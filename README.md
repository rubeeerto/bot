# Telegram Spotify-to-MP3 Bot

A Telegram bot that waits for Spotify track/playlist links, finds the track on YouTube, downloads audio via yt-dlp, converts to MP3 (ffmpeg), and sends it back to the user.

## Requirements
- Python 3.9+
- ffmpeg installed and available in PATH
- Telegram bot token from @BotFather
- Optional: Spotify API Client ID/Secret (for playlist metadata)

## Setup
1. Create and activate a venv (optional but recommended)
2. Install dependencies:
```bash
pip install -r requirements.txt
```
3. Create `.env` with:
```
BOT_TOKEN=123456:ABC-YourToken
SPOTIFY_CLIENT_ID=your_client_id   # optional
SPOTIFY_CLIENT_SECRET=your_client_secret # optional
```
4. Run the bot:
```bash
python bot.py
```

## Usage
- Send a Spotify track URL to the bot. It will search YouTube, download, convert to MP3, and send back.
- Send a Spotify playlist URL to download tracks one by one (can be long). You can stop the process by removing the bot or stopping the script.

## Notes
- Uses yt-dlp for YouTube search/download and pydub/ffmpeg for conversion if needed. yt-dlp can also extract and remux to MP3 directly via ffmpeg.
- This is for personal/educational use. Respect copyright and platform ToS.
