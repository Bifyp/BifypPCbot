# handlers/tts.py

import threading
import logging
import telebot

try:
    import pyttsx3
    HAS_TTS = True
except Exception:
    HAS_TTS = False

_lock = threading.Lock()


def register(bot, message):
    if not HAS_TTS:
        bot.send_message(message.chat.id, "❌ pyttsx3 не установлен")
        return
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("🔊 Произнести текст", callback_data="tts_speak"))
    bot.send_message(message.chat.id, "🔊 *TTS — Голосовой вывод:*", reply_markup=kb)


def _speak(text: str):
    """
    Каждый раз создаём новый движок в СВОЁМ потоке.
    pyttsx3 на Windows использует COM (SAPI5) — нельзя вызывать
    из потока, который не вызвал CoInitialize.
    Также выбираем первый голос с поддержкой кириллицы (если есть).
    """
    with _lock:
        try:
            import comtypes
            comtypes.CoInitialize()
        except Exception:
            pass
        try:
            engine = pyttsx3.init()
            engine.setProperty("rate", 160)

            # Ищем русский SAPI-голос
            voices = engine.getProperty("voices")
            ru_voice = None
            for v in voices:
                name = (v.name or "").lower()
                langs = [str(l).lower() for l in (v.languages or [])]
                if "ru" in name or "russian" in name or any("ru" in l for l in langs):
                    ru_voice = v.id
                    break

            if ru_voice:
                engine.setProperty("voice", ru_voice)
            # Если русского голоса нет — используем дефолтный,
            # но передаём текст как есть (SAPI5 сам справляется с Unicode)

            engine.say(text)
            engine.runAndWait()
            engine.stop()
        except Exception as e:
            logging.error(f"TTS error: {e}")
        finally:
            try:
                import comtypes
                comtypes.CoUninitialize()
            except Exception:
                pass


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data == "tts_speak")
    def ask_tts(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔊 Введи текст для произношения:")
        bot.register_next_step_handler(msg, do_speak)

    def do_speak(message):
        if not is_allowed(message): return
        if not HAS_TTS:
            bot.send_message(message.chat.id, "❌ pyttsx3 не доступен")
            return
        try:
            threading.Thread(target=_speak, args=(message.text,), daemon=True).start()
            bot.send_message(message.chat.id, f"🔊 Произношу: _{message.text[:80]}_")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка TTS: {e}")
