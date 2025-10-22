# Обновление бота на Railway

## 🔧 Исправленные проблемы

### 1. Поддержка коротких Spotify ссылок
- ✅ Добавлена поддержка `https://spotify.link/...` ссылок
- ✅ Добавлена поддержка `https://spoti.fi/...` ссылок
- ✅ Автоматическое разрешение коротких ссылок

### 2. Исправление конфликта Telegram API
- ✅ Добавлена обработка ошибки "terminated by other getUpdates request"
- ✅ Автоматический перезапуск при конфликте
- ✅ Ограничение типов обновлений

### 3. Исправление ошибок YouTube
- ✅ Обновлены настройки yt-dlp для обхода аутентификации
- ✅ Добавлен innertube_key для YouTube Music
- ✅ Улучшена обработка ошибок

## 🚀 Развертывание обновлений

### Способ 1: Через Railway CLI
```bash
# Установите Railway CLI
npm install -g @railway/cli

# Войдите в аккаунт
railway login

# Подключитесь к проекту
railway link

# Разверните обновления
railway up
```

### Способ 2: Через GitHub
1. Зафиксируйте изменения в Git:
```bash
git add .
git commit -m "Fix Spotify links, Telegram conflicts, and YouTube errors"
git push origin main
```

2. Railway автоматически развернет обновления из main ветки

### Способ 3: Через Railway Dashboard
1. Откройте [Railway Dashboard](https://railway.app)
2. Выберите ваш проект
3. Нажмите "Deploy" в разделе "Deployments"
4. Выберите "Deploy from GitHub" и укажите ветку main

## 🔍 Проверка работы

После развертывания проверьте:

1. **Логи бота** - не должно быть ошибок конфликта Telegram
2. **Обработка ссылок** - попробуйте отправить:
   - `https://spotify.link/5Jz5GIGsCXb`
   - `https://open.spotify.com/track/4iV5W9uYEdYUVa79Axb7Rh`
3. **YouTube загрузки** - не должно быть ошибок "Please sign in"

## 📊 Мониторинг

Используйте команды для мониторинга:
- `/status` - статус бота
- `/help` - справка по использованию

## 🐛 Если что-то не работает

1. Проверьте логи в Railway Dashboard
2. Убедитесь, что все переменные окружения настроены
3. Проверьте, что бот не запущен локально (может вызывать конфликт)
4. Перезапустите сервис в Railway Dashboard

## 📝 Переменные окружения

Убедитесь, что настроены:
- `TELEGRAM_TOKEN` - токен бота
- `SPOTIFY_CLIENT_ID` - ID Spotify приложения
- `SPOTIFY_CLIENT_SECRET` - секрет Spotify приложения
- `PORT` - порт (обычно 8080)
