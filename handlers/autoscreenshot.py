# handlers/autoscreenshot.py — авто-скриншоты + детект активности

import mss
import io
import os
import time
import logging
import threading
import pyautogui
from PIL import Image
from collections import deque

from config import (AUTO_SCREENSHOT_ENABLED, AUTO_SCREENSHOT_INTERVAL,
                    AUTO_SCREENSHOT_KEEP, ACTIVITY_DETECT_ENABLED,
                    ACTIVITY_IDLE_MINUTES)

_screenshot_buffer = deque(maxlen=AUTO_SCREENSHOT_KEEP)  # bytes
_auto_enabled      = AUTO_SCREENSHOT_ENABLED
_last_mouse_pos    = None
_last_move_time    = time.time()
_activity_alerted  = False   # чтобы не спамить


def _take() -> bytes:
    with mss.mss() as sct:
        raw = sct.grab(sct.monitors[1])
        img = Image.frombytes("RGB", raw.size, raw.bgra, "raw", "BGRX")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=70)
    return buf.getvalue()


def start_auto_tasks(bot, user_ids: list):
    """Запускается в фоне из bot.py"""

    def notify(text, photo=None):
        for uid in user_ids:
            try:
                if photo:
                    bot.send_photo(uid, io.BytesIO(photo), caption=text)
                else:
                    bot.send_message(uid, text)
            except Exception:
                pass

    # ── Авто-скриншоты ────────────────────────────────────────────────────
    def auto_screenshot_loop():
        while True:
            time.sleep(AUTO_SCREENSHOT_INTERVAL)
            if not _auto_enabled:
                continue
            try:
                data = _take()
                _screenshot_buffer.append(data)
                logging.info("Авто-скриншот сохранён в буфер")
            except Exception as e:
                logging.error(f"auto_screenshot error: {e}")

    # ── Детект активности ─────────────────────────────────────────────────
    def activity_loop():
        global _last_mouse_pos, _last_move_time, _activity_alerted
        _last_mouse_pos = pyautogui.position()
        while True:
            time.sleep(15)
            if not ACTIVITY_DETECT_ENABLED:
                continue
            try:
                pos = pyautogui.position()
                if pos != _last_mouse_pos:
                    _last_mouse_pos  = pos
                    _last_move_time  = time.time()
                    if _activity_alerted:
                        # активность возобновилась
                        _activity_alerted = False

                idle_mins = (time.time() - _last_move_time) / 60
                if idle_mins < 0.5 and not _activity_alerted:
                    # Кто-то работает — присылаем скриншот
                    _activity_alerted = True
                    data = _take()
                    notify("👀 *Обнаружена активность за ПК!*\nКто-то работает за компьютером.",
                           photo=data)
            except Exception as e:
                logging.error(f"activity_loop error: {e}")

    threading.Thread(target=auto_screenshot_loop, daemon=True).start()
    threading.Thread(target=activity_loop,        daemon=True).start()


def get_buffer_screenshots():
    return list(_screenshot_buffer)


def set_auto_enabled(val: bool):
    global _auto_enabled
    _auto_enabled = val


def register(bot, message):
    global _auto_enabled
    status = "✅ Включены" if _auto_enabled else "❌ Выключены"
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(
            "❌ Выключить" if _auto_enabled else "✅ Включить",
            callback_data="asc_toggle"),
        telebot.types.InlineKeyboardButton("📸 Последние 3", callback_data="asc_show"),
    )
    import telebot as tb
    bot.send_message(message.chat.id,
                     f"📸 *Авто-скриншоты:* {status}\n"
                     f"Интервал: {AUTO_SCREENSHOT_INTERVAL} сек\n"
                     f"Буфер: {len(_screenshot_buffer)}/{AUTO_SCREENSHOT_KEEP} шт",
                     reply_markup=kb)


import telebot

def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in ("asc_toggle", "asc_show"))
    def handle_asc(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        if call.data == "asc_toggle":
            set_auto_enabled(not _auto_enabled)
            state = "✅ Включены" if _auto_enabled else "❌ Выключены"
            bot.send_message(call.message.chat.id, f"📸 Авто-скриншоты: {state}")
        elif call.data == "asc_show":
            buf = get_buffer_screenshots()
            if not buf:
                bot.send_message(call.message.chat.id, "📸 Буфер пуст")
                return
            for i, data in enumerate(buf[-3:], 1):
                bot.send_photo(call.message.chat.id,
                               io.BytesIO(data), caption=f"📸 #{i}")
