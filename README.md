# WB Position Bot

Telegram bot to track Wildberries product positions by search phrases with per-user device and region (dest) selection.

## Features
- Manage articles and phrases with per-phrase thresholds
- Hourly auto-tracking with notifications
- Manual position check for one/all articles
- Region selection via federal district -> city (dest)
- Device selection (pc, android, ios)

## Requirements
- Python 3.11+
- PostgreSQL 13+

## Setup
1. Create `.env`:
```
TELEGRAM_TOKEN=your_bot_token
DATABASE_URL=postgresql+asyncpg://postgres:postgres@localhost:5432/wb_bot
SCHEDULER_ENABLED=true
DEFAULT_DEVICE=pc
```
2. Install deps:
```
python -m venv .venv
. .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```
3. Create database and run:
```
python bot.py
```

## Dest helper
Use the script to get dest by coordinates and address:
```
python scripts/fetch_dest.py 55.7558 37.6176 Москва
```

## Deploy on Render
- Use a Background Worker with `python bot.py`
- Set env vars from `.env` accordingly
- Ensure database network access
