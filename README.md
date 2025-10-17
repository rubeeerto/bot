# Spotify Music Bot

Телеграм бот для поиска и скачивания музыки по ссылкам Spotify.

## Возможности

- 🎵 Парсинг ссылок Spotify (треки, плейлисты, альбомы)
- 🔍 Поиск музыки в онлайн ресурсах (YouTube)
- 📥 Скачивание и отправка MP3 файлов
- 📊 Поддержка плейлистов до 15 треков
- 🎧 Качество 192kbps MP3
- 📁 Ограничение размера файла 50MB

## Установка

1. Клонируйте репозиторий:
```bash
git clone <repository-url>
cd spotifyBOT
```

2. Установите зависимости:
```bash
pip install -r requirements.txt
```

3. Настройте переменные окружения:
   - Скопируйте `.env.example` в `.env`
   - Добавьте токены (см. SPOTIFY_SETUP.md для настройки Spotify API)

4. Запустите бота:
```bash
python main.py
```

## Настройка

### Обязательные переменные:
- `TELEGRAM_TOKEN` - токен вашего телеграм бота

### Опциональные переменные:
- `SPOTIFY_CLIENT_ID` - Client ID из Spotify Developer Dashboard
- `SPOTIFY_CLIENT_SECRET` - Client Secret из Spotify Developer Dashboard

Подробная инструкция по настройке Spotify API в файле `SPOTIFY_SETUP.md`.

## Использование

1. Отправьте боту команду `/start`
2. Отправьте ссылку на трек, плейлист или альбом Spotify
3. Дождитесь обработки и получения MP3 файла

### Поддерживаемые форматы ссылок:
- `https://open.spotify.com/track/...`
- `https://open.spotify.com/playlist/...`
- `https://open.spotify.com/album/...`
- `spotify:track:...`
- `spotify:playlist:...`
- `spotify:album:...`

## Ограничения

- Плейлисты и альбомы: максимум 15 треков за раз
- Размер файла: максимум 50MB
- Качество: 192kbps MP3
- Поиск осуществляется через YouTube

## Структура проекта

```
spotifyBOT/
├── main.py              # Основной файл бота
├── utils.py              # Утилиты и вспомогательные классы
├── requirements.txt      # Зависимости Python
├── README.md            # Документация
├── SPOTIFY_SETUP.md     # Инструкция по настройке Spotify API
└── downloads/           # Папка для временных файлов (создается автоматически)
```

## Команды бота

- `/start` - Начать работу с ботом
- `/help` - Получить помощь по использованию

## Технические детали

- **Фреймворк**: aiogram 3.x
- **Парсинг Spotify**: spotipy
- **Скачивание**: yt-dlp
- **Поиск**: YouTube
- **Формат**: MP3 192kbps

## Лицензия

Этот проект предназначен только для образовательных целей. Пожалуйста, соблюдайте авторские права и условия использования Spotify и YouTube.
