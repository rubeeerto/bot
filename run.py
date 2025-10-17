#!/usr/bin/env python3
"""
Скрипт запуска Spotify Music Bot
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

def check_requirements():
    """Проверяет наличие необходимых файлов и зависимостей"""
    required_files = ['main.py', 'utils.py', 'requirements.txt']
    
    for file in required_files:
        if not Path(file).exists():
            print(f"❌ Файл {file} не найден!")
            return False
    
    # Проверяем переменные окружения
    if not os.getenv('TELEGRAM_TOKEN'):
        print("❌ TELEGRAM_TOKEN не установлен!")
        print("Создайте файл .env и добавьте токен бота")
        return False
    
    return True

def setup_logging():
    """Настраивает логирование"""
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler('bot.log'),
            logging.StreamHandler(sys.stdout)
        ]
    )

def main():
    """Основная функция"""
    print("🎵 Spotify Music Bot")
    print("=" * 50)
    
    # Проверяем требования
    if not check_requirements():
        print("\n❌ Проверка не пройдена. Убедитесь, что все файлы на месте.")
        sys.exit(1)
    
    # Настраиваем логирование
    setup_logging()
    
    # Создаем папку для загрузок
    os.makedirs("downloads", exist_ok=True)
    
    print("✅ Все проверки пройдены")
    print("🚀 Запускаю бота...")
    
    try:
        # Импортируем и запускаем бота
        from main import main as bot_main
        asyncio.run(bot_main())
    except KeyboardInterrupt:
        print("\n👋 Бот остановлен пользователем")
    except Exception as e:
        print(f"\n❌ Ошибка при запуске бота: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
