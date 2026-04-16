# TaskFlow — планнер в Telegram

Синхронизация в обе стороны: задачи из чата с ботом и из Mini App лежат в одной базе.

## Архитектура

```
┌─────────────┐        ┌──────────────┐        ┌──────────┐
│  Telegram   │◄──────►│   bot.py     │◄──────►│          │
│   чат       │        │              │        │ tasks.db │
└─────────────┘        └──────────────┘        │ (SQLite) │
                                                │          │
┌─────────────┐        ┌──────────────┐        │          │
│  Mini App   │◄──────►│  server.py   │◄──────►│          │
│  (WebApp)   │  HTTPS │  FastAPI     │        │          │
└─────────────┘        └──────────────┘        └──────────┘
```

Оба процесса читают/пишут в `tasks.db`. Добавил в чате — видно в приложении. Удалил в приложении — бот знает.

---

## Установка

### 1. Получи токен
Открой @BotFather → `/newbot` → скопируй токен.

### 2. Поставь зависимости
```bash
cd "Telegram BOT"
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Настрой `.env`
```bash
cp .env.example .env
# Впиши BOT_TOKEN
```

### 4. Запусти HTTPS-туннель (для разработки)
Telegram Mini App требует HTTPS. Самый простой способ — [ngrok](https://ngrok.com):
```bash
ngrok http 8000
```
Скопируй полученный `https://abc123.ngrok-free.app` в `.env` как `WEBAPP_URL`.

### 5. Запусти сервер и бота (в двух терминалах)
```bash
# Терминал 1 — API + Mini App
uvicorn server:app --host 0.0.0.0 --port 8000

# Терминал 2 — бот
python bot.py
```

### 6. Проверь
В Telegram открой бота → нажми "📅 Планнер" в меню или пришли `/app`.

---

## Команды в чате

| Команда | Что делает |
|---------|-----------|
| любой текст | создаёт задачу (дата распознаётся автоматически) |
| `/app` | открыть Mini App |
| `/today` | задачи на сегодня |
| `/week` | ближайшие 7 дней |
| `/all` | все задачи |
| `/done 5` | отметить #5 выполненной |
| `/del 5` | удалить #5 |

Примеры текста:
- `позвонить Алексу завтра в 15:00` → задача, завтра 15:00
- `дедлайн отчёт в понедельник` → дедлайн, понедельник
- `созвон с командой в пятницу в 11 на 30 минут` → встреча, пятница 11:00, 30 мин

---

## Деплой на VPS

На сервере с HTTPS (Let's Encrypt / Cloudflare):

```bash
# systemd unit для сервера
sudo tee /etc/systemd/system/taskflow-api.service > /dev/null <<EOF
[Unit]
Description=TaskFlow API
After=network.target
[Service]
User=youruser
WorkingDirectory=/path/to/Telegram BOT
Environment="PATH=/path/to/venv/bin"
ExecStart=/path/to/venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000
Restart=always
[Install]
WantedBy=multi-user.target
EOF

# systemd unit для бота
sudo tee /etc/systemd/system/taskflow-bot.service > /dev/null <<EOF
[Unit]
Description=TaskFlow Bot
After=network.target
[Service]
User=youruser
WorkingDirectory=/path/to/Telegram BOT
ExecStart=/path/to/venv/bin/python bot.py
Restart=always
[Install]
WantedBy=multi-user.target
EOF

sudo systemctl enable --now taskflow-api taskflow-bot
```

Настрой nginx/Caddy как reverse proxy на `127.0.0.1:8000`.

---

## Безопасность

- Все API-запросы из Mini App содержат `X-Init-Data` header.
- `server.py` валидирует его через HMAC-SHA256 по схеме Telegram — никто не может подделать `user_id`.
- `ALLOW_UNSAFE_DEV=1` включает fallback `?uid=123` **только для разработки**. В проде держи `0`.
- `BOT_TOKEN` — секрет. В `.env`, не в git (в `.gitignore`).
