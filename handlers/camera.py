# handlers/camera.py — скриншот с веб-камеры

import io
import logging
import telebot

try:
    import cv2
    HAS_CV2 = True
except ImportError:
    HAS_CV2 = False


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(telebot.types.InlineKeyboardButton("📷 Снимок с камеры", callback_data="cam_snap"))
    bot.send_message(message.chat.id, "📷 *Веб-камера:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data == "cam_snap")
    def snap(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id, "📷 Снимаю...")
        if not HAS_CV2:
            bot.send_message(call.message.chat.id, "❌ opencv-python не установлен")
            return

        cap = None
        try:
            cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                bot.send_message(call.message.chat.id, "❌ Веб-камера не найдена")
                return

            ret, frame = cap.read()
            if not ret:
                bot.send_message(call.message.chat.id, "❌ Не удалось получить кадр")
                return

            _, buf = cv2.imencode(".jpg", frame,
                                  [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            bio = io.BytesIO(buf.tobytes())
            bio.name = "webcam.jpg"
            bot.send_photo(call.message.chat.id, bio, caption="📷 Снимок с веб-камеры")
            logging.info("Webcam snapshot taken successfully")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка камеры: {e}")
            logging.exception("Camera error")
        finally:
            if cap is not None:
                cap.release()
                cv2.destroyAllWindows()

    @bot.message_handler(commands=["webcam"])
    def cmd_webcam(message):
        if not is_allowed(message): return
        register(bot, message)
