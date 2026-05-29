# handlers/anydesk.py — запуск AnyDesk

import os
import subprocess
import logging
from typing import Optional


def find_anydesk() -> Optional[str]:
    """Шукає AnyDesk в стандартних місцях."""
    possible_paths = [
        r"C:\Program Files (x86)\AnyDesk\AnyDesk.exe",
        r"C:\Program Files\AnyDesk\AnyDesk.exe",
        os.path.expanduser(r"~\AppData\Local\AnyDesk\AnyDesk.exe"),
        os.path.expanduser(r"~\AppData\Roaming\AnyDesk\AnyDesk.exe"),
    ]

    for path in possible_paths:
        if os.path.exists(path):
            return path

    return None


def start_anydesk(anydesk_path: str) -> bool:
    """Запускає AnyDesk."""
    try:
        subprocess.Popen([anydesk_path], shell=False)
        return True
    except Exception as e:
        logging.error(f"Помилка запуску AnyDesk: {e}")
        return False


def setup(bot, is_allowed):
    """Реєструє хендлери для AnyDesk."""
    pass


def register(bot, message):
    """Запускає AnyDesk."""
    if not is_allowed(message):
        return

    anydesk_path = find_anydesk()

    if not anydesk_path:
        bot.send_message(
            message.chat.id,
            "❌ AnyDesk не знайдено!\n\nВстанови з anydesk.com",
        )
        return

    if start_anydesk(anydesk_path):
        bot.send_message(
            message.chat.id,
            "✅ AnyDesk запущено!\n\n"
            "Відкрий AnyDesk на ПК щоб побачити ID",
        )
    else:
        bot.send_message(
            message.chat.id,
            "❌ Не вдалося запустити AnyDesk",
        )
