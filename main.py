import asyncio
import os
import re
import shutil
import tempfile
import base64
import html
from dataclasses import dataclass
from typing import List, Optional, Dict, Any

from dotenv import load_dotenv
from telegram import Update, InputFile
from telegram.constants import ChatAction
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

import yt_dlp
import requests
# Добавим импорты для альтернативных загрузчиков
try:
	import youtube_dl
except ImportError:
	youtube_dl = None
try:
	from pytube import YouTube
except ImportError:
	YouTube = None

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
	duration_seconds: Optional[int] = None

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
			dur_ms = t.get("duration_ms") or 0
			duration_seconds = int(round(dur_ms / 1000)) if dur_ms else None
			return TrackInfo(title=name, artists=artists, duration_seconds=duration_seconds)
		# Fallback: oEmbed
		oembed = requests.get("https://open.spotify.com/oembed", params={"url": url}, timeout=15).json()
		title = oembed.get("title")
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
				dur_ms = (tr.get("duration_ms") or 0)
				duration_seconds = int(round(dur_ms / 1000)) if dur_ms else None
				if name:
					items.append(TrackInfo(title=name, artists=artists, duration_seconds=duration_seconds))
			if results.get("next"):
				results = sp_client.next(results)
			else:
				break
	except Exception:
		return items
	return items


def build_search_query(info: TrackInfo) -> str:
	# Prefer precise search terms
	base = f"{info.title} {', '.join(info.artists)}" if info.artists else info.title
	return f"{base} official audio"


def sanitize_filename(name: str) -> str:
	return re.sub(r"[\\/:*?\"<>|]", "_", name).strip()[:150]


def _common_http_headers() -> dict:
	return {
		"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
		"Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
	}


def _write_cookies_from_env() -> Optional[str]:
	"""If COOKIES_FILE_B64 env is set, write it to a temp file and return path."""
	b64 = os.getenv("COOKIES_FILE_B64")
	if not b64:
		return None
	try:
		data = base64.b64decode(b64)
		tmp = tempfile.NamedTemporaryFile(delete=False)
		tmp.write(data)
		tmp.flush()
		tmp.close()
		return tmp.name
	except Exception:
		return None


def _search_bandcamp_candidates(query: str, limit: int = 5) -> List[str]:
	"""Use DuckDuckGo HTML to find Bandcamp track URLs."""
	q = f"site:bandcamp.com/track {query}"
	headers = _common_http_headers()
	r = requests.get("https://duckduckgo.com/html/", params={"q": q}, headers=headers, timeout=15)
	if r.status_code != 200:
		return []
	html_text = r.text
	urls: List[str] = []
	for m in re.finditer(r"href=\"(/l/\?kh=[^\"&]*&uddg=([^\"]+))\"", html_text):
		enc = m.group(2)
		try:
			decoded = requests.utils.unquote(enc)
			decoded = html.unescape(decoded)
			if "bandcamp.com/track/" in decoded:
				urls.append(decoded)
				if len(urls) >= limit:
					break
		except Exception:
			continue
	return urls


def _norm(s: str) -> str:
	return re.sub(r"\s+", " ", s.lower()).strip()


def _score_candidate(track: TrackInfo, cand: Dict[str, Any]) -> float:
	# Score by title/artist match and duration proximity
	target_title = _norm(track.title)
	artist_blob = _norm(" ".join(track.artists)) if track.artists else ""
	cand_title = _norm(cand.get("title") or "")
	cand_uploader = _norm(cand.get("uploader") or cand.get("channel") or "")
	cand_channel = _norm(cand.get("channel") or "")
	score = 0.0
	if target_title and target_title in cand_title:
		score += 3.0
	if artist_blob and artist_blob and any(a in cand_title for a in artist_blob.split() if len(a) > 2):
		score += 1.5
	if artist_blob and (artist_blob in cand_uploader or artist_blob in cand_channel):
		score += 1.0
	# Prefer "Topic" channels and "official audio"
	if "topic" in cand_channel:
		score += 1.0
	if "official" in cand_title or "audio" in cand_title:
		score += 0.5
	# Duration proximity
	if track.duration_seconds and cand.get("duration"):
		diff = abs(int(cand["duration"]) - int(track.duration_seconds))
		if diff <= 2:
			score += 3.0
		elif diff <= 5:
			score += 2.0
		elif diff <= 10:
			score += 1.0
	return score


async def download_audio_with_fallbacks(query: str, out_dir: str, track: Optional[TrackInfo] = None) -> Optional[str]:
	# Try YouTube, then SoundCloud, then Bandcamp
	loop = asyncio.get_event_loop()

	def list_candidates_yt() -> List[Dict[str, Any]]:
		opts = {
			"quiet": True,
			"no_warnings": True,
			"noplaylist": True,
			"default_search": "ytsearch",
			"extract_flat": True,
			"http_headers": _common_http_headers(),
			"extractor_args": {
				"youtube": {
					"player_client": ["android"],
					"player_skip": ["configs", "webpage"],
				}
			},
			"sleep_requests": 1.0,
		}
		search_query = f"ytsearch15:{query}"
		with yt_dlp.YoutubeDL(opts) as ydl:
			info = ydl.extract_info(search_query, download=False)
			entries = info.get("entries") or []
			cands: List[Dict[str, Any]] = []
			for e in entries:
				cands.append({
					"url": e.get("url") or e.get("webpage_url"),
					"title": e.get("title"),
					"duration": e.get("duration"),
					"uploader": e.get("uploader"),
					"channel": e.get("channel") or e.get("channel_id"),
				})
			return [c for c in cands if c.get("url")]

	def list_candidates_sc() -> List[Dict[str, Any]]:
		opts = {
			"quiet": True,
			"no_warnings": True,
			"noplaylist": True,
			"extract_flat": True,
			"http_headers": _common_http_headers(),
			"sleep_requests": 1.0,
		}
		search_query = f"scsearch15:{query}"
		with yt_dlp.YoutubeDL(opts) as ydl:
			info = ydl.extract_info(search_query, download=False)
			entries = info.get("entries") or []
			cands: List[Dict[str, Any]] = []
			for e in entries:
				cands.append({
					"url": e.get("url") or e.get("webpage_url"),
					"title": e.get("title"),
					"duration": e.get("duration"),
					"uploader": e.get("uploader"),
					"channel": e.get("channel") or e.get("channel_id"),
				})
			return [c for c in cands if c.get("url")]

	def list_candidates_bc() -> List[Dict[str, Any]]:
		urls = _search_bandcamp_candidates(query, limit=5)
		return [{"url": u, "title": u} for u in urls]

	base_opts = {
		"format": "bestaudio/best",
		"outtmpl": os.path.join(out_dir, "%(title)s.%(ext)s"),
		"noplaylist": True,
		"quiet": True,
		"no_warnings": True,
		"retries": 3,
		"socket_timeout": 30,
		"http_headers": _common_http_headers(),
		"extractor_args": {
			"youtube": {
				"player_client": ["android"],
				"player_skip": ["configs", "webpage"],
			},
			"soundcloud": {
				"client_id": [os.getenv("SOUNDCLOUD_CLIENT_ID")] if os.getenv("SOUNDCLOUD_CLIENT_ID") else None
			}
		},
		"sleep_requests": 1.0,
		"throttledratelimit": 1024 * 64,
		"ratelimit": 1024 * 256,
		"concurrent_fragment_downloads": 1,
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
	}
	proxy = os.getenv("HTTPS_PROXY") or os.getenv("HTTP_PROXY")
	if proxy:
		base_opts["proxy"] = proxy
	cookies_path = _write_cookies_from_env()
	if cookies_path:
		base_opts["cookiefile"] = cookies_path

	def try_download(url: str) -> Optional[str]:
		# 1. yt-dlp
		try:
			with yt_dlp.YoutubeDL(base_opts) as ydl:
				info = ydl.extract_info(url, download=True)
				if "entries" in info:
					info = info["entries"][0]
				for fn in os.listdir(out_dir):
					if fn.lower().endswith(".mp3"):
						return os.path.join(out_dir, fn)
				return None
		except Exception as e:
			print(f"yt-dlp failed: {e}")
		# 2. youtube-dl fallback
		if youtube_dl is not None:
			try:
				ydl_opts = base_opts.copy()
				ydl_opts.pop("extractor_args", None)  # youtube-dl не поддерживает extractor_args
				with youtube_dl.YoutubeDL(ydl_opts) as ydl:
					info = ydl.extract_info(url, download=True)
					if "entries" in info:
						info = info["entries"][0]
					for fn in os.listdir(out_dir):
						if fn.lower().endswith(".mp3"):
							return os.path.join(out_dir, fn)
					return None
			except Exception as e:
				print(f"youtube-dl failed: {e}")
		# 3. pytube fallback (только для YouTube)
		if YouTube is not None and ("youtube.com" in url or "youtu.be" in url):
			try:
				yt = YouTube(url)
				stream = yt.streams.filter(only_audio=True).first()
				if stream:
					out_file = stream.download(output_path=out_dir)
					# Преобразуем в mp3, если нужно
					if not out_file.lower().endswith(".mp3"):
						import subprocess
						mp3_path = os.path.splitext(out_file)[0] + ".mp3"
						subprocess.run([
							"ffmpeg", "-y", "-i", out_file, mp3_path
						], check=True)
						os.remove(out_file)
						return mp3_path
					return out_file
				return None
			except Exception as e:
				print(f"pytube failed: {e}")
		return None

	# Aggregate and rank candidates
	yt_candidates = await loop.run_in_executor(None, list_candidates_yt)
	sc_candidates = await loop.run_in_executor(None, list_candidates_sc)
	bc_candidates = await loop.run_in_executor(None, list_candidates_bc)
	all_candidates: List[Dict[str, Any]] = []
	all_candidates.extend(yt_candidates)
	all_candidates.extend(sc_candidates)
	all_candidates.extend(bc_candidates)
	if not all_candidates:
		return None

	if track is not None:
		all_candidates.sort(key=lambda c: _score_candidate(track, c), reverse=True)

	for cand in all_candidates:
		result = await loop.run_in_executor(None, try_download, cand["url"])
		if result:
			return result

	return None


async def send_typing(ctx: ContextTypes.DEFAULT_TYPE, chat_id: int):
	try:
		await ctx.bot.send_chat_action(chat_id=chat_id, action=ChatAction.UPLOAD_DOCUMENT)
	except Exception:
		pass


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
	await update.message.reply_text(
		"Отправь ссылку на Spotify трек или плейлист. Я найду на YouTube/SoundCloud/Bandcamp и пришлю MP3."
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
				await asyncio.sleep(1.0)
			except Exception:
				continue
		return

	await update.message.reply_text("Пришлите ссылку на Spotify трек или плейлист.")


async def process_single_track(update: Update, context: ContextTypes.DEFAULT_TYPE, info: TrackInfo, prefix: str = ""):
	chat_id = update.effective_chat.id
	title = info.display_title
	await update.message.reply_text(f"{prefix}Ищу: {title}")
	await send_typing(context, chat_id)

	with tempfile.TemporaryDirectory() as tmpdir:
		file_path = await download_audio_with_fallbacks(build_search_query(info), tmpdir, track=info)
		if not file_path or not os.path.exists(file_path):
			await update.message.reply_text(f"Не удалось скачать: {title}. Пробуйте другой трек или позже.")
			return
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
	# Start polling; recommend ensuring only one instance is running on Railway
	app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
	try:
		main()
	except (KeyboardInterrupt, SystemExit):
		pass