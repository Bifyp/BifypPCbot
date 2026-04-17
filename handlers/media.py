# handlers/media.py

import logging
import threading
import telebot

try:
    from pycaw.pycaw import AudioUtilities, IAudioEndpointVolume
    from comtypes import CLSCTX_ALL
    import ctypes
    import comtypes
    HAS_PYCAW = True
except ImportError:
    HAS_PYCAW = False

import pyautogui


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        telebot.types.InlineKeyboardButton("🔉 -10%",     callback_data="vol_down"),
        telebot.types.InlineKeyboardButton("🔊 Уровень",  callback_data="vol_get"),
        telebot.types.InlineKeyboardButton("🔊 +10%",     callback_data="vol_up"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("🔇 Mute",      callback_data="vol_mute"),
        telebot.types.InlineKeyboardButton("⏯ Play/Pause", callback_data="media_play"),
        telebot.types.InlineKeyboardButton("⏭ Next",       callback_data="media_next"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("⏮ Prev",      callback_data="media_prev"),
        telebot.types.InlineKeyboardButton("🔈 Задать %", callback_data="vol_set"),
    )
    bot.send_message(message.chat.id, "🔊 *Медиа и звук:*", reply_markup=kb)


def _vol_thread(fn):
    """Запускает fn в отдельном COM-потоке."""
    def worker():
        try:
            comtypes.CoInitialize()
        except OSError:
            # COM уже инициализирован в этом потоке
            pass
        try:
            fn()
        except Exception as e:
            logging.exception("Volume COM error")
        finally:
            try:
                comtypes.CoUninitialize()
            except Exception:
                pass
    threading.Thread(target=worker, daemon=True).start()


def _get_vol_interface():
    devices   = AudioUtilities.GetSpeakers()
    interface = devices.Activate(IAudioEndpointVolume._iid_, CLSCTX_ALL, None)
    return ctypes.cast(interface, ctypes.POINTER(IAudioEndpointVolume))


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in (
        "vol_down", "vol_up", "vol_get", "vol_mute",
        "media_play", "media_next", "media_prev", "vol_set"))
    def handle_media(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        data = call.data
        cid  = call.message.chat.id

        try:
            if data == "media_play":
                pyautogui.press("playpause")
                bot.send_message(cid, "⏯ Play/Pause")
            elif data == "media_next":
                pyautogui.press("nexttrack")
                bot.send_message(cid, "⏭ Следующий трек")
            elif data == "media_prev":
                pyautogui.press("prevtrack")
                bot.send_message(cid, "⏮ Предыдущий трек")
            elif data == "vol_mute":
                pyautogui.press("volumemute")
                bot.send_message(cid, "🔇 Mute переключён")

            elif data in ("vol_up", "vol_down", "vol_get"):
                if not HAS_PYCAW:
                    bot.send_message(cid, "❌ pycaw не установлен"); return
                def do_vol(d=data):
                    vol     = _get_vol_interface()
                    current = round(vol.GetMasterVolumeLevelScalar() * 100)
                    if d == "vol_up":
                        new = min(100, current + 10)
                        vol.SetMasterVolumeLevelScalar(new / 100, None)
                        bot.send_message(cid, f"🔊 Громкость: {new}%")
                    elif d == "vol_down":
                        new = max(0, current - 10)
                        vol.SetMasterVolumeLevelScalar(new / 100, None)
                        bot.send_message(cid, f"🔉 Громкость: {new}%")
                    else:
                        bot.send_message(cid, f"🔊 Текущая громкость: {current}%")
                _vol_thread(do_vol)

            elif data == "vol_set":
                msg = bot.send_message(cid, "🔊 Введи уровень громкости (0-100):")
                bot.register_next_step_handler(msg, set_volume_step)

        except Exception as e:
            bot.send_message(cid, f"❌ Ошибка медиа: {e}")
            logging.error(f"media error: {e}")

    def set_volume_step(message):
        if not is_allowed(message): return
        cid = message.chat.id
        try:
            level = max(0, min(100, int(message.text.strip())))
        except ValueError:
            bot.send_message(cid, "❌ Введи число от 0 до 100"); return
        if not HAS_PYCAW:
            bot.send_message(cid, "❌ pycaw не установлен"); return
        def do_set():
            vol = _get_vol_interface()
            vol.SetMasterVolumeLevelScalar(level / 100, None)
            bot.send_message(cid, f"✅ Громкость установлена: {level}%")
        _vol_thread(do_set)
