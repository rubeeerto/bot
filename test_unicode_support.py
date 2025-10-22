#!/usr/bin/env python3
"""
Тест для проверки поддержки Unicode символов (китайские иероглифы, эмодзи и т.д.)
"""

import asyncio
import sys
import os

# Добавляем текущую директорию в путь
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from utils import clean_filename, EnhancedSoundCloudProvider

async def test_unicode_support():
    """Тестирует поддержку Unicode символов"""
    
    print("🧪 Тестирование поддержки Unicode символов\n")
    
    # Тестовые строки с различными Unicode символами
    test_strings = [
        "煉獄と猗窩座の戦い 椎名豪",  # Японские иероглифы
        "你好世界",  # Китайские иероглифы
        "Привет мир",  # Кириллица
        "مرحبا بالعالم",  # Арабский
        "🎵 Music Bot 🎶",  # Эмодзи
        "Café & Résumé",  # Диакритические знаки
        "Test/File*Name?",  # Проблемные символы
        "   Multiple   Spaces   ",  # Множественные пробелы
        "",  # Пустая строка
        "   ",  # Только пробелы
    ]
    
    print("📝 Тестирование функции clean_filename:")
    for i, test_str in enumerate(test_strings, 1):
        print(f"Тест {i}: '{test_str}'")
        try:
            cleaned = clean_filename(test_str)
            print(f"   Результат: '{cleaned}'")
            print(f"   Длина: {len(cleaned)} символов, {len(cleaned.encode('utf-8'))} байт")
            
            # Проверяем, что результат валиден
            if cleaned and cleaned != '_':
                print("   ✅ Успешно обработано")
            else:
                print("   ⚠️ Fallback на 'track'")
                
        except Exception as e:
            print(f"   ❌ Ошибка: {e}")
        print()
    
    print("🌐 Тестирование URL кодирования:")
    from urllib.parse import quote
    
    for i, test_str in enumerate(test_strings[:5], 1):  # Тестируем только первые 5
        print(f"Тест {i}: '{test_str}'")
        try:
            encoded = quote(test_str, safe='', encoding='utf-8')
            print(f"   Закодировано: {encoded}")
            print("   ✅ Успешно закодировано")
        except Exception as e:
            print(f"   ❌ Ошибка кодирования: {e}")
        print()
    
    print("🎯 Тест завершен!")

if __name__ == "__main__":
    asyncio.run(test_unicode_support())
