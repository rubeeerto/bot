#!/usr/bin/env python3
"""
Тест для проверки поддержки коротких Spotify ссылок
"""

import asyncio
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import EnhancedSpotifyParser

async def test_spotify_links():
    """Тестирует различные типы Spotify ссылок"""
    
    # Инициализируем парсер (без API ключей для теста)
    parser = EnhancedSpotifyParser()
    
    # Тестовые ссылки
    test_links = [
        "https://spotify.link/5Jz5GIGsCXb",  # Короткая ссылка
        "https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh",  # Полная ссылка трека
        "https://open.spotify.com/playlist/37i9dQZF1DXcBWIGoYBM5M",  # Плейлист
        "https://open.spotify.com/album/1A2GTWGtFfWp7KSQTwWOyo",  # Альбом
        "spotify:track:4iV5W9uYEdYUVa79Axb7Rh",  # URI формат
        "https://spoti.fi/abc123",  # Другая короткая ссылка
        "invalid_link",  # Неверная ссылка
    ]
    
    print("🧪 Тестирование поддержки Spotify ссылок\n")
    
    for i, link in enumerate(test_links, 1):
        print(f"Тест {i}: {link}")
        
        try:
            # Тестируем разрешение коротких ссылок
            resolved = await parser._resolve_short_url(link)
            print(f"   Разрешенная ссылка: {resolved}")
            
            # Тестируем извлечение ID
            ids = await parser.extract_ids_from_url(link)
            print(f"   Извлеченные ID: {ids}")
            
            # Проверяем результат
            if any(ids.values()):
                print("   ✅ Ссылка распознана")
            else:
                print("   ❌ Ссылка не распознана")
                
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
        
        print()
    
    print("🎯 Тест завершен!")

if __name__ == "__main__":
    asyncio.run(test_spotify_links())
