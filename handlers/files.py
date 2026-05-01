# handlers/files.py

import os
import shutil
import logging
import telebot
import hashlib
from config import DEFAULT_FOLDER

# Текущая папка для каждого пользователя
_current_dirs = {}

# Маппинг хешей на полные пути (решает проблему обрезки путей)
_path_cache = {}

def _hash_path(path: str) -> str:
    """Создаёт короткий хеш для длинного пути"""
    return hashlib.md5(path.encode('utf-8')).hexdigest()[:16]

def _store_path(path: str) -> str:
    """Сохраняет путь в кеш и возвращает хеш"""
    path_hash = _hash_path(path)
    _path_cache[path_hash] = path
    return path_hash

def _get_path(path_hash: str) -> str:
    """Получает путь из кеша по хешу"""
    return _path_cache.get(path_hash, path_hash)


def _cdir(uid):
    return _current_dirs.get(uid, DEFAULT_FOLDER)


def register(bot, message):
    uid = message.from_user.id
    _send_dir(bot, message.chat.id, uid, _cdir(uid))


def _send_dir(bot, chat_id, uid, path, message_id=None):
    try:
        entries = os.listdir(path)
    except PermissionError:
        text = f"❌ Нет доступа: `{path}`"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id)
        else:
            bot.send_message(chat_id, text)
        logging.error(f"Permission denied accessing: {path}")
        return
    except FileNotFoundError:
        text = f"❌ Папка не найдена: `{path}`"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id)
        else:
            bot.send_message(chat_id, text)
        logging.error(f"Directory not found: {path}")
        return
    except Exception as e:
        text = f"❌ Ошибка: {e}"
        if message_id:
            bot.edit_message_text(text, chat_id, message_id)
        else:
            bot.send_message(chat_id, text)
        logging.exception(f"Error listing directory {path}")
        return

    _current_dirs[uid] = path
    dirs = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))])

    # Фильтруем ненужные файлы (.lnk, .ini, .url)
    skip_extensions = ('.lnk', '.ini', '.url')
    fls = sorted([e for e in entries
                  if os.path.isfile(os.path.join(path, e))
                  and not e.lower().endswith(skip_extensions)])
    logging.info(f"Files found in {path}: {len(fls)} files after filtering")

    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    # Кнопка "вверх"
    parent = os.path.dirname(path)
    if parent != path:
        parent_hash = _store_path(parent)
        kb.add(telebot.types.InlineKeyboardButton("⬆️ ..", callback_data=f"fl_cd_{parent_hash}"))

    for d in dirs[:30]:
        full = os.path.join(path, d)
        full_hash = _store_path(full)
        kb.add(telebot.types.InlineKeyboardButton(f"📂 {d}", callback_data=f"fl_cd_{full_hash}"))

    for f in fls[:30]:
        full = os.path.join(path, f)
        try:
            size = os.path.getsize(full)
            label = f"📄 {f} ({_fmt_size(size)})"
        except Exception as e:
            logging.warning(f"Cannot get size for {full}: {e}")
            label = f"📄 {f}"

        full_hash = _store_path(full)
        kb.add(telebot.types.InlineKeyboardButton(label, callback_data=f"fl_file_{full_hash}"))

    kb.row(
        telebot.types.InlineKeyboardButton("📤 Получить файл", callback_data="fl_download"),
        telebot.types.InlineKeyboardButton("🗑 Удалить", callback_data="fl_delete"),
    )

    text = f"📁 `{path}`\n{len(dirs)} папок, {len(fls)} файлов"
    if message_id:
        bot.edit_message_text(text, chat_id, message_id, reply_markup=kb, parse_mode="Markdown")
    else:
        bot.send_message(chat_id, text, reply_markup=kb, parse_mode="Markdown")


def _fmt_size(b):
    if b < 1024: return f"{b}B"
    if b < 1024**2: return f"{b//1024}KB"
    if b < 1024**3: return f"{b//1024**2}MB"
    return f"{b//1024**3}GB"


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fl_cd_"))
    def nav_dir(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        path_hash = call.data.replace("fl_cd_", "")
        path = _get_path(path_hash)
        _send_dir(bot, call.message.chat.id, call.from_user.id, path, call.message.message_id)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fl_file_"))
    def show_file(call):
        if not is_allowed(call): return
        path_hash = call.data.replace("fl_file_", "")
        path = _get_path(path_hash)
        bot.answer_callback_query(call.id)
        try:
            size = os.path.getsize(path)
            kb = telebot.types.InlineKeyboardMarkup()
            dl_hash = _store_path(path)
            kb.add(telebot.types.InlineKeyboardButton(
                "📥 Скачать", callback_data=f"fl_dl_{dl_hash}"))
            kb.add(telebot.types.InlineKeyboardButton(
                "🗑 Удалить", callback_data=f"fl_del_{dl_hash}"))
            bot.send_message(call.message.chat.id,
                             f"📄 `{os.path.basename(path)}`\n💾 Размер: {_fmt_size(size)}",
                             reply_markup=kb)
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
            logging.exception(f"Error showing file {path}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fl_dl_"))
    def download_file(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id, "📤 Отправляю...")
        path_hash = call.data.replace("fl_dl_", "")
        path = _get_path(path_hash)
        try:
            if not os.path.exists(path):
                bot.send_message(call.message.chat.id, f"❌ Файл не найден: `{path}`")
                return
            if os.path.getsize(path) > 50 * 1024 * 1024:
                bot.send_message(call.message.chat.id, "❌ Файл больше 50MB — нельзя отправить через Telegram")
                return
            with open(path, "rb") as f:
                bot.send_document(call.message.chat.id, f,
                                  caption=f"📄 {os.path.basename(path)}")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
            logging.exception(f"Error downloading file {path}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fl_del_"))
    def confirm_delete(call):
        if not is_allowed(call): return
        path_hash = call.data.replace("fl_del_", "")
        path = _get_path(path_hash)
        bot.answer_callback_query(call.id)
        kb = telebot.types.InlineKeyboardMarkup()
        delok_hash = _store_path(path)
        kb.row(
            telebot.types.InlineKeyboardButton("✅ Да, удалить", callback_data=f"fl_delok_{delok_hash}"),
            telebot.types.InlineKeyboardButton("❌ Отмена", callback_data="fl_cancel"),
        )
        bot.send_message(call.message.chat.id,
                         f"⚠️ Удалить `{os.path.basename(path)}`?", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fl_delok_"))
    def do_delete(call):
        if not is_allowed(call): return
        path_hash = call.data.replace("fl_delok_", "")
        path = _get_path(path_hash)
        bot.answer_callback_query(call.id)
        try:
            if os.path.isdir(path):
                shutil.rmtree(path)
            else:
                os.remove(path)
            bot.send_message(call.message.chat.id, f"🗑 Удалено: `{os.path.basename(path)}`")
            logging.info(f"Deleted: {path}")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка удаления: {e}")
            logging.exception(f"Error deleting {path}")

    @bot.callback_query_handler(func=lambda c: c.data in ("fl_download", "fl_delete", "fl_cancel"))
    def misc(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        if call.data == "fl_download":
            msg = bot.send_message(call.message.chat.id, "📤 Введи полный путь к файлу:")
            bot.register_next_step_handler(msg, lambda m: _send_file_by_path(bot, m, is_allowed))
        elif call.data == "fl_cancel":
            bot.send_message(call.message.chat.id, "❌ Отменено")

    # Загрузка файла от пользователя
    @bot.message_handler(content_types=["document"])
    def receive_file(message):
        if not is_allowed(message): return
        uid = message.from_user.id
        dest_dir = _cdir(uid)
        try:
            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)
            dest = os.path.join(dest_dir, message.document.file_name)
            with open(dest, "wb") as f:
                f.write(downloaded)
            bot.reply_to(message, f"✅ Файл сохранён в `{dest}`")
        except Exception as e:
            bot.reply_to(message, f"❌ Ошибка сохранения: {e}")


def _send_file_by_path(bot, message, is_allowed):
    if not is_allowed(message): return
    path = message.text.strip()
    try:
        if not os.path.exists(path):
            bot.send_message(message.chat.id, f"❌ Файл не найден: `{path}`")
            return
        if os.path.getsize(path) > 50 * 1024 * 1024:
            bot.send_message(message.chat.id, "❌ Файл больше 50MB")
            return
        with open(path, "rb") as f:
            bot.send_document(message.chat.id, f, caption=f"📄 {os.path.basename(path)}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
