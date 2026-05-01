# bot.py — точка входа v2.0

import telebot
import threading
import time
import logging
import os

from config import BOT_TOKEN, ALLOWED_IDS
from web.server import start_web_server, set_bot_ref

from handlers import (
    apps, screenshot, terminal, media,
    browser, files, system, input_handler,
    clipboard, tts, alerts, log, favorites,
    camera, audio, network, autoscreenshot, installer, scheduler, macros
)

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="Markdown")


def is_allowed(message_or_call):
    """
    Принимает Message или CallbackQuery.
    - Message: from_user.id — это пользователь ✅
    - CallbackQuery: message.from_user — это БОТ ❌, нужно call.from_user ✅
    """
    obj = message_or_call
    # Если передали CallbackQuery напрямую (call, не call.message)
    if hasattr(obj, "data"):  # это CallbackQuery
        uid = getattr(obj, "from_user", None)
        return uid is not None and uid.id in ALLOWED_IDS
    # Обычное Message
    uid = getattr(obj, "from_user", None)
    if uid is None:
        uid = getattr(obj, "chat", None)
    if uid is None:
        return False
    return (uid.id if hasattr(uid, "id") else uid) in ALLOWED_IDS


# ─── /start ───────────────────────────────────────────────────────────────────

@bot.message_handler(commands=["start"])
def cmd_start(message):
    if not is_allowed(message):
        return
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.row("📸 Скриншот",    "📁 Файлы",    "💻 Терминал")
    keyboard.row("🔊 Медиа",       "🌐 Браузер",  "⚙️ Система")
    keyboard.row("🚀 Приложения",  "⌨️ Ввод",    "📋 Буфер")
    keyboard.row("🔊 TTS",         "🔔 Алерты",   "📜 Лог")
    keyboard.row("⭐ Избранное",   "📷 Камера",   "🎙 Звук")
    keyboard.row("🌐 Сеть",        "🖼 Авто-фото","📦 Установка")
    keyboard.row("⏰ Планировщик", "⌨️ Макросы",  "📹 Удалённый доступ")

    banner = os.path.join(os.path.dirname(__file__), "start_banner.jpg")
    try:
        with open(banner, "rb") as img:
            bot.send_photo(
                message.chat.id, img,
                caption="✅ *PC Control Bot v2.0 запущен!*\nВыбери раздел 👇",
                reply_markup=keyboard
            )
    except Exception:
        bot.send_message(message.chat.id,
                         "✅ *PC Control Bot v2.0*\nВыбери раздел:",
                         reply_markup=keyboard)


# ─── Меню → хендлеры ──────────────────────────────────────────────────────────

MENU = {
    "📹 Удалённый доступ": "_remote",
    "📸 Скриншот":         "_scr",
    "📁 Файлы":            "_files",
    "💻 Терминал":         "_term",
    "🔊 Медиа":            "_media",
    "🌐 Браузер":          "_browser",
    "⚙️ Система":          "_system",
    "🚀 Приложения":       "_apps",
    "⌨️ Ввод":             "_input",
    "📋 Буфер":            "_clip",
    "🔊 TTS":              "_tts",
    "🔔 Алерты":           "_alerts",
    "📜 Лог":              "_log",
    "⭐ Избранное":        "_fav",
    "📷 Камера":           "_cam",
    "🎙 Звук":             "_audio",
    "🌐 Сеть":             "_net",
    "🖼 Авто-фото":        "_asc",
    "📦 Установка":        "_inst",
    "⏰ Планировщик":      "_sched",
    "⌨️ Макросы":          "_macros",
}


@bot.message_handler(func=lambda m: is_allowed(m) and m.text in MENU)
def menu_handler(message):
    key = MENU[message.text]
    if key == "_remote":
        from web.server import get_tunnel_url
        url = get_tunnel_url()
        if url:
            bot.send_message(message.chat.id,
                             f"🌐 *Веб-панель:*\n{url}\n\n🔒 Введи пароль из `config.py`\n"
                             f"⏱ Сессия истекает через 2 часа")
        else:
            bot.send_message(message.chat.id,
                             "⏳ Туннель запускается, подожди 10–15 сек...")
    elif key == "_scr":     screenshot.register(bot, message)
    elif key == "_files":   files.register(bot, message)
    elif key == "_term":    terminal.register(bot, message)
    elif key == "_media":   media.register(bot, message)
    elif key == "_browser": browser.register(bot, message)
    elif key == "_system":  system.register(bot, message)
    elif key == "_apps":    apps.register(bot, message)
    elif key == "_input":   input_handler.register(bot, message)
    elif key == "_clip":    clipboard.register(bot, message)
    elif key == "_tts":     tts.register(bot, message)
    elif key == "_alerts":  alerts.register(bot, message)
    elif key == "_log":     log.register(bot, message)
    elif key == "_fav":     favorites.register(bot, message)
    elif key == "_cam":     camera.register(bot, message)
    elif key == "_audio":   audio.register(bot, message)
    elif key == "_net":     network.register(bot, message)
    elif key == "_asc":     autoscreenshot.register(bot, message)
    elif key == "_inst":    installer.register(bot, message)
    elif key == "_sched":   scheduler.register(bot, message)
    elif key == "_macros":  macros.register(bot, message)


# ─── Регистрация хендлеров ────────────────────────────────────────────────────

def _register_all():
    apps.setup(bot, is_allowed)
    screenshot.setup(bot, is_allowed)
    terminal.setup(bot, is_allowed)
    media.setup(bot, is_allowed)
    browser.setup(bot, is_allowed)
    files.setup(bot, is_allowed)
    system.setup(bot, is_allowed)
    input_handler.setup(bot, is_allowed)
    clipboard.setup(bot, is_allowed)
    tts.setup(bot, is_allowed)
    alerts.setup(bot, is_allowed)
    log.setup(bot, is_allowed)
    favorites.setup(bot, is_allowed)
    camera.setup(bot, is_allowed)
    audio.setup(bot, is_allowed)
    network.setup(bot, is_allowed)
    autoscreenshot.setup(bot, is_allowed)
    installer.setup(bot, is_allowed)
    scheduler.setup(bot, is_allowed)
    macros.setup(bot, is_allowed)


# ─── Запуск ───────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    logging.info("PC Control Bot v2.0 запускается...")

    # Передаём ссылку на бот в web-сервер (для уведомлений)
    set_bot_ref(bot, ALLOWED_IDS)

    # Flask + cloudflared
    threading.Thread(target=start_web_server, daemon=True).start()

    # Системные алерты
    threading.Thread(target=alerts.start_monitoring,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    # Авто-скриншоты + детект активности
    threading.Thread(target=autoscreenshot.start_auto_tasks,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    # Планировщик задач
    threading.Thread(target=scheduler.start_scheduler,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    # Регистрация хендлеров
    _register_all()

    # Уведомление "ПК онлайн" через 30 сек
    def notify_online():
        time.sleep(30)
        from web.server import get_tunnel_url
        url = get_tunnel_url() or "_(туннель ещё запускается)_"
        for uid in ALLOWED_IDS:
            try:
                bot.send_message(uid,
                    f"✅ *PC Control Bot v2.0 онлайн!*\n"
                    f"🌐 Веб-панель: {url}\n"
                    f"🔒 Сессия: 2 часа\n"
                    f"📡 WebSocket: активен")
            except Exception as e:
                logging.warning(f"notify error: {e}")

    threading.Thread(target=notify_online, daemon=True).start()

    logging.info("Polling запущен")

    bot.infinity_polling(timeout=30, long_polling_timeout=15)
