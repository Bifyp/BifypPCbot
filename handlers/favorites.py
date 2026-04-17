# handlers/favorites.py

import json
import os
import logging
import telebot

FAVORITES_FILE = "favorites.json"
HISTORY_FILE   = "history.json"
MAX_HISTORY    = 20


def _load(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save(path, data):
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"favorites save error: {e}")


def add_to_history(command: str):
    history = _load(HISTORY_FILE)
    if not history or history[0] != command:
        history.insert(0, command)
    history = history[:MAX_HISTORY]
    _save(HISTORY_FILE, history)


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    kb.add(
        telebot.types.InlineKeyboardButton("⭐ Мои избранные", callback_data="fav_list"),
        telebot.types.InlineKeyboardButton("➕ Добавить команду", callback_data="fav_add"),
        telebot.types.InlineKeyboardButton("📜 История команд", callback_data="fav_history"),
    )
    bot.send_message(message.chat.id, "⭐ *Избранное и история:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in (
        "fav_list", "fav_add", "fav_history"))
    def handle_fav(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if call.data == "fav_list":
            favs = _load(FAVORITES_FILE)
            if not favs:
                bot.send_message(call.message.chat.id, "⭐ Список избранного пуст")
                return
            kb = telebot.types.InlineKeyboardMarkup(row_width=1)
            for i, item in enumerate(favs[:20]):
                kb.add(telebot.types.InlineKeyboardButton(
                    f"▶️ {item['name']}", callback_data=f"fav_run_{i}"))
            kb.add(telebot.types.InlineKeyboardButton("🗑 Удалить", callback_data="fav_del"))
            bot.send_message(call.message.chat.id, "⭐ *Избранные команды:*", reply_markup=kb)

        elif call.data == "fav_add":
            msg = bot.send_message(call.message.chat.id,
                "➕ Введи название и команду через `|`\nПример: `Открыть Chrome|chrome`")
            bot.register_next_step_handler(msg, do_add_fav)

        elif call.data == "fav_history":
            history = _load(HISTORY_FILE)
            if not history:
                bot.send_message(call.message.chat.id, "📜 История пуста")
                return
            text = "📜 *История команд:*\n" + "\n".join(f"`{h}`" for h in history)
            bot.send_message(call.message.chat.id, text)

    def do_add_fav(message):
        if not is_allowed(message): return
        try:
            parts = message.text.strip().split("|", 1)
            if len(parts) != 2:
                bot.send_message(message.chat.id, "❌ Формат: `Название|команда`")
                return
            name, cmd = parts[0].strip(), parts[1].strip()
            favs = _load(FAVORITES_FILE)
            favs.append({"name": name, "cmd": cmd})
            _save(FAVORITES_FILE, favs)
            bot.send_message(message.chat.id, f"✅ Добавлено: `{name}`")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fav_run_"))
    def run_fav(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        idx = int(call.data.replace("fav_run_", ""))
        favs = _load(FAVORITES_FILE)
        if idx >= len(favs):
            bot.send_message(call.message.chat.id, "❌ Не найдено")
            return
        import subprocess, os
        cmd = favs[idx]["cmd"]
        try:
            if ":" in cmd and not cmd.startswith("http"):
                os.startfile(cmd)
            else:
                subprocess.Popen(cmd, shell=True)
            add_to_history(cmd)
            bot.send_message(call.message.chat.id, f"✅ Запущено: `{cmd}`")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

    @bot.callback_query_handler(func=lambda c: c.data == "fav_del")
    def ask_del(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        favs = _load(FAVORITES_FILE)
        kb = telebot.types.InlineKeyboardMarkup(row_width=1)
        for i, item in enumerate(favs[:20]):
            kb.add(telebot.types.InlineKeyboardButton(
                f"🗑 {item['name']}", callback_data=f"fav_delidx_{i}"))
        bot.send_message(call.message.chat.id, "🗑 Выбери для удаления:", reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("fav_delidx_"))
    def do_del(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        idx = int(call.data.replace("fav_delidx_", ""))
        favs = _load(FAVORITES_FILE)
        if idx < len(favs):
            removed = favs.pop(idx)
            _save(FAVORITES_FILE, favs)
            bot.send_message(call.message.chat.id, f"✅ Удалено: `{removed['name']}`")
