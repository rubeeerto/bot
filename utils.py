import os
import re
import asyncio
from typing import List, Optional, Dict
import aiohttp
import spotipy
from spotipy.oauth2 import SpotifyClientCredentials
import os
from typing import Tuple

async def _download_file(session: aiohttp.ClientSession, url: str, dest_path: str) -> Optional[str]:
    """Скачивает файл по URL в указанный путь"""
    try:
        os.makedirs(os.path.dirname(dest_path), exist_ok=True)
        async with session.get(url) as resp:
            if resp.status != 200:
                return None
            with open(dest_path, 'wb') as f:
                while True:
                    chunk = await resp.content.read(8192)
                    if not chunk:
                        break
                    f.write(chunk)
        return dest_path
    except Exception:
        return None


class EnhancedSpotifyParser:
    """Улучшенный парсер Spotify с дополнительными функциями"""
    
    def __init__(self, client_id: str = None, client_secret: str = None):
        self.client_id = client_id
        self.client_secret = client_secret
        self.sp = None
        
        if client_id and client_secret:
            try:
                client_credentials_manager = SpotifyClientCredentials(
                    client_id=client_id,
                    client_secret=client_secret
                )
                self.sp = spotipy.Spotify(client_credentials_manager=client_credentials_manager)
            except Exception as e:
                print(f"Error initializing Spotify client: {e}")
    
    def extract_ids_from_url(self, url: str) -> Dict[str, Optional[str]]:
        """Извлекает все возможные ID из ссылки Spotify"""
        patterns = {
            'track': [
                r'spotify:track:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/track/([a-zA-Z0-9]+)',
                r'https://spotify\.com/track/([a-zA-Z0-9]+)'
            ],
            'playlist': [
                r'spotify:playlist:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/playlist/([a-zA-Z0-9]+)',
                r'https://spotify\.com/playlist/([a-zA-Z0-9]+)'
            ],
            'album': [
                r'spotify:album:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/album/([a-zA-Z0-9]+)',
                r'https://spotify\.com/album/([a-zA-Z0-9]+)'
            ],
            'artist': [
                r'spotify:artist:([a-zA-Z0-9]+)',
                r'https://open\.spotify\.com/artist/([a-zA-Z0-9]+)',
                r'https://spotify\.com/artist/([a-zA-Z0-9]+)'
            ]
        }
        
        result = {}
        for content_type, pattern_list in patterns.items():
            result[content_type] = None
            for pattern in pattern_list:
                match = re.search(pattern, url)
                if match:
                    result[content_type] = match.group(1)
                    break
        
        return result
    
    async def get_track_info(self, track_id: str) -> Optional[Dict]:
        """Получает подробную информацию о треке"""
        if not self.sp:
            return None
            
        try:
            track = self.sp.track(track_id)
            return {
                'id': track['id'],
                'name': track['name'],
                'artist': ', '.join([artist['name'] for artist in track['artists']]),
                'artists': [artist['name'] for artist in track['artists']],
                'album': track['album']['name'],
                'album_artists': [artist['name'] for artist in track['album']['artists']],
                'duration': track['duration_ms'] // 1000,
                'duration_formatted': self._format_duration(track['duration_ms']),
                'url': track['external_urls']['spotify'],
                'preview_url': track['preview_url'],
                'popularity': track['popularity'],
                'explicit': track['explicit'],
                'release_date': track['album']['release_date'],
                'genres': track['album'].get('genres', [])
            }
        except Exception as e:
            print(f"Error getting track info: {e}")
            return None
    
    async def get_playlist_info(self, playlist_id: str) -> Optional[Dict]:
        """Получает информацию о плейлисте"""
        if not self.sp:
            return None
            
        try:
            playlist = self.sp.playlist(playlist_id)
            tracks = []
            
            # Получаем все треки из плейлиста
            results = self.sp.playlist_tracks(playlist_id)
            tracks.extend(results['items'])
            
            # Если есть следующая страница, загружаем её
            while results['next']:
                results = self.sp.next(results)
                tracks.extend(results['items'])
            
            track_list = []
            for item in tracks:
                track = item['track']
                if track and track['type'] == 'track':
                    track_list.append({
                        'id': track['id'],
                        'name': track['name'],
                        'artist': ', '.join([artist['name'] for artist in track['artists']]),
                        'artists': [artist['name'] for artist in track['artists']],
                        'album': track['album']['name'],
                        'duration': track['duration_ms'] // 1000,
                        'duration_formatted': self._format_duration(track['duration_ms']),
                        'url': track['external_urls']['spotify'],
                        'popularity': track['popularity']
                    })
            
            return {
                'id': playlist['id'],
                'name': playlist['name'],
                'description': playlist['description'],
                'owner': playlist['owner']['display_name'],
                'tracks_count': playlist['tracks']['total'],
                'url': playlist['external_urls']['spotify'],
                'tracks': track_list
            }
        except Exception as e:
            print(f"Error getting playlist info: {e}")
            return None
    
    async def get_album_info(self, album_id: str) -> Optional[Dict]:
        """Получает информацию об альбоме"""
        if not self.sp:
            return None
            
        try:
            album = self.sp.album(album_id)
            tracks = []
            
            for track in album['tracks']['items']:
                tracks.append({
                    'id': track['id'],
                    'name': track['name'],
                    'artist': ', '.join([artist['name'] for artist in track['artists']]),
                    'artists': [artist['name'] for artist in track['artists']],
                    'duration': track['duration_ms'] // 1000,
                    'duration_formatted': self._format_duration(track['duration_ms']),
                    'url': f"https://open.spotify.com/track/{track['id']}"
                })
            
            return {
                'id': album['id'],
                'name': album['name'],
                'artist': ', '.join([artist['name'] for artist in album['artists']]),
                'artists': [artist['name'] for artist in album['artists']],
                'release_date': album['release_date'],
                'total_tracks': album['total_tracks'],
                'url': album['external_urls']['spotify'],
                'tracks': tracks
            }
        except Exception as e:
            print(f"Error getting album info: {e}")
            return None
    
    def _format_duration(self, duration_ms: int) -> str:
        """Форматирует длительность в читаемый вид"""
        seconds = duration_ms // 1000
        minutes = seconds // 60
        seconds = seconds % 60
        return f"{minutes}:{seconds:02d}"
    
    def create_search_query(self, track_info: Dict) -> str:
        """Создает поисковый запрос для поиска музыки"""
        # Пробуем разные варианты поискового запроса
        queries = [
            f"{track_info['name']} {track_info['artist']}",
            f"{track_info['name']} {track_info['artists'][0]}",
            f"{track_info['name']} {track_info['album']}",
            f"{track_info['name']} {track_info['artist']} lyrics",
            f"{track_info['name']} {track_info['artist']} official"
        ]
        return queries[0]  # Возвращаем основной запрос


class MusicSearchEngine:
    """Класс для поиска музыки в различных источниках"""
    
    def __init__(self):
        self.session = None
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def search_youtube(self, query: str, max_results: int = 5) -> List[Dict]:
        """Ищет видео на YouTube"""
        try:
            # Здесь можно добавить интеграцию с YouTube API
            # Пока используем yt-dlp для поиска
            import yt_dlp
            
            ydl_opts = {
                'quiet': True,
                'no_warnings': True,
                'extract_flat': True,
            }
            
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                search_results = ydl.extract_info(
                    f"ytsearch{max_results}:{query}",
                    download=False
                )
                
                if not search_results or 'entries' not in search_results:
                    return []
                
                results = []
                for entry in search_results['entries']:
                    if entry:
                        results.append({
                            'title': entry.get('title', ''),
                            'url': entry.get('url', ''),
                            'duration': entry.get('duration', 0),
                            'view_count': entry.get('view_count', 0)
                        })
                
                return results
                
        except Exception as e:
            print(f"Error searching YouTube: {e}")
            return []
    
    async def search_soundcloud(self, query: str) -> List[Dict]:
        """Ищет треки на SoundCloud"""
        # Здесь можно добавить интеграцию с SoundCloud API
        return []
    
    async def get_best_match(self, track_info: Dict, search_results: List[Dict]) -> Optional[Dict]:
        """Выбирает лучший результат поиска"""
        if not search_results:
            return None
        
        # Простая логика выбора лучшего результата
        # Можно улучшить, добавив сравнение названий и исполнителей
        best_match = search_results[0]
        
        # Проверяем длительность (если доступна)
        if track_info.get('duration') and best_match.get('duration'):
            duration_diff = abs(track_info['duration'] - best_match['duration'])
            if duration_diff > 30:  # Если разница больше 30 секунд
                # Ищем более подходящий по длительности
                for result in search_results[1:]:
                    if result.get('duration'):
                        new_diff = abs(track_info['duration'] - result['duration'])
                        if new_diff < duration_diff:
                            best_match = result
                            duration_diff = new_diff
        
        return best_match


def clean_filename(filename: str) -> str:
    """Очищает имя файла от недопустимых символов"""
    # Удаляем недопустимые символы для Windows
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        filename = filename.replace(char, '_')
    
    # Ограничиваем длину имени файла
    if len(filename) > 200:
        filename = filename[:200]
    
    return filename.strip()


def format_file_size(size_bytes: int) -> str:
    """Форматирует размер файла в читаемый вид"""
    if size_bytes == 0:
        return "0 B"
    
    size_names = ["B", "KB", "MB", "GB"]
    i = 0
    while size_bytes >= 1024 and i < len(size_names) - 1:
        size_bytes /= 1024.0
        i += 1
    
    return f"{size_bytes:.1f} {size_names[i]}"


class JioSaavnProvider:
    """Онлайн-провайдер: поиск и скачивание MP3 через неофициальное API JioSaavn"""

    BASE = "https://saavn.me"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search(self, query: str, limit: int = 5) -> List[Dict]:
        """Ищет треки в JioSaavn по запросу"""
        try:
            assert self.session is not None
            params = {"query": query}
            async with self.session.get(f"{self.BASE}/search/songs", params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                data = await resp.json()
                results = data.get("data", []) or []
                songs = results[:limit]
                parsed: List[Dict] = []
                for s in songs:
                    parsed.append({
                        "id": s.get("id"),
                        "title": s.get("name") or s.get("title"),
                        "primaryArtists": s.get("primaryArtists", ""),
                        "image": s.get("image"),
                        "album": s.get("album"),
                        "duration": int(s.get("duration", 0)) if s.get("duration") else 0
                    })
                return parsed
        except Exception:
            return []

    async def get_song(self, song_id: str) -> Optional[Dict]:
        try:
            assert self.session is not None
            params = {"id": song_id}
            async with self.session.get(f"{self.BASE}/songs", params=params, timeout=30) as resp:
                if resp.status != 200:
                    return None
                data = await resp.json()
                songs = data.get("data", []) or []
                return songs[0] if songs else None
        except Exception:
            return None


class SoundCloudProvider:
    """Онлайн-провайдер: поиск треков на SoundCloud (через HTML) и скачивание через yt-dlp"""

    SEARCH_URL = "https://soundcloud.com/search/sounds"

    def __init__(self):
        self.session: Optional[aiohttp.ClientSession] = None

    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers={
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
        })
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()

    async def search_urls(self, query: str, limit: int = 3) -> List[str]:
        try:
            assert self.session is not None
            params = {"q": query}
            async with self.session.get(self.SEARCH_URL, params=params, timeout=30) as resp:
                if resp.status != 200:
                    return []
                html = await resp.text()
            # Простейший парсинг ссылок на треки вида href="/artist/track"
            import re as _re
            candidates = []
            for m in _re.finditer(r'href="(/[^"\s]+/[^"\s]+)"', html):
                path = m.group(1)
                # отбрасываем плейлисты и всякое
                if "/sets/" in path or path.startswith("/search"):
                    continue
                if path.count('/') >= 2:  # обычно /artist/track
                    url = f"https://soundcloud.com{path}"
                    if url not in candidates:
                        candidates.append(url)
                if len(candidates) >= limit:
                    break
            return candidates
        except Exception:
            return []


class YTMusicProvider:
    """Провайдер поиска в YouTube Music через ytmusicapi (без ключа)"""

    def __init__(self):
        from ytmusicapi import YTMusic
        # Анонимная инициализация (без cookies) — для поиска хватает
        self.yt = YTMusic()

    def search(self, query: str, limit: int = 5) -> List[Dict]:
        try:
            results = self.yt.search(query, filter="songs", limit=limit) or []
            parsed: List[Dict] = []
            for r in results:
                title = r.get("title")
                artists = ", ".join([a.get("name") for a in (r.get("artists") or []) if a.get("name")])
                dur = r.get("duration")  # формат mm:ss
                seconds = 0
                if isinstance(dur, str) and ":" in dur:
                    try:
                        m, s = dur.split(":")
                        seconds = int(m) * 60 + int(s)
                    except Exception:
                        seconds = 0
                video_id = r.get("videoId")
                if video_id:
                    parsed.append({
                        "title": title,
                        "artist": artists,
                        "duration": seconds,
                        "url": f"https://music.youtube.com/watch?v={video_id}",
                    })
            return parsed
        except Exception:
            return []

    async def download_best(self, query: str) -> Optional[str]:
        """Ищет трек и скачивает лучшую доступную версию MP3. Возвращает путь к файлу."""
        try:
            results = await self.search(query, limit=5)
            if not results:
                return None
            # Берем первый кандидат (можно улучшить по совпадению артиста/длительности)
            candidate = results[0]
            song = await self.get_song(candidate["id"]) if candidate.get("id") else None
            if not song:
                return None
            # Ищем ссылку на 320/160/96 kbps
            media_urls = []
            for key in ("downloadUrl", "moreInfo"):
                if isinstance(song.get(key), list):
                    media_urls.extend(song.get(key) or [])
                elif isinstance(song.get(key), dict):
                    # иногда аудиоссылки в moreInfo.download_links и т.п.
                    dl = song[key].get("download_links") if song[key] else None
                    if isinstance(dl, list):
                        media_urls.extend(dl)
            # Плоский список url-строк
            urls: List[str] = []
            for item in media_urls:
                if isinstance(item, dict):
                    u = item.get("link") or item.get("url")
                    if u:
                        urls.append(u)
                elif isinstance(item, str):
                    urls.append(item)
            # Фильтруем mp3 ссылки, предпочитая 320
            preferred = [u for u in urls if "320" in u]
            if not preferred:
                preferred = [u for u in urls if u.endswith(".mp3")]
            dl_url = preferred[0] if preferred else (urls[0] if urls else None)
            if not dl_url:
                return None
            safe_name = clean_filename(f"{candidate['title']} - {candidate.get('primaryArtists','')}".strip())
            dest = os.path.join("downloads", f"{safe_name}.mp3")
            async with aiohttp.ClientSession() as s:
                path = await _download_file(s, dl_url, dest)
            return path
        except Exception:
            return None
