# handlers/clipboard.py

import logging
import telebot

try:
    import win32clipboard
    HAS_WIN32 = True
except ImportError:
    HAS_WIN32 = False


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("👁 Посмотреть", callback_data="clip_view"),
        telebot.types.InlineKeyboardButton("✏️ Добавить", callback_data="clip_add"),
    )
    kb.row(
        telebot.types.InlineKeyboardButton("🗑 Очистить", callback_data="clip_clear"),
    )
    bot.send_message(message.chat.id, "📋 *Буфер обмена:*", reply_markup=kb)


def _get_clipboard():
    if not HAS_WIN32:
        import subprocess
        result = subprocess.run("powershell Get-Clipboard", capture_output=True,
                                text=True, shell=True)
        return result.stdout.strip()
    win32clipboard.OpenClipboard()
    try:
        data = win32clipboard.GetClipboardData()
    except Exception:
        data = "(пусто или не текст)"
    win32clipboard.CloseClipboard()
    return data


def _set_clipboard(text):
    if not HAS_WIN32:
        import subprocess
        subprocess.run(f'powershell Set-Clipboard "{text}"', shell=True)
        return
    win32clipboard.OpenClipboard()
    win32clipboard.EmptyClipboard()
    win32clipboard.SetClipboardText(text, win32clipboard.CF_UNICODETEXT)
    win32clipboard.CloseClipboard()


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in ("clip_view", "clip_add", "clip_clear"))
    def handle_clip(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if call.data == "clip_view":
            try:
                text = _get_clipboard()
                if not text or text == "(пусто или не текст)":
                    bot.send_message(call.message.chat.id, "📋 Буфер обмена пуст")
                    return

                # Показываем первые 3000 символов
                if len(text) > 3000:
                    preview = text[:3000] + "...(обрезано)"
                    bot.send_message(call.message.chat.id,
                                   f"📋 *Содержимое буфера обмена:*\n```\n{preview}\n```\n\n"
                                   f"Всего символов: {len(text)}")
                else:
                    bot.send_message(call.message.chat.id,
                                   f"📋 *Содержимое буфера обмена:*\n```\n{text}\n```")
                logging.info("Clipboard content viewed")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка чтения: {e}")
                logging.exception("Clipboard read error")

        elif call.data == "clip_add":
            msg = bot.send_message(call.message.chat.id,
                                 "✏️ Введи текст для добавления в буфер обмена:")
            bot.register_next_step_handler(msg, write_clip)

        elif call.data == "clip_clear":
            try:
                _set_clipboard("")
                bot.send_message(call.message.chat.id, "🗑 Буфер обмена очищен")
                logging.info("Clipboard cleared")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка очистки: {e}")
                logging.exception("Clipboard clear error")

    def write_clip(message):
        if not is_allowed(message): return
        try:
            _set_clipboard(message.text)
            bot.send_message(message.chat.id,
                           f"✅ Текст добавлен в буфер обмена\n"
                           f"Символов: {len(message.text)}")
            logging.info(f"Clipboard updated with {len(message.text)} chars")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка записи: {e}")
            logging.exception("Clipboard write error")
