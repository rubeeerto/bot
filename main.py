import asyncio
import logging
import os
import re
import time
from typing import List, Optional, Tuple

import aiohttp
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton
from dotenv import load_dotenv
import yt_dlp
import shutil
from aiohttp import web

from utils import EnhancedSpotifyParser, MusicSearchEngine, clean_filename, format_file_size, JioSaavnProvider, SoundCloudProvider, YTMusicProvider, AlternativeMusicProvider, BandcampProvider, ArchiveOrgProvider, FreeMusicArchiveProvider, JamendoProvider, MixcloudProvider, AlternativeYouTubeProvider, VKMusicProvider, YandexMusicProvider, DeezerProvider, AudiomackProvider, MusopenProvider, PleerNetProvider, MP3JuicesProvider, ZaycevProvider, MyzukaProvider, RuTrackProvider, RedMp3Provider, Mp3SkullsProvider, Music7sProvider, Mp3DownloadProvider, Beemp3sProvider, VkMusicFunProvider, ImprovedSearchEngine, EnhancedSoundCloudProvider

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

# Семафор для ограничения одновременных загрузок (максимум 3 одновременно)
download_semaphore = asyncio.Semaphore(3)

# Счетчик активных загрузок
active_downloads = 0

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
            
            # Небольшая задержка между провайдерами
            await asyncio.sleep(0.5)
            
            # 2) Пробуем улучшенный SoundCloud с фильтрацией версий
            try:
                logger.info("Provider: Enhanced SoundCloud")
                async with EnhancedSoundCloudProvider() as sc:
                    path = await sc.search_and_download_best(clean_query, track_info)
                    if path and os.path.exists(path):
                        logger.info(f"Enhanced SoundCloud success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Enhanced SoundCloud error: {e}")
            
            await asyncio.sleep(0.3)
                
            # 2.1) Пробуем обычный SoundCloud как fallback с фильтрацией
            try:
                logger.info("Provider: SoundCloud Fallback")
                async with SoundCloudProvider() as sc:
                    sc_urls = await sc.search_urls(clean_query, limit=5)
                logger.info(f"SoundCloud candidates: {len(sc_urls)}")
                if sc_urls:
                    # Сначала анализируем кандидатов для фильтрации
                    candidate_info = []
                    for url in sc_urls:
                        try:
                            import yt_dlp
                            ydl_info_opts = {
                                'quiet': True,
                                'no_warnings': True,
                                'extract_flat': True,
                            }
                            with yt_dlp.YoutubeDL(ydl_info_opts) as ydl_info:
                                info = ydl_info.extract_info(url, download=False)
                                if info:
                                    candidate_info.append({
                                        'url': url,
                                        'title': info.get('title', ''),
                                        'duration': info.get('duration', 0),
                                        'view_count': info.get('view_count', 0)
                                    })
                        except Exception:
                            continue
                    
                    # Фильтруем кандидатов
                    filtered_candidates = ImprovedSearchEngine.filter_original_versions(candidate_info, track_info)
                    
                    if not filtered_candidates:
                        logger.info("SoundCloud Fallback: No good candidates after filtering")
                        # Если нет хороших кандидатов, пробуем первый без фильтрации
                        filtered_candidates = candidate_info[:1]
                    
                    # Скачиваем лучшего кандидата
                    best_candidate = filtered_candidates[0]
                    logger.info(f"SoundCloud Fallback: Best candidate '{best_candidate['title']}'")
                    
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
                        # Исправления для FFmpeg проблем
                        'ffmpeg_location': None,  # Используем системный FFmpeg
                        'postprocessor_args': {
                            'FFmpegExtractAudio': [
                                '-acodec', 'mp3',
                                '-ab', '192k',
                                '-ar', '44100',
                                '-ac', '2',
                                '-avoid_negative_ts', 'make_zero',
                                '-fflags', '+genpts',
                                '-strict', '-2',  # Разрешаем экспериментальные кодеки
                                '-max_muxing_queue_size', '1024'  # Увеличиваем буфер
                            ]
                        },
                        'ignoreerrors': True,  # Игнорируем ошибки постобработки
                        'no_check_certificate': True,  # Отключаем проверку сертификатов
                    }
                    import yt_dlp as _yt
                    with _yt.YoutubeDL(ydl_sc_opts) as ydl2:
                        try:
                            logger.info(f"SoundCloud try: {best_candidate['url']}")
                            info = ydl2.extract_info(best_candidate['url'], download=True)
                            title = info.get('title') or 'track'
                            
                            # Ищем скачанный файл в разных форматах
                            base_name = clean_filename(title)
                            for ext in ['mp3', 'webm', 'm4a', 'ogg', 'wav']:
                                candidate = f"downloads/{base_name}.{ext}"
                                if os.path.exists(candidate):
                                    logger.info(f"SoundCloud success: {candidate}")
                                    return candidate
                            
                            # Если MP3 не найден, но есть другие форматы, конвертируем
                            for ext in ['webm', 'm4a', 'ogg', 'wav']:
                                source_file = f"downloads/{base_name}.{ext}"
                                if os.path.exists(source_file):
                                    # Пробуем конвертировать в MP3
                                    mp3_file = f"downloads/{base_name}.mp3"
                                    try:
                                        import subprocess
                                        result = subprocess.run([
                                            'ffmpeg', '-i', source_file, 
                                            '-acodec', 'mp3', '-ab', '192k',
                                            '-ar', '44100', '-ac', '2',
                                            '-y', mp3_file
                                        ], capture_output=True, timeout=30)
                                        if result.returncode == 0 and os.path.exists(mp3_file):
                                            logger.info(f"SoundCloud converted success: {mp3_file}")
                                            return mp3_file
                                    except Exception:
                                        # Если конвертация не удалась, возвращаем исходный файл
                                        logger.info(f"SoundCloud success (original): {source_file}")
                                        return source_file
                                        
                        except Exception as e:
                            logger.error(f"SoundCloud candidate failed: {e}")
            except Exception:
                logger.exception("SoundCloud provider error")
            
            await asyncio.sleep(0.4)
            
            # 2.5) Пробуем альтернативный провайдер (Last.fm + другие источники)
            try:
                logger.info("Provider: AlternativeMusic")
                async with AlternativeMusicProvider() as alt_provider:
                    path = await alt_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"AlternativeMusic success: {path}")
                        return path
            except Exception as e:
                logger.error(f"AlternativeMusic error: {e}")

            # 2.5A) Пробуем Pleer.net
            try:
                logger.info("Provider: PleerNet")
                async with PleerNetProvider() as pleer_provider:
                    path = await pleer_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"PleerNet success: {path}")
                        return path
            except Exception as e:
                logger.error(f"PleerNet error: {e}")
            
            await asyncio.sleep(0.2)
            # 2.5B) Пробуем MP3Juices
            try:
                logger.info("Provider: MP3Juices")
                async with MP3JuicesProvider() as mp3j_provider:
                    path = await mp3j_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"MP3Juices success: {path}")
                        return path
            except Exception as e:
                logger.error(f"MP3Juices error: {e}")
            
            await asyncio.sleep(0.2)
            # 2.5C) Пробуем Zaycev.net
            try:
                logger.info("Provider: Zaycev.net")
                async with ZaycevProvider() as zaycev_provider:
                    path = await zaycev_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Zaycev.net success: {path}")
                        return path
            except Exception as e:
                logger.error(f"ZaycevProvider error: {e}")
            
            # 2.5D) Пробуем Myzuka.fm
            try:
                logger.info("Provider: Myzuka.fm")
                async with MyzukaProvider() as myzuka_provider:
                    path = await myzuka_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Myzuka.fm success: {path}")
                        return path
            except Exception as e:
                logger.error(f"MyzukaProvider error: {e}")
                # Продолжаем работу, не прерываем выполнение
            # 2.5E) Пробуем rutracker.org (выдаём публичную ссылку, если найден торрент)
            try:
                logger.info("Provider: RuTracker")
                async with RuTrackProvider() as rutr_provider:
                    info_url = await rutr_provider.search_and_download(clean_query)
                    if info_url:
                        logger.info(f"RuTracker info for '{clean_query}': {info_url}")
                        # Для этого типа результата можно отправить текстом ссылку пользователю, либо пробросить в формат ответа
            except Exception as e:
                logger.error(f"RuTrackProvider error: {e}")
            
            # 2.6) Пробуем Bandcamp
            try:
                logger.info("Provider: Bandcamp")
                async with BandcampProvider() as bc_provider:
                    path = await bc_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Bandcamp success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Bandcamp error: {e}")
            
            # 2.7) Пробуем Internet Archive
            try:
                logger.info("Provider: Archive.org")
                async with ArchiveOrgProvider() as arch_provider:
                    path = await arch_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Archive.org success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Archive.org error: {e}")
            
            # 2.8) Пробуем Free Music Archive
            try:
                logger.info("Provider: Free Music Archive")
                async with FreeMusicArchiveProvider() as fma_provider:
                    path = await fma_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Free Music Archive success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Free Music Archive error: {e}")
            
            # 2.9) Пробуем Jamendo
            try:
                logger.info("Provider: Jamendo")
                async with JamendoProvider() as jam_provider:
                    path = await jam_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Jamendo success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Jamendo error: {e}")
            
            # 2.10) Пробуем Mixcloud
            try:
                logger.info("Provider: Mixcloud")
                async with MixcloudProvider() as mix_provider:
                    path = await mix_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mixcloud success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mixcloud error: {e}")
            
            # 2.11) Пробуем VK Music
            try:
                logger.info("Provider: VK Music")
                async with VKMusicProvider() as vk_provider:
                    path = await vk_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"VK Music success: {path}")
                        return path
            except Exception as e:
                logger.error(f"VK Music error: {e}")
            
            # 2.12) Пробуем Яндекс.Музыка
            try:
                logger.info("Provider: Yandex Music")
                async with YandexMusicProvider() as yandex_provider:
                    path = await yandex_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Yandex Music success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Yandex Music error: {e}")
            
            # 2.13) Пробуем Deezer
            try:
                logger.info("Provider: Deezer")
                async with DeezerProvider() as deezer_provider:
                    path = await deezer_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Deezer success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Deezer error: {e}")
            
            # 2.14) Пробуем Audiomack
            try:
                logger.info("Provider: Audiomack")
                async with AudiomackProvider() as audiomack_provider:
                    path = await audiomack_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Audiomack success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Audiomack error: {e}")

            # 2.15) Пробуем Musopen
            try:
                logger.info("Provider: Musopen")
                async with MusopenProvider() as musopen_provider:
                    path = await musopen_provider.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Musopen success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Musopen error: {e}")
            
            # 2.16) Пробуем альтернативный YouTube провайдер
            try:
                logger.info("Provider: AlternativeYouTube")
                alt_yt_provider = AlternativeYouTubeProvider()
                path = await alt_yt_provider.search_and_download(clean_query)
                if path and os.path.exists(path):
                    logger.info(f"AlternativeYouTube success: {path}")
                    return path
            except Exception as e:
                logger.error(f"AlternativeYouTube error: {e}")
            
            # 2.17) Пробуем YouTube Music: ищем песни и качаем лучшего кандидата через yt-dlp
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

            # Настройки для yt-dlp с максимальным обходом блокировок
            import random
            
            # Ротация User-Agent для обхода детекции
            user_agents = [
                'Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1',
                'Mozilla/5.0 (Linux; Android 13; SM-G991B) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Mobile Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:109.0) Gecko/20100101 Firefox/121.0',
                'Mozilla/5.0 (Macintosh; Intel Mac OS X 10.15; rv:109.0) Gecko/20100101 Firefox/121.0'
            ]
            
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
                # Исправления для FFmpeg
                'ffmpeg_location': None,  # Используем системный FFmpeg
                'postprocessor_args': {
                    'FFmpegExtractAudio': [
                        '-acodec', 'mp3',
                        '-ab', '192k',
                        '-ar', '44100',
                        '-ac', '2',
                        '-avoid_negative_ts', 'make_zero',
                        '-fflags', '+genpts',
                        '-strict', '-2',  # Разрешаем экспериментальные кодеки
                        '-max_muxing_queue_size', '1024'  # Увеличиваем буфер
                    ]
                },
                'ignoreerrors': True,  # Игнорируем ошибки постобработки
                'no_check_certificate': True,  # Отключаем проверку сертификатов
                'prefer_ffmpeg': True,
                'noprogress': True,
                'noplaylist': True,
                'quiet': True,
                'no_warnings': True,
                'max_filesize': 50 * 1024 * 1024,  # 50MB лимит
                'windowsfilenames': True,
                # Максимальный обход блокировок YouTube
                'http_headers': {
                    'User-Agent': random.choice(user_agents),
                    'Accept-Language': 'en-US,en;q=0.9,ru;q=0.8',
                    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8',
                    'Accept-Encoding': 'gzip, deflate, br',
                    'DNT': '1',
                    'Connection': 'keep-alive',
                    'Upgrade-Insecure-Requests': '1',
                    'Sec-Fetch-Dest': 'document',
                    'Sec-Fetch-Mode': 'navigate',
                    'Sec-Fetch-Site': 'none',
                },
                'extractor_args': {
                    'youtube': {
                        'player_client': ['ios', 'android_music', 'android', 'web'],
                        'skip': ['dash', 'hls'],
                        'player_skip': ['webpage'],
                        'comment_sort': ['top'],
                        'innertube_host': 'music.youtube.com',
                    }
                },
                'retries': 3,
                'fragment_retries': 3,
                'retry_sleep': 2,
                'sleep_interval': 1,
                'max_sleep_interval': 3,
                # Дополнительные настройки обхода
                'geo_bypass': True,
                'geo_bypass_country': 'US',
                'cookiesfrombrowser': None,  # Отключаем cookies
                'no_check_certificate': True,
                'ignoreerrors': True,
                # Отключаем аутентификацию
                'username': None,
                'password': None,
                'netrc': False,
                # Дополнительные настройки для обхода блокировок
                'extract_flat': False,
                'writethumbnail': False,
                'writeinfojson': False,
                'writesubtitles': False,
                'writeautomaticsub': False,
                # Прокси (если доступны)
                'proxy': None,  # Можно добавить прокси позже
            }
            
            try:
                import yt_dlp
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
                logger.error(f"YouTube search failed: {e}")
                
                # Пробуем альтернативный подход с более простыми настройками
                try:
                    logger.info("Provider: YouTube fallback")
                    simple_ydl_opts = {
                        'format': 'bestaudio/best',
                        'outtmpl': f'downloads/%(title)s.%(ext)s',
                        'postprocessors': [{
                            'key': 'FFmpegExtractAudio',
                            'preferredcodec': 'mp3',
                            'preferredquality': '192',
                        }],
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'ignoreerrors': True,
                        'extract_flat': False,
                        # Исправления для FFmpeg
                        'ffmpeg_location': None,
                        'postprocessor_args': {
                            'FFmpegExtractAudio': [
                                '-acodec', 'mp3',
                                '-ab', '192k',
                                '-ar', '44100',
                                '-ac', '2',
                                '-avoid_negative_ts', 'make_zero',
                                '-fflags', '+genpts',
                                '-strict', '-2',
                                '-max_muxing_queue_size', '1024'
                            ]
                        },
                        'no_check_certificate': True,
                    }
                    
                    with yt_dlp.YoutubeDL(simple_ydl_opts) as ydl:
                        search_results = ydl.extract_info(
                            f"ytsearch3:{clean_query}",
                            download=False
                        )
                        
                        if search_results and 'entries' in search_results:
                            entries = [e for e in search_results.get('entries', []) if e]
                            if entries:
                                best = entries[0]
                                video_url = best.get('webpage_url') or best.get('url')
                                if video_url:
                                    # Скачиваем с простыми настройками
                                    download_opts = simple_ydl_opts.copy()
                                    download_opts['extract_flat'] = False
                                    with yt_dlp.YoutubeDL(download_opts) as ydl_download:
                                        ydl_download.download([video_url])
                                    
                                    title = best.get('title') or 'track'
                                    filename = f"downloads/{clean_filename(title)}.mp3"
                                    if os.path.exists(filename):
                                        logger.info(f"YouTube fallback success: {filename}")
                                        return filename
                except Exception as fallback_error:
                    logger.error(f"YouTube fallback also failed: {fallback_error}")
                    
                    # Последняя попытка - максимально простые настройки
                    try:
                        logger.info("Provider: YouTube ultra-simple")
                        ultra_simple_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                            'no_check_certificate': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ultra_simple_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{clean_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:  # Файл создан в последние 30 секунд
                                            logger.info(f"YouTube ultra-simple success: {file_path}")
                                            return file_path
                    except Exception as ultra_error:
                        logger.error(f"YouTube ultra-simple also failed: {ultra_error}")
                
                # Не прерываем выполнение, продолжаем с другими провайдерами
                return None
            
            # 2.5F) Пробуем RedMp3
            try:
                logger.info("Provider: RedMp3")
                async with RedMp3Provider() as redmp3:
                    path = await redmp3.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"RedMp3 success: {path}")
                        return path
            except Exception as e:
                logger.error(f"RedMp3Provider error: {e}")
            # 2.5G) Пробуем Mp3Skulls
            try:
                logger.info("Provider: Mp3Skulls")
                async with Mp3SkullsProvider() as skulls:
                    path = await skulls.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mp3Skulls success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mp3SkullsProvider error: {e}")
            # 2.5I) Пробуем Mp3Download.to
            try:
                logger.info("Provider: Mp3Download.to")
                async with Mp3DownloadProvider() as mp3dl:
                    path = await mp3dl.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Mp3Download.to success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Mp3DownloadProvider error: {e}")
            # 2.5J) Пробуем Beemp3s.net
            try:
                logger.info("Provider: Beemp3s.net")
                async with Beemp3sProvider() as beemp3s:
                    path = await beemp3s.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"Beemp3s.net success: {path}")
                        return path
            except Exception as e:
                logger.error(f"Beemp3sProvider error: {e}")
            # 2.5K) Пробуем VkMusic.fun
            try:
                logger.info("Provider: VkMusic.fun")
                async with VkMusicFunProvider() as vkmusic:
                    path = await vkmusic.search_and_download(clean_query)
                    if path and os.path.exists(path):
                        logger.info(f"VkMusic.fun success: {path}")
                        return path
            except Exception as e:
                logger.error(f"VkMusicFunProvider error: {e}")

            # 2.6) Пробуем Last.fm
            try:
                logger.info("Provider: Last.fm")
                # Last.fm API для поиска треков
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Получаем API ключ из переменных окружения или используем демо
                    api_key = os.getenv('LASTFM_API_KEY', 'demo')
                    url = f"http://ws.audioscrobbler.com/2.0/?method=track.search&track={clean_query}&api_key={api_key}&format=json"
                    async with session.get(url) as response:
                        if response.status == 200:
                            data = await response.json()
                            tracks = data.get('results', {}).get('trackmatches', {}).get('track', [])
                            if tracks:
                                # Берем первый трек и ищем его на YouTube
                                track = tracks[0]
                                artist = track.get('artist', '')
                                track_name = track.get('name', '')
                                search_query = f"{artist} {track_name}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Last.fm success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Last.fm error: {e}")

            # 2.7) Пробуем Genius
            try:
                logger.info("Provider: Genius")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Genius API для поиска треков
                    access_token = os.getenv('GENIUS_ACCESS_TOKEN', 'demo')
                    headers = {'Authorization': f'Bearer {access_token}'}
                    url = f"https://api.genius.com/search?q={clean_query}"
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            hits = data.get('response', {}).get('hits', [])
                            if hits:
                                # Берем первый хит и ищем на YouTube
                                hit = hits[0]
                                result = hit.get('result', {})
                                artist = result.get('primary_artist', {}).get('name', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Genius success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Genius error: {e}")

            # 2.8) Пробуем MusicBrainz
            try:
                logger.info("Provider: MusicBrainz")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # MusicBrainz API для поиска треков
                    url = f"https://musicbrainz.org/ws/2/recording?query={clean_query}&fmt=json"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            recordings = data.get('recordings', [])
                            if recordings:
                                # Берем первую запись и ищем на YouTube
                                recording = recordings[0]
                                artist = recording.get('artist-credit', [{}])[0].get('name', '')
                                title = recording.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"MusicBrainz success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"MusicBrainz error: {e}")

            # 2.9) Пробуем Discogs
            try:
                logger.info("Provider: Discogs")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Discogs API для поиска треков
                    token = os.getenv('DISCOGS_TOKEN', 'demo')
                    headers = {'Authorization': f'Discogs token={token}'}
                    url = f"https://api.discogs.com/database/search?q={clean_query}&type=release"
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('title', '').split(' - ')[0] if ' - ' in result.get('title', '') else ''
                                title = result.get('title', '').split(' - ')[1] if ' - ' in result.get('title', '') else result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Discogs success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Discogs error: {e}")

            # 2.10) Пробуем Rate Your Music
            try:
                logger.info("Provider: Rate Your Music")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # RYM API для поиска треков
                    url = f"https://rateyourmusic.com/api/search?q={clean_query}&type=album"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Rate Your Music success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Rate Your Music error: {e}")

            # 2.11) Пробуем AllMusic
            try:
                logger.info("Provider: AllMusic")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # AllMusic API для поиска треков
                    url = f"https://www.allmusic.com/search/all/{clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            # Парсим HTML для поиска треков
                            html = await response.text()
                            # Простой поиск по HTML (можно улучшить с помощью BeautifulSoup)
                            if 'track' in html.lower() or 'song' in html.lower():
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{clean_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"AllMusic success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"AllMusic error: {e}")

            # 2.12) Пробуем Pitchfork
            try:
                logger.info("Provider: Pitchfork")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Pitchfork API для поиска треков
                    url = f"https://pitchfork.com/api/v2/search/?query={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Pitchfork success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Pitchfork error: {e}")

            # 2.13) Пробуем NME
            try:
                logger.info("Provider: NME")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # NME API для поиска треков
                    url = f"https://www.nme.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"NME success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"NME error: {e}")

            # 2.14) Пробуем Rolling Stone
            try:
                logger.info("Provider: Rolling Stone")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Rolling Stone API для поиска треков
                    url = f"https://www.rollingstone.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Rolling Stone success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Rolling Stone error: {e}")

            # 2.15) Пробуем Billboard
            try:
                logger.info("Provider: Billboard")
                import aiohttp
                async with aiohttp.ClientSession() as session:
                    # Billboard API для поиска треков
                    url = f"https://www.billboard.com/api/search?q={clean_query}"
                    headers = {'User-Agent': 'SpotifyBot/1.0 (https://example.com)'}
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            data = await response.json()
                            results = data.get('results', [])
                            if results:
                                # Берем первый результат и ищем на YouTube
                                result = results[0]
                                artist = result.get('artist', '')
                                title = result.get('title', '')
                                search_query = f"{artist} {title}"
                                
                                # Ищем на YouTube
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'prefer_ffmpeg': True,
                                    'noprogress': True,
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'windowsfilenames': True,
                                }
                                import yt_dlp
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(f"ytsearch1:{search_query}", download=False)
                                    if search_results and 'entries' in search_results and search_results['entries']:
                                        video_url = search_results['entries'][0].get('webpage_url')
                                        if video_url:
                                            ydl.download([video_url])
                                            title = search_results['entries'][0].get('title', 'track')
                                            filename = f"downloads/{clean_filename(title)}.mp3"
                                            if os.path.exists(filename):
                                                logger.info(f"Billboard success: {filename}")
                                                return filename
            except Exception as e:
                logger.error(f"Billboard error: {e}")

            # 2.16) Пробуем дополнительные варианты поиска на YouTube
            try:
                logger.info("Provider: YouTube Variants")
                # Пробуем разные варианты поискового запроса
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' - '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' - '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' '),
                    # Дополнительные варианты для сложных названий
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip(),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' music',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' song',
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', '').replace('  ', ' ').strip() + ' audio',
                    # Пробуем только первую часть названия
                    clean_query.split('_')[0] if '_' in clean_query else clean_query,
                    # Пробуем только вторую часть названия
                    clean_query.split('_')[1] if '_' in clean_query and len(clean_query.split('_')) > 1 else clean_query,
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                            # Более агрессивные настройки для обхода блокировок
                            'extractor_args': {
                                'youtube': {
                                    'player_client': ['android', 'web'],
                                    'innertube_host': 'music.youtube.com',
                                    'api_key': 'AIzaSyAO_FJ2SlqU8Q4STEHLGCilw_Y9_11qcW8',
                                    'client_version': '17.31.35',
                                }
                            },
                            'http_headers': {
                                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
                            },
                            'retries': 3,
                            'sleep_interval': 1,
                            'max_sleep_interval': 5,
                            'username': None,
                            'password': None,
                            'netrc': False,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"ytsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуем скачать первое видео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"YouTube Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"YouTube Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"YouTube Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"YouTube Variants error: {e}")

            # 2.17) Пробуем SoundCloud с разными вариантами
            try:
                logger.info("Provider: SoundCloud Variants")
                # Пробуем разные варианты поискового запроса на SoundCloud
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"scsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуем скачать первое видео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"SoundCloud Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"SoundCloud Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"SoundCloud Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"SoundCloud Variants error: {e}")

            # 2.18) Пробуем Bandcamp с разными вариантами
            try:
                logger.info("Provider: Bandcamp Variants")
                # Пробуем разные варианты поискового запроса на Bandcamp
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"bandcampsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуем скачать первое видео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Bandcamp Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Bandcamp Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Bandcamp Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Bandcamp Variants error: {e}")

            # 2.19) Пробуем Mixcloud с разными вариантами
            try:
                logger.info("Provider: Mixcloud Variants")
                # Пробуем разные варианты поискового запроса на Mixcloud
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"mixcloudsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуем скачать первое видео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Mixcloud Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Mixcloud Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Mixcloud Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Mixcloud Variants error: {e}")

            # 2.20) Пробуем Archive.org с разными вариантами
            try:
                logger.info("Provider: Archive.org Variants")
                # Пробуем разные варианты поискового запроса на Archive.org
                search_variants = [
                    clean_query,
                    clean_query.replace('_', ' '),
                    clean_query.replace('_', ' ').replace(',', ' '),
                    clean_query.replace('_', ' ').replace(',', ' ').replace('!', ''),
                ]
                
                for variant in search_variants:
                    if not variant.strip():
                        continue
                        
                    try:
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'prefer_ffmpeg': True,
                            'noprogress': True,
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'windowsfilenames': True,
                        }
                        import yt_dlp
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(f"archiveorgsearch3:{variant}", download=False)
                            if search_results and 'entries' in search_results and search_results['entries']:
                                # Пробуем скачать первое видео
                                video_url = search_results['entries'][0].get('webpage_url')
                                if video_url:
                                    try:
                                        ydl.download([video_url])
                                        title = search_results['entries'][0].get('title', 'track')
                                        filename = f"downloads/{clean_filename(title)}.mp3"
                                        if os.path.exists(filename):
                                            logger.info(f"Archive.org Variants success: {filename}")
                                            return filename
                                    except Exception as e:
                                        logger.warning(f"Archive.org Variants failed for '{variant}': {e}")
                                        continue
                    except Exception as e:
                        logger.warning(f"Archive.org Variants error for '{variant}': {e}")
                        continue
            except Exception as e:
                logger.error(f"Archive.org Variants error: {e}")

        except Exception as e:
            logger.exception("Downloader fatal error")
            return None
        
        # Дополнительные провайдеры для увеличения шансов нахождения трека
        
        # 3.1) Пробуем Last.fm + YouTube
        try:
            logger.info("Provider: Last.fm + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Last.fm
                lastfm_url = f"http://ws.audioscrobbler.com/2.0/?method=track.search&track={quote(clean_query)}&api_key=YOUR_API_KEY&format=json"
                async with session.get(lastfm_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and 'trackmatches' in data['results']:
                            tracks = data['results']['trackmatches']['track']
                            if tracks:
                                # Берем первый трек
                                track = tracks[0] if isinstance(tracks, list) else tracks
                                artist = track.get('artist', '')
                                track_name = track.get('name', '')
                                
                                # Ищем на YouTube
                                youtube_query = f"{artist} {track_name}"
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'ignoreerrors': True,
                                }
                                
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(
                                        f"ytsearch1:{youtube_query}",
                                        download=True
                                    )
                                    
                                    if search_results:
                                        # Ищем скачанный файл
                                        import glob
                                        import time
                                        await asyncio.sleep(2)
                                        
                                        for file_path in glob.glob("downloads/*"):
                                            if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                                file_age = time.time() - os.path.getctime(file_path)
                                                if file_age < 30:
                                                    logger.info(f"Last.fm + YouTube success: {file_path}")
                                                    return file_path
        except Exception as e:
            logger.error(f"Last.fm + YouTube failed: {e}")
        
        # 3.2) Пробуем Genius + YouTube
        try:
            logger.info("Provider: Genius + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Genius
                genius_url = f"https://api.genius.com/search?q={quote(clean_query)}"
                headers = {'Authorization': 'Bearer YOUR_ACCESS_TOKEN'}
                async with session.get(genius_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'response' in data and 'hits' in data['response']:
                            hits = data['response']['hits']
                            if hits:
                                # Берем первый хит
                                hit = hits[0]['result']
                                artist = hit.get('primary_artist', {}).get('name', '')
                                title = hit.get('title', '')
                                
                                # Ищем на YouTube
                                youtube_query = f"{artist} {title}"
                                ydl_opts = {
                                    'format': 'bestaudio/best',
                                    'outtmpl': f'downloads/%(title)s.%(ext)s',
                                    'postprocessors': [{
                                        'key': 'FFmpegExtractAudio',
                                        'preferredcodec': 'mp3',
                                        'preferredquality': '192',
                                    }],
                                    'noplaylist': True,
                                    'quiet': True,
                                    'no_warnings': True,
                                    'ignoreerrors': True,
                                }
                                
                                with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                    search_results = ydl.extract_info(
                                        f"ytsearch1:{youtube_query}",
                                        download=True
                                    )
                                    
                                    if search_results:
                                        # Ищем скачанный файл
                                        import glob
                                        import time
                                        await asyncio.sleep(2)
                                        
                                        for file_path in glob.glob("downloads/*"):
                                            if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                                file_age = time.time() - os.path.getctime(file_path)
                                                if file_age < 30:
                                                    logger.info(f"Genius + YouTube success: {file_path}")
                                                    return file_path
        except Exception as e:
            logger.error(f"Genius + YouTube failed: {e}")
        
        # 3.3) Пробуем MusicBrainz + YouTube
        try:
            logger.info("Provider: MusicBrainz + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на MusicBrainz
                musicbrainz_url = f"https://musicbrainz.org/ws/2/recording?query={quote(clean_query)}&fmt=json"
                async with session.get(musicbrainz_url) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'recordings' in data and data['recordings']:
                            recording = data['recordings'][0]
                            title = recording.get('title', '')
                            artist = ''
                            if 'artist-credit' in recording:
                                artist_credit = recording['artist-credit'][0]
                                if 'name' in artist_credit:
                                    artist = artist_credit['name']
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
                            ydl_opts = {
                                'format': 'bestaudio/best',
                                'outtmpl': f'downloads/%(title)s.%(ext)s',
                                'postprocessors': [{
                                    'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3',
                                    'preferredquality': '192',
                                }],
                                'noplaylist': True,
                                'quiet': True,
                                'no_warnings': True,
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"MusicBrainz + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"MusicBrainz + YouTube failed: {e}")
        
        # 3.4) Пробуем Discogs + YouTube
        try:
            logger.info("Provider: Discogs + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Discogs
                discogs_url = f"https://api.discogs.com/database/search?q={quote(clean_query)}&type=release"
                headers = {'User-Agent': 'SpotifyBot/1.0'}
                async with session.get(discogs_url, headers=headers) as response:
                    if response.status == 200:
                        data = await response.json()
                        if 'results' in data and data['results']:
                            result = data['results'][0]
                            title = result.get('title', '')
                            artist = result.get('artist', '')
                            
                            # Ищем на YouTube
                            youtube_query = f"{artist} {title}"
                            ydl_opts = {
                                'format': 'bestaudio/best',
                                'outtmpl': f'downloads/%(title)s.%(ext)s',
                                'postprocessors': [{
                                    'key': 'FFmpegExtractAudio',
                                    'preferredcodec': 'mp3',
                                    'preferredquality': '192',
                                }],
                                'noplaylist': True,
                                'quiet': True,
                                'no_warnings': True,
                                'ignoreerrors': True,
                            }
                            
                            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                                search_results = ydl.extract_info(
                                    f"ytsearch1:{youtube_query}",
                                    download=True
                                )
                                
                                if search_results:
                                    # Ищем скачанный файл
                                    import glob
                                    import time
                                    await asyncio.sleep(2)
                                    
                                    for file_path in glob.glob("downloads/*"):
                                        if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                            file_age = time.time() - os.path.getctime(file_path)
                                            if file_age < 30:
                                                logger.info(f"Discogs + YouTube success: {file_path}")
                                                return file_path
        except Exception as e:
            logger.error(f"Discogs + YouTube failed: {e}")
        
        # 3.5) Пробуем Rate Your Music + YouTube
        try:
            logger.info("Provider: Rate Your Music + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Rate Your Music
                rym_url = f"https://rateyourmusic.com/search?searchterm={quote(clean_query)}&searchtype=l"
                async with session.get(rym_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Rate Your Music + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Rate Your Music + YouTube failed: {e}")
        
        # 3.6) Пробуем AllMusic + YouTube
        try:
            logger.info("Provider: AllMusic + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на AllMusic
                allmusic_url = f"https://www.allmusic.com/search/all/{quote(clean_query)}"
                async with session.get(allmusic_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"AllMusic + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"AllMusic + YouTube failed: {e}")
        
        # 3.7) Пробуем Pitchfork + YouTube
        try:
            logger.info("Provider: Pitchfork + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Pitchfork
                pitchfork_url = f"https://pitchfork.com/search/?query={quote(clean_query)}"
                async with session.get(pitchfork_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Pitchfork + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Pitchfork + YouTube failed: {e}")
        
        # 3.8) Пробуем NME + YouTube
        try:
            logger.info("Provider: NME + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на NME
                nme_url = f"https://www.nme.com/search?q={quote(clean_query)}"
                async with session.get(nme_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"NME + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"NME + YouTube failed: {e}")
        
        # 3.9) Пробуем Rolling Stone + YouTube
        try:
            logger.info("Provider: Rolling Stone + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Rolling Stone
                rollingstone_url = f"https://www.rollingstone.com/search/?q={quote(clean_query)}"
                async with session.get(rollingstone_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Rolling Stone + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Rolling Stone + YouTube failed: {e}")
        
        # 3.10) Пробуем Billboard + YouTube
        try:
            logger.info("Provider: Billboard + YouTube")
            import aiohttp
            async with aiohttp.ClientSession() as session:
                # Ищем трек на Billboard
                billboard_url = f"https://www.billboard.com/search?q={quote(clean_query)}"
                async with session.get(billboard_url) as response:
                    if response.status == 200:
                        # Парсим HTML (упрощенная версия)
                        html = await response.text()
                        # Здесь можно добавить парсинг HTML для извлечения названия и исполнителя
                        # Пока используем оригинальный запрос
                        youtube_query = clean_query
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                            'noplaylist': True,
                            'quiet': True,
                            'no_warnings': True,
                            'ignoreerrors': True,
                        }
                        
                        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                            search_results = ydl.extract_info(
                                f"ytsearch1:{youtube_query}",
                                download=True
                            )
                            
                            if search_results:
                                # Ищем скачанный файл
                                import glob
                                import time
                                await asyncio.sleep(2)
                                
                                for file_path in glob.glob("downloads/*"):
                                    if file_path.lower().endswith(('.mp3', '.webm', '.m4a', '.ogg', '.wav', '.aac')):
                                        file_age = time.time() - os.path.getctime(file_path)
                                        if file_age < 30:
                                            logger.info(f"Billboard + YouTube success: {file_path}")
                                            return file_path
        except Exception as e:
            logger.error(f"Billboard + YouTube failed: {e}")
        
        # Если ничего не найдено
        logger.info("All providers failed to find the track")
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


@dp.message(Command("status"))
async def status_command(message: Message):
    """Показывает статус бота и активных загрузок"""
    global active_downloads
    
    status_text = (
        f"🤖 **Статус бота**\n\n"
        f"🔄 Активных загрузок: {active_downloads}/3\n"
        f"🎵 FFmpeg доступен: {'✅' if is_ffmpeg_available() else '❌'}\n"
        f"🎧 Spotify API: {'✅' if spotify_client_id and spotify_client_secret else '❌'}\n"
        f"🌐 Провайдеров: 25+\n\n"
        f"💡 **Возможности:**\n"
        f"• Поиск по Spotify ссылкам\n"
        f"• Поиск по названию трека\n"
        f"• Фильтрация оригинальных версий\n"
        f"• Параллельная обработка запросов\n"
        f"• 25+ источников музыки"
    )
    
    await message.answer(status_text, parse_mode="Markdown")


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
    
    # Отправляем сообщение о начале обработки
    processing_msg = await message.answer("🔄 Обрабатываю ссылку...")
    
    try:
        # Извлекаем ID из ссылки (теперь асинхронно)
        ids = await spotify_parser.extract_ids_from_url(text)
        
        if not any(ids.values()):
            await processing_msg.edit_text("❌ Пожалуйста, отправьте ссылку на трек или плейлист Spotify.")
            return
        
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
    global active_downloads
    
    # Проверяем, не превышен ли лимит одновременных загрузок
    if active_downloads >= 3:
        await processing_msg.edit_text("⏳ Слишком много запросов одновременно. Попробуйте через минуту.")
        return
    
    # Увеличиваем счетчик активных загрузок
    active_downloads += 1
    
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
            f"🔄 Ищу и скачиваю... (активных загрузок: {active_downloads})"
        )
        
        # Формируем поисковый запрос
        search_query = spotify_parser.create_search_query(track_info)
        
        # Используем семафор для ограничения одновременных загрузок
        async with download_semaphore:
            file_path = await MusicDownloader.search_and_download(search_query, track_info)
        
        # Добавляем подробное логирование для отладки
        logger.info(f"Download result: file_path={file_path}")
        if file_path:
            logger.info(f"File exists: {os.path.exists(file_path)}")
            if os.path.exists(file_path):
                logger.info(f"File size: {os.path.getsize(file_path)} bytes")
        
        if file_path and os.path.exists(file_path):
            # Получаем размер файла
            file_size = os.path.getsize(file_path)
            logger.info(f"Sending file: {file_path} (size: {file_size} bytes)")
            
            # Проверяем формат файла и конвертируем если нужно
            file_extension = os.path.splitext(file_path)[1].lower()
            logger.info(f"File extension: {file_extension}")
            
            if file_extension not in ['.mp3', '.m4a', '.aac', '.ogg', '.wav']:
                logger.error(f"Unsupported file format: {file_extension}")
                await processing_msg.edit_text("❌ Неподдерживаемый формат файла.")
                os.remove(file_path)
                return
            
            # Если файл не в формате MP3, конвертируем его
            if file_extension != '.mp3':
                try:
                    logger.info(f"Converting {file_extension} to MP3...")
                    import subprocess
                    import tempfile
                    
                    # Создаем временный файл для конвертации
                    mp3_path = file_path.replace(file_extension, '.mp3')
                    
                    # Используем FFmpeg напрямую для конвертации
                    ffmpeg_cmd = [
                        'ffmpeg',
                        '-i', file_path,
                        '-acodec', 'mp3',
                        '-ab', '192k',
                        '-ar', '44100',
                        '-ac', '2',
                        '-y',  # Перезаписываем файл если существует
                        mp3_path
                    ]
                    
                    result = subprocess.run(ffmpeg_cmd, capture_output=True, text=True, timeout=60)
                    
                    if result.returncode == 0 and os.path.exists(mp3_path):
                        # Удаляем оригинальный файл
                        os.remove(file_path)
                        file_path = mp3_path
                        logger.info(f"Successfully converted to MP3: {file_path}")
                    else:
                        logger.error(f"FFmpeg conversion failed: {result.stderr}")
                        # Пробуем yt-dlp как fallback
                        import yt_dlp
                        ydl_opts = {
                            'format': 'bestaudio/best',
                            'outtmpl': f'downloads/%(title)s.%(ext)s',
                            'postprocessors': [{
                                'key': 'FFmpegExtractAudio',
                                'preferredcodec': 'mp3',
                                'preferredquality': '192',
                            }],
                        'prefer_ffmpeg': True,
                        'noprogress': True,
                        'noplaylist': True,
                        'quiet': True,
                        'no_warnings': True,
                        'windowsfilenames': True,
                    }
                    
                    # Конвертируем файл
                    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                        ydl.download([file_path])
                    
                    # Удаляем оригинальный файл
                    os.remove(file_path)
                    
                    # Ищем новый MP3 файл
                    mp3_file = file_path.replace(file_extension, '.mp3')
                    if os.path.exists(mp3_file):
                        file_path = mp3_file
                        file_size = os.path.getsize(file_path)
                        logger.info(f"Converted to MP3: {file_path} ({file_size} bytes)")
                    else:
                        logger.error("Failed to convert to MP3")
                        await processing_msg.edit_text("❌ Не удалось конвертировать файл в MP3.")
                        return
                        
                except Exception as e:
                    logger.error(f"Conversion error: {e}")
                    await processing_msg.edit_text("❌ Ошибка конвертации файла.")
                    os.remove(file_path)
                    return
            
            try:
                # Создаем красивое название файла только с названием трека
                clean_track_name = clean_filename(track_info['name'])
                
                # Отправляем файл с кастомным именем
            await message.answer_document(
                    document=types.FSInputFile(file_path, filename=f"{clean_track_name}.mp3"),
                caption=f"🎵 {track_info['name']} - {track_info['artist']}\n"
                       f"⏱️ {track_info['duration_formatted']} | 📁 {format_file_size(file_size)}"
            )
            
            # Удаляем временный файл
            os.remove(file_path)
                logger.info(f"File sent successfully and removed: {file_path}")
            
            await processing_msg.delete()
            except Exception as send_error:
                logger.error(f"Error sending file: {send_error}")
                await processing_msg.edit_text(f"❌ Ошибка отправки файла: {send_error}")
        else:
            logger.error(f"File not found or invalid path: {file_path}")
            await processing_msg.edit_text("❌ Не удалось найти или скачать трек.")
            
    except Exception as e:
        logger.error(f"Error processing track: {e}")
        await processing_msg.edit_text("❌ Произошла ошибка при обработке трека.")
    finally:
        # Уменьшаем счетчик активных загрузок
        active_downloads -= 1


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
    port = int(os.getenv('PORT', 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logger.info(f"HTTP server started on port {port}")
    
    try:
        # Запускаем Telegram бота с обработкой конфликтов
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Bot startup error: {e}")
        # Если ошибка связана с конфликтом, ждем и перезапускаем
        if "Conflict" in str(e) or "terminated by other getUpdates" in str(e):
            logger.info("Detected Telegram conflict, waiting 10 seconds before retry...")
            await asyncio.sleep(10)
            try:
                await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
            except Exception as retry_error:
                logger.error(f"Retry failed: {retry_error}")
                raise
        else:
        raise


if __name__ == "__main__":
    asyncio.run(main())
