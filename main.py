import asyncio
import logging
import os
import re
from typing import List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import yt_dlp
import shutil
from aiohttp import web

from utils import EnhancedSpotifyParser, MusicSearchEngine, clean_filename, format_file_size, JioSaavnProvider, SoundCloudProvider, YTMusicProvider

# Загружаем переменные окружения
load_dotenv()

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler('bot.log')
    ]
)
logger = logging.getLogger(__name__)
# Проверка наличия ffmpeg
def is_ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None

# Инициализация бота
bot = Bot(token=os.getenv('TELEGRAM_TOKEN'))
dp = Dispatcher()

# Инициализация Spotify API
spotify_client_id = os.getenv('SPOTIFY_CLIENT_ID')
spotify_client_secret = os.getenv('SPOTIFY_CLIENT_SECRET')

# Создаем экземпляр парсера Spotify
spotify_parser = EnhancedSpotifyParser(spotify_client_id, spotify_client_secret)


class MusicDownloader:
    """Класс для поиска и скачивания музыки"""
    
    @staticmethod
    async def search_and_download(query: str, track_info: dict = None) -> Optional[str]:
        """Ищет и скачивает музыку по запросу"""
        try:
            # Очищаем запрос от недопустимых символов
            clean_query = clean_filename(query)
            logger.info(f"Download start. Query='{clean_query}'")
            
            # 1) Пробуем онлайн провайдера (JioSaavn)
            try:
                logger.info("Provider: JioSaavn")
                async with JioSaavnProvider() as provider:
                    path = await provider.download_best(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"JioSaavn success: {path}")
                        return path
            except Exception as _:
                logger.exception("JioSaavn error")
            
            # 2) Пробуем SoundCloud: ищем несколько кандидатов и качаем через yt-dlp
            try:
                logger.info("Provider: SoundCloud")
                async with SoundCloudProvider() as sc:
                    sc_urls = await sc.search_urls(clean_query, limit=3)
                logger.info(f"SoundCloud candidates: {len(sc_urls)}")
                if sc_urls:
                    ydl_sc_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': f'downloads/%(title)s.%(ext)s',
                        'postprocessors': [
                            {
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }
                        ],
                        'prefer_ffmpeg': True,
                        'noprogress': True,
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'windowsfilenames': True,
                    }
                    import yt_dlp as _yt
                    with _yt.YoutubeDL(ydl_sc_opts) as ydl2:
                        for url in sc_urls:
                            try:
                                logger.info(f"SoundCloud try: {url}")
                                info = ydl2.extract_info(url, download=True)
                                title = info.get('title') or 'track'
                                candidate = f"downloads/{clean_filename(title)}.mp3"
                                if os.path.exists(candidate):
                                    logger.info(f"SoundCloud success: {candidate}")
                                    return candidate
                            except Exception:
                                logger.exception("SoundCloud candidate failed")
                                continue
            except Exception:
                logger.exception("SoundCloud provider error")
            
            # 2.5) Пробуем YouTube Music: ищем песни и качаем лучшего кандидата через yt-dlp
            try:
                ytm = YTMusicProvider()
                ytm_candidates = ytm.search(clean_query, limit=7)
                # если есть track_info, переформируем запросы и расширим список
                if track_info:
                    extra_q = f"{track_info.get('name','')} {track_info.get('artist','')}".strip()
                    if extra_q and extra_q.lower() != clean_query.lower():
                        ytm_candidates += ytm.search(extra_q, limit=7)
                # сортируем по близости длительности, если известна
                target_dur = track_info.get('duration') if track_info else None
                if target_dur:
                    ytm_candidates.sort(key=lambda c: abs((c.get('duration') or 0) - target_dur))
                ydl_ytm_opts = {
                    'format': 'bestaudio/best',
                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                    'postprocessors': [
                        {
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }
                    ],
                    'prefer_ffmpeg': True,
                    'noprogress': True,
                    'noplaylist': True,
                    'quiet': True,
                    'no_warnings': True,
                    'windowsfilenames': True,
                }
                import yt_dlp as _ytm
                with _ytm.YoutubeDL(ydl_ytm_opts) as ydlm:
                    tried = 0
                    for cand in ytm_candidates:
                        if tried >= 5:
                            break
                        tried += 1
                        url = cand.get('url')
                        if not url:
                            continue
                        try:
                            info = ydlm.extract_info(url, download=True)
                            title = info.get('title') or cand.get('title') or 'track'
                            candidate = f"downloads/{clean_filename(title)}.mp3"
                            if os.path.exists(candidate):
                                return candidate
                        except Exception:
                            continue
            except Exception:
                pass

            # Настройки для yt-dlp с обходом блокировок
            ydl_opts = {
                'format': 'bestaudio/best',
                'outtmpl': f'downloads/%(title)s.%(ext)s',
                'postprocessors': [
                    {
                        'key': 'FFmpegExtractAudio',
                        'preferredcodec': 'mp3',
                        'preferredquality': '192',
                    }
                ],
                'prefer_ffmpeg': True,
                'noprogress': True,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,  # 50MB лимит
                'windowsfilenames': True,
                # Обход блокировок YouTube
                'http_headers': {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36',
                    'Accept-Language': 'en-US,en;q=0.9',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['android', 'web'],
                        'skip': ['dash', 'hls'],
                    }
                },
                'retries': 3,
                'fragment_retries': 3,
                'retry_sleep': 2,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                logger.info("Provider: YouTube search")
                # Ищем до 5 видео и выбираем наиболее подходящее
                search_results = ydl.extract_info(
                    f"ytsearch5:{clean_query}",
                    download=False
                )
                
                if not search_results or 'entries' not in search_results:
                    logger.info("YouTube returned no entries")
                    return None
                
                entries = [e for e in (search_results.get('entries') or []) if e]
                if not entries:
                    logger.info("YouTube entries empty")
                    return None
                
                # Подбор по длительности (если известна)
                target_duration = None
                if track_info and isinstance(track_info.get('duration'), int) and track_info['duration'] > 0:
                    target_duration = track_info['duration']
                
                def duration_score(e):
                    d = e.get('duration') or 0
                    if target_duration is None:
                        return 0
                    return abs(d - target_duration)
                
                # Сортируем: сначала по длительности, затем по просмотрам (если есть)
                entries.sort(key=lambda e: (duration_score(e), -(e.get('view_count') or 0)))
                best = entries[0]
                video_url = best.get('webpage_url') or best.get('url')
                if not video_url:
                    logger.info("Best YouTube entry has no URL")
                    return None
                
                # Скачиваем
                logger.info(f"YouTube downloading: {video_url}")
                ydl.download([video_url])
                
                # Возвращаем путь к файлу
                title = best.get('title') or 'track'
                filename = f"downloads/{clean_filename(title)}.mp3"
                logger.info(f"YouTube success: {filename}")
                return filename
                
        except Exception as e:
            logger.exception("Downloader fatal error")
            return None


@dp.message(Command("start"))
async def start_handler(message: Message):
    """Обработчик команды /start"""
    welcome_text = """
🎵 Добро пожаловать в Spotify Music Bot!

Отправьте мне ссылку на трек, плейлист или альбом Spotify, и я найду и отправлю вам MP3 файл.

Поддерживаемые форматы:
• https://open.spotify.com/track/...
• https://open.spotify.com/playlist/...
• https://open.spotify.com/album/...
• spotify:track:...
• spotify:playlist:...
• spotify:album:...

Команды:
/start - Начать работу
/help - Помощь

Ограничения:
• Плейлисты и альбомы: максимум 15 треков
• Размер файла: максимум 50MB
• Качество: 192kbps MP3
    """
    
    await message.answer(welcome_text)


@dp.message(Command("help"))
async def help_handler(message: Message):
    """Обработчик команды /help"""
    help_text = """
📖 Помощь по использованию бота

Как использовать:
1. Скопируйте ссылку на трек, плейлист или альбом Spotify
2. Отправьте ссылку боту
3. Дождитесь обработки и получения MP3 файла

Поддерживаемые форматы:
• Треки: https://open.spotify.com/track/...
• Плейлисты: https://open.spotify.com/playlist/...
• Альбомы: https://open.spotify.com/album/...

Примеры ссылок:
• https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh
• https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M
• https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo

Ограничения:
• Плейлисты и альбомы: максимум 15 треков
• Размер файла: максимум 50MB
• Качество: 192kbps MP3

Примечание: Бот работает через поиск в YouTube, поэтому качество может варьироваться.
    """
    
    await message.answer(help_text)


@dp.message(F.text)
async def process_spotify_link(message: Message):
    """Обработчик ссылок Spotify"""
    text = message.text.strip()
    
    if not spotify_parser.extract_ids_from_url(text):
        await message.answer("❌ Пожалуйста, отправьте ссылку на трек или плейлист Spotify.")
        return
    
    # Отправляем сообщение о начале обработки
    processing_msg = await message.answer("🔄 Обрабатываю ссылку...")
    
    try:
        # Извлекаем ID из ссылки
        ids = spotify_parser.extract_ids_from_url(text)
        
        if ids['track']:
            # Обрабатываем трек
            await process_track(message, ids['track'], processing_msg)
        elif ids['playlist']:
            # Обрабатываем плейлист
            await process_playlist(message, ids['playlist'], processing_msg)
        elif ids['album']:
            # Обрабатываем альбом
            await process_album(message, ids['album'], processing_msg)
        else:
            await processing_msg.edit_text("❌ Не удалось распознать ссылку Spotify.")
            
    except Exception as e:
        logger.error(f"Error processing Spotify link: {e}")
        await processing_msg.edit_text("❌ Произошла ошибка при обработке ссылки.")


async def process_track(message: Message, track_id: str, processing_msg: types.Message):
    """Обрабатывает отдельный трек"""
    try:
        # Получаем информацию о треке
        track_info = await spotify_parser.get_track_info(track_id)
        
        if not track_info:
            await processing_msg.edit_text("❌ Не удалось получить информацию о треке.")
            return
        
        # Обновляем сообщение
        await processing_msg.edit_text(
            f"🎵 Найден трек: {track_info['name']} - {track_info['artist']}\n"
            f"⏱️ Длительность: {track_info['duration_formatted']}\n"
            f"🔄 Ищу и скачиваю..."
        )
        
        # Формируем поисковый запрос
        search_query = spotify_parser.create_search_query(track_info)
        
        # Скачиваем музыку
        file_path = await MusicDownloader.search_and_download(search_query, track_info)
        
        if file_path and os.path.exists(file_path):
            # Получаем размер файла
            file_size = os.path.getsize(file_path)
            
            # Отправляем файл
            await message.answer_document(
                document=types.FSInputFile(file_path),
                caption=f"🎵 {track_info['name']} - {track_info['artist']}\n"
                       f"⏱️ {track_info['duration_formatted']} | 📁 {format_file_size(file_size)}"
            )
            
            # Удаляем временный файл
            os.remove(file_path)
            
            await processing_msg.delete()
        else:
            await processing_msg.edit_text("❌ Не удалось найти или скачать трек.")
            
    except Exception as e:
        logger.error(f"Error processing track: {e}")
        await processing_msg.edit_text("❌ Произошла ошибка при обработке трека.")


async def process_playlist(message: Message, playlist_id: str, processing_msg: types.Message):
    """Обрабатывает плейлист"""
    try:
        # Получаем информацию о плейлисте
        playlist_info = await spotify_parser.get_playlist_info(playlist_id)
        
        if not playlist_info:
            await processing_msg.edit_text("❌ Не удалось получить информацию о плейлисте.")
            return
        
        tracks = playlist_info['tracks']
        
        if len(tracks) > 15:
            await processing_msg.edit_text(
                f"⚠️ Плейлист '{playlist_info['name']}' содержит {len(tracks)} треков.\n"
                f"Для больших плейлистов рекомендуется обрабатывать треки по отдельности.\n"
                f"Максимум для обработки: 15 треков."
            )
            return
        
        # Обновляем сообщение
        await processing_msg.edit_text(
            f"🎵 Плейлист: {playlist_info['name']}\n"
            f"👤 Автор: {playlist_info['owner']}\n"
            f"📊 Треков: {len(tracks)}\n"
            f"🔄 Начинаю скачивание..."
        )
        
        downloaded_count = 0
        
        for i, track in enumerate(tracks, 1):
            try:
                # Обновляем прогресс
                await processing_msg.edit_text(
                    f"🎵 Плейлист: {playlist_info['name']}\n"
                    f"📥 Скачиваю {i}/{len(tracks)}: {track['name']} - {track['artist']}"
                )
                
                # Формируем поисковый запрос
                search_query = spotify_parser.create_search_query(track)
                
                # Скачиваем музыку
                file_path = await MusicDownloader.search_and_download(search_query, track)
                
                if file_path and os.path.exists(file_path):
                    # Получаем размер файла
                    file_size = os.path.getsize(file_path)
                    
                    # Отправляем файл
                    await message.answer_document(
                        document=types.FSInputFile(file_path),
                        caption=f"🎵 {track['name']} - {track['artist']}\n"
                               f"⏱️ {track['duration_formatted']} | 📁 {format_file_size(file_size)}"
                    )
                    
                    # Удаляем временный файл
                    os.remove(file_path)
                    downloaded_count += 1
                    
                    # Небольшая пауза между скачиваниями
                    await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error downloading track {track['name']}: {e}")
                continue
        
        await processing_msg.edit_text(
            f"✅ Скачивание завершено!\n"
            f"🎵 Плейлист: {playlist_info['name']}\n"
            f"📊 Успешно скачано: {downloaded_count}/{len(tracks)} треков"
        )
        
    except Exception as e:
        logger.error(f"Error processing playlist: {e}")
        await processing_msg.edit_text("❌ Произошла ошибка при обработке плейлиста.")


async def process_album(message: Message, album_id: str, processing_msg: types.Message):
    """Обрабатывает альбом"""
    try:
        # Получаем информацию об альбоме
        album_info = await spotify_parser.get_album_info(album_id)
        
        if not album_info:
            await processing_msg.edit_text("❌ Не удалось получить информацию об альбоме.")
            return
        
        tracks = album_info['tracks']
        
        if len(tracks) > 15:
            await processing_msg.edit_text(
                f"⚠️ Альбом '{album_info['name']}' содержит {len(tracks)} треков.\n"
                f"Для больших альбомов рекомендуется обрабатывать треки по отдельности.\n"
                f"Максимум для обработки: 15 треков."
            )
            return
        
        # Обновляем сообщение
        await processing_msg.edit_text(
            f"🎵 Альбом: {album_info['name']}\n"
            f"👤 Исполнитель: {album_info['artist']}\n"
            f"📅 Год: {album_info['release_date']}\n"
            f"📊 Треков: {len(tracks)}\n"
            f"🔄 Начинаю скачивание..."
        )
        
        downloaded_count = 0
        
        for i, track in enumerate(tracks, 1):
            try:
                # Обновляем прогресс
                await processing_msg.edit_text(
                    f"🎵 Альбом: {album_info['name']}\n"
                    f"📥 Скачиваю {i}/{len(tracks)}: {track['name']}"
                )
                
                # Формируем поисковый запрос
                search_query = spotify_parser.create_search_query(track)
                
                # Скачиваем музыку
                file_path = await MusicDownloader.search_and_download(search_query, track)
                
                if file_path and os.path.exists(file_path):
                    # Получаем размер файла
                    file_size = os.path.getsize(file_path)
                    
                    # Отправляем файл
                    await message.answer_document(
                        document=types.FSInputFile(file_path),
                        caption=f"🎵 {track['name']} - {track['artist']}\n"
                               f"⏱️ {track['duration_formatted']} | 📁 {format_file_size(file_size)}"
                    )
                    
                    # Удаляем временный файл
                    os.remove(file_path)
                    downloaded_count += 1
                    
                    # Небольшая пауза между скачиваниями
                    await asyncio.sleep(2)
                
            except Exception as e:
                logger.error(f"Error downloading track {track['name']}: {e}")
                continue
        
        await processing_msg.edit_text(
            f"✅ Скачивание завершено!\n"
            f"🎵 Альбом: {album_info['name']}\n"
            f"📊 Успешно скачано: {downloaded_count}/{len(tracks)} треков"
        )
        
    except Exception as e:
        logger.error(f"Error processing album: {e}")
        await processing_msg.edit_text("❌ Произошла ошибка при обработке альбома.")


async def health_check(request):
    """Health check endpoint для Railway"""
    return web.Response(text="Spotify Music Bot is running", status=200)

async def main():
    """Основная функция"""
    # Проверяем переменные окружения
    if not os.getenv('TELEGRAM_TOKEN'):
        logger.error("TELEGRAM_TOKEN not found in environment variables")
        return
    
    # Создаем папку для загрузок
    os.makedirs("downloads", exist_ok=True)
    
    logger.info("Starting Spotify Music Bot...")
    logger.info(f"FFmpeg available: {is_ffmpeg_available()}")
    logger.info(f"Spotify API configured: {bool(spotify_client_id and spotify_client_secret)}")
    
    # Создаем HTTP сервер для health check
    app = web.Application()
    app.router.add_get('/', health_check)
    app.router.add_get('/health', health_check)
    
    # Запускаем HTTP сервер в фоне
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv('PORT', 8000))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"HTTP server started on port {port}")
    
    try:
        # Запускаем Telegram бота
        await dp.start_polling(bot)
    except Exception as e:
        logger.error(f"Bot startup error: {e}")
        raise


if __name__ == "__main__":
    asyncio.run(main())
