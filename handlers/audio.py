# handlers/audio.py — запись звука с микрофона

import io
import os
import wave
import logging
import threading
import telebot

try:
    import sounddevice as sd
    import numpy as np
    HAS_SD = True
except ImportError:
    HAS_SD = False


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=3)
    kb.add(
        telebot.types.InlineKeyboardButton("🎙 5 сек",  callback_data="aud_rec_5"),
        telebot.types.InlineKeyboardButton("🎙 15 сек", callback_data="aud_rec_15"),
        telebot.types.InlineKeyboardButton("🎙 30 сек", callback_data="aud_rec_30"),
    )
    bot.send_message(message.chat.id, "🎙 *Запись звука с микрофона:*", reply_markup=kb)


def _record_wav(seconds: int) -> bytes:
    """Записывает аудио с микрофона с проверкой доступности устройства"""
    samplerate = 44100
    channels   = 1

    # Проверка доступности устройства
    try:
        devices = sd.query_devices()
        if not devices:
            raise RuntimeError("Нет доступных аудио устройств")

        # Проверка наличия устройства ввода
        default_input = sd.query_devices(kind='input')
        if not default_input:
            raise RuntimeError("Микрофон не найден")
    except Exception as e:
        raise RuntimeError(f"Ошибка проверки устройства: {e}")

    recording = sd.rec(int(seconds * samplerate),
                        samplerate=samplerate,
                        channels=channels,
                        dtype="int16",
                        blocking=False)

    # Ожидание с таймаутом (добавляем 5 сек запаса)
    timeout = seconds + 5
    if not sd.wait(timeout=timeout):
        sd.stop()
        raise TimeoutError(f"Запись превысила таймаут {timeout}с")

    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(recording.tobytes())
    buf.seek(0)
    return buf.read()


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("aud_rec_"))
    def handle_rec(call):
        if not is_allowed(call): return
        if not HAS_SD:
            bot.answer_callback_query(call.id, "❌ sounddevice не установлен")
            bot.send_message(call.message.chat.id, "❌ Установи: `pip install sounddevice`")
            return
        secs = int(call.data.replace("aud_rec_", ""))
        bot.answer_callback_query(call.id, f"🎙 Пишу {secs} сек...")
        bot.send_message(call.message.chat.id, f"🎙 Запись {secs} сек — подожди...")

        def do_record():
            try:
                wav_bytes = _record_wav(secs)
                bio = io.BytesIO(wav_bytes)
                bio.name = f"record_{secs}s.wav"
                bot.send_audio(call.message.chat.id, bio,
                               caption=f"🎙 Запись {secs} сек")
                logging.info(f"Audio recorded successfully: {secs}s")
            except TimeoutError as e:
                bot.send_message(call.message.chat.id, f"⏱ Таймаут записи: {e}")
                logging.warning(f"Audio recording timeout: {e}")
            except RuntimeError as e:
                bot.send_message(call.message.chat.id, f"❌ {e}")
                logging.error(f"Audio device error: {e}")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка записи: {e}")
                logging.exception("Audio recording error")

        threading.Thread(target=do_record, daemon=True).start()

    @bot.message_handler(commands=["record"])
    def cmd_record(message):
        if not is_allowed(message): return
        parts = message.text.split()
        if len(parts) == 2:
            try:
                secs = max(1, min(60, int(parts[1])))
                bot.send_message(message.chat.id, f"🎙 Записываю {secs} сек...")
                def do():
                    try:
                        wav_bytes = _record_wav(secs)
                        bio = io.BytesIO(wav_bytes)
                        bio.name = f"record_{secs}s.wav"
                        bot.send_audio(message.chat.id, bio,
                                       caption=f"🎙 Запись {secs} сек")
                        logging.info(f"Audio recorded via command: {secs}s")
                    except TimeoutError as e:
                        bot.send_message(message.chat.id, f"⏱ Таймаут: {e}")
                        logging.warning(f"Audio timeout: {e}")
                    except RuntimeError as e:
                        bot.send_message(message.chat.id, f"❌ {e}")
                        logging.error(f"Audio device error: {e}")
                    except Exception as e:
                        bot.send_message(message.chat.id, f"❌ {e}")
                        logging.exception("Audio recording error")
                threading.Thread(target=do, daemon=True).start()
                return
            except ValueError:
                pass
        register(bot, message)
