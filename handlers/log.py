# handlers/log.py

import os
import logging
import telebot


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("📄 Последние 30 строк", callback_data="log_tail"),
        telebot.types.InlineKeyboardButton("📥 Скачать bot.log", callback_data="log_download"),
    )
    kb.row(
        telebot.types.InlineKeyboardButton("🔒 Скачать security.log", callback_data="log_security"),
        telebot.types.InlineKeyboardButton("📦 Скачать все логи", callback_data="log_all"),
    )
    kb.add(telebot.types.InlineKeyboardButton("🗑 Очистить bot.log", callback_data="log_clear"))
    bot.send_message(message.chat.id, "📜 *Логи системы:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in ("log_tail", "log_download", "log_security", "log_all", "log_clear"))
    def handle_log(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        log_path = "bot.log"
        security_path = "security.log"

        if call.data == "log_tail":
            try:
                if not os.path.exists(log_path):
                    bot.send_message(call.message.chat.id, "📄 Лог пуст")
                    return
                with open(log_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()
                tail = "".join(lines[-30:])
                if len(tail) > 3800:
                    tail = tail[-3800:]
                bot.send_message(call.message.chat.id, f"📄 *Последние 30 строк:*\n```\n{tail}\n```")
                logging.info("Log tail viewed")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                logging.exception("Log tail error")

        elif call.data == "log_download":
            try:
                if not os.path.exists(log_path):
                    bot.send_message(call.message.chat.id, "📄 bot.log не найден")
                    return
                with open(log_path, "rb") as f:
                    bot.send_document(call.message.chat.id, f, caption="📜 bot.log")
                logging.info("bot.log downloaded")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                logging.exception("Log download error")

        elif call.data == "log_security":
            try:
                if not os.path.exists(security_path):
                    bot.send_message(call.message.chat.id, "🔒 security.log не найден")
                    return
                with open(security_path, "rb") as f:
                    bot.send_document(call.message.chat.id, f, caption="🔒 security.log")
                logging.info("security.log downloaded")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                logging.exception("Security log download error")

        elif call.data == "log_all":
            try:
                import zipfile
                import tempfile
                import time

                zip_path = tempfile.mktemp(suffix=".zip")
                with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
                    if os.path.exists(log_path):
                        zf.write(log_path, "bot.log")
                    if os.path.exists(security_path):
                        zf.write(security_path, "security.log")

                with open(zip_path, "rb") as f:
                    bot.send_document(call.message.chat.id, f,
                                    caption=f"📦 Все логи ({time.strftime('%Y-%m-%d %H:%M')})")

                os.remove(zip_path)
                logging.info("All logs downloaded as ZIP")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                logging.exception("All logs download error")

        elif call.data == "log_clear":
            kb = telebot.types.InlineKeyboardMarkup()
            kb.row(
                telebot.types.InlineKeyboardButton("✅ Да", callback_data="log_clear_ok"),
                telebot.types.InlineKeyboardButton("❌ Нет", callback_data="log_clear_no"),
            )
            bot.send_message(call.message.chat.id, "⚠️ Очистить bot.log?", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data in ("log_clear_ok", "log_clear_no"))
    def confirm_clear(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        if call.data == "log_clear_ok":
            try:
                with open("bot.log", "w", encoding="utf-8") as f:
                    f.write("")
                bot.send_message(call.message.chat.id, "✅ bot.log очищен")
                logging.info("bot.log cleared by user")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                logging.exception("Log clear error")
        else:
            bot.send_message(call.message.chat.id, "❌ Отменено")
