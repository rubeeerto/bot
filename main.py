import asyncio
import os
import re
import shutil
import tempfile
from dataclasses import dataclass
from typing import List, Optional

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import yt_dlp
import requests

try:
	import spotipy
	from spotipy.oauth2 import SpotifyClientCredentials
except Exception:
	spotipy = None

SPOTIFY_TRACK_RE = re.compile(r"https?://open\.spotify\.com/track/([a-zA-Z0-9]+)")
SPOTIFY_PLAYLIST_RE = re.compile(r"https?://open\.spotify\.com/playlist/([a-zA-Z0-9]+)")


@dataclass
class TrackInfo:
	title: str
	artists: List[str]

	@property
	def display_title(self) -> str:
		artists = ", ".join(self.artists) if self.artists else ""
		return f"{self.title} - {artists}" if artists else self.title


def load_env():
	load_dotenv()


def get_spotify_client():
	client_id = os.getenv("SPOTIFY_CLIENT_ID")
	client_secret = os.getenv("SPOTIFY_CLIENT_SECRET")
	if not client_id or not client_secret:
		return None
	if spotipy is None:
		return None
	auth_manager = SpotifyClientCredentials(client_id=client_id, client_secret=client_secret)
	return spotipy.Spotify(auth_manager=auth_manager)


def resolve_spotify_track(url: str, sp_client=None) -> Optional[TrackInfo]:
	m = SPOTIFY_TRACK_RE.search(url)
	if not m:
		return None
	track_id = m.group(1)
	try:
		if sp_client is not None:
			t = sp_client.track(track_id)
			name = t["name"]
			artists = [a["name"] for a in t.get("artists", [])]
			return TrackInfo(title=name, artists=artists)
		# Fallback: oEmbed
		oembed = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=15).json()
		title = oembed.get("title")
		# oEmbed title is like "Song Name - Artist"
		if title and " - " in title:
			t, a = title.split(" - ", 1)
			return TrackInfo(title=t.strip(), artists=[a.strip()])
		return TrackInfo(title=title or "Unknown", artists=[])
	except Exception:
		return None


def resolve_spotify_playlist(url: str, sp_client=None) -> List[TrackInfo]:
	m = SPOTIFY_PLAYLIST_RE.search(url)
	if not m or sp_client is None:
		return []
	playlist_id = m.group(1)
	items: List[TrackInfo] = []
	try:
		results = sp_client.playlist_items(playlist_id, additional_types=("track",), limit=100)
		while results:
			for it in results.get("items", []):
				tr = it.get("track")
				if not tr:
					continue
				name = tr.get("name")
				artists = [a.get("name") for a in (tr.get("artists") or []) if a]
				if name:
					items.append(TrackInfo(title=name, artists=artists))
			if results.get("next"):
				results = sp_client.next(results)
			else:
				break
	except Exception:
		return items
	return items


def build_search_query(info: TrackInfo) -> str:
	# Prefer official audio by adding keywords
	return f"{info.title} {', '.join(info.artists)} audio"


def sanitize_filename(name: str) -> str:
	return re.sub(r"[\\/:*?\"<>|]", "_", name).strip()[:150]


async def download_youtube_as_mp3(query: str, out_dir: str) -> Optional[str]:
	# Uses yt-dlp to search and extract bestaudio, convert to mp3
	output_tpl = os.path.join(out_dir, "%(title)s.%(ext)s")
	ydl_opts = {
		"format": "bestaudio/best",
		"outtmpl": output_tpl,
		"noplaylist": True,
		"quiet": True,
		"no_warnings": True,
		"postprocessors": [
			{
				"key": "FFmpegExtractAudio",
				"preferredcodec": "mp3",
				"preferredquality": "192",
			},
			{
				"key": "FFmpegMetadata",
			},
		],
		"default_search": "ytsearch",
		"max_downloads": 1,
	}
	loop = asyncio.get_event_loop()

	def run_ydl():
		with yt_dlp.YoutubeDL(ydl_opts) as ydl:
			info = ydl.extract_info(query, download=True)
			if "entries" in info:
				info = info["entries"][0]
			# After postprocessing, extension is mp3 and output is at out_dir
			title = info.get("title") or "audio"
			# yt-dlp may sanitize title; find resulting file
			for fn in os.listdir(out_dir):
				if fn.lower().endswith(".mp3"):
					return os.path.join(out_dir, fn)
			return None

	return await loop.run_in_executor(None, run_ydl)


async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
	try:
		await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
	except Exception:
		pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text(
		"Отправь ссылку на Spotify трек или плейлист. Я найду на YouTube и пришлю MP3."
	)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
	if not update.message or not update.message.text:
		return
	text = update.message.text.strip()
	sp_client = get_spotify_client()

	track_info = resolve_spotify_track(text, sp_client)
	if track_info:
		await process_single_track(update, context, track_info)
		return

	playlist_infos = resolve_spotify_playlist(text, sp_client)
	if playlist_infos:
		await update.message.reply_text(
			f"Найден плейлист: {len(playlist_infos)} трек(ов). Начинаю загрузку по одному..."
		)
		for idx, info in enumerate(playlist_infos, start=1):
			try:
				await process_single_track(update, context, info, prefix=f"[{idx}/{len(playlist_infos)}] ")
			except Exception:
				continue
		return

	await update.message.reply_text("Пришлите ссылку на Spotify трек или плейлист.")


async def process_single_track(update: Update, context: ContextTypes.DEFAULT_TYPE, info: TrackInfo, prefix: str = ""):
	chat_id = update.effective_chat.id
	title = info.display_title
	await update.message.reply_text(f"{prefix}Ищу на YouTube: {title}")
	await send_typing(context, chat_id)

	with tempfile.TemporaryDirectory() as tmpdir:
		file_path = await download_youtube_as_mp3(build_search_query(info), tmpdir)
		if not file_path or not os.path.exists(file_path):
			await update.message.reply_text(f"Не удалось скачать: {title}")
			return
		# Rename to desired filename
		desired_name = sanitize_filename(title) + ".mp3"
		final_path = os.path.join(tmpdir, desired_name)
		try:
			shutil.move(file_path, final_path)
		except Exception:
			final_path = file_path

		await send_typing(context, chat_id)
		try:
			with open(final_path, "rb") as f:
				await update.message.reply_audio(audio=f, filename=os.path.basename(final_path), title=title)
		except Exception:
			# Fallback to document
			with open(final_path, "rb") as f:
				await update.message.reply_document(document=InputFile(f, filename=os.path.basename(final_path)))


def main():
	load_env()
	token = os.getenv("BOT_TOKEN")
	if not token:
		raise RuntimeError("BOT_TOKEN not set in environment/.env")

	app = Application.builder().token(token).concurrent_updates(True).build()

	app.add_handler(CommandHandler("start", start))
	app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

	print("Bot started. Waiting for messages...")
	app.run_polling()


if __name__ == "__main__":
	try:
		main()
	except (KeyboardInterrupt, SystemExit):
		pass
