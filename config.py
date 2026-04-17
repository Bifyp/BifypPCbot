# config.py — загрузка конфигурации из .env

import os
from typing import List
from dotenv import load_dotenv

# Загружаем .env файл
load_dotenv()

# Telegram Bot
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
ALLOWED_IDS: List[int] = [int(id.strip()) for id in os.getenv("ALLOWED_USER_IDS", "").split(",") if id.strip()]

# Папка по умолчанию для файлового менеджера
DEFAULT_FOLDER: str = os.getenv("DEFAULT_FOLDER", "C:\\Users")

# Пароль для веб-панели
WEB_PANEL_PASSWORD: str = os.getenv("WEB_PANEL_PASSWORD", "")

# Порт Flask
FLASK_PORT: int = int(os.getenv("FLASK_PORT", "5000"))

# Безопасность
SESSION_LIFETIME_HOURS: int = int(os.getenv("SESSION_LIFETIME_HOURS", "2"))
MAX_LOGIN_ATTEMPTS: int = int(os.getenv("MAX_LOGIN_ATTEMPTS", "5"))
BAN_DURATION_MINUTES: int = int(os.getenv("BAN_DURATION_MINUTES", "10"))
NOTIFY_ON_WEB_LOGIN: bool = os.getenv("NOTIFY_ON_WEB_LOGIN", "True").lower() == "true"

# Автоскриншоты
AUTO_SCREENSHOT_ENABLED: bool = os.getenv("AUTO_SCREENSHOT_ENABLED", "False").lower() == "true"
AUTO_SCREENSHOT_INTERVAL: int = int(os.getenv("AUTO_SCREENSHOT_INTERVAL", "300"))
AUTO_SCREENSHOT_KEEP: int = int(os.getenv("AUTO_SCREENSHOT_KEEP", "10"))

# Детект активности
ACTIVITY_DETECT_ENABLED: bool = os.getenv("ACTIVITY_DETECT_ENABLED", "False").lower() == "true"
ACTIVITY_IDLE_MINUTES: int = int(os.getenv("ACTIVITY_IDLE_MINUTES", "5"))

# Алиасы для совместимости
ACTIVITY_DETECT: bool = ACTIVITY_DETECT_ENABLED
ACTIVITY_IDLE_SECONDS: int = ACTIVITY_IDLE_MINUTES * 60

# Алерты
ALERT_CPU_THRESHOLD: int = int(os.getenv("ALERT_CPU_THRESHOLD", "80"))
ALERT_RAM_THRESHOLD: int = int(os.getenv("ALERT_RAM_THRESHOLD", "85"))
ALERT_DISK_THRESHOLD: int = int(os.getenv("ALERT_DISK_THRESHOLD", "90"))
ALERT_CHECK_INTERVAL: int = int(os.getenv("ALERT_CHECK_INTERVAL", "300"))

# Wake-on-LAN
WOL_MAC: str = os.getenv("WOL_MAC", "AA:BB:CC:DD:EE:FF")

# Проверка обязательных параметров
if not BOT_TOKEN:
    raise ValueError("BOT_TOKEN не установлен в .env файле!")
if not ALLOWED_IDS:
    raise ValueError("ALLOWED_USER_IDS не установлен в .env файле!")
if not WEB_PANEL_PASSWORD:
    raise ValueError("WEB_PANEL_PASSWORD не установлен в .env файле!")
