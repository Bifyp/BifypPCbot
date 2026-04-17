# handlers/terminal.py

import subprocess
import logging
import telebot
import json
import os

# История команд для каждого пользователя
_command_history = {}  # user_id -> [commands]
_history_file = "terminal_history.json"

def _load_history():
    """Загружает историю команд из файла"""
    global _command_history
    if os.path.exists(_history_file):
        try:
            with open(_history_file, "r", encoding="utf-8") as f:
                _command_history = json.load(f)
                # Конвертируем ключи обратно в int
                _command_history = {int(k): v for k, v in _command_history.items()}
        except Exception as e:
            logging.warning(f"Failed to load command history: {e}")
            _command_history = {}

def _save_history():
    """Сохраняет историю команд в файл"""
    try:
        with open(_history_file, "w", encoding="utf-8") as f:
            json.dump(_command_history, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save command history: {e}")

def _add_to_history(user_id, cmd):
    """Добавляет команду в историю пользователя"""
    if user_id not in _command_history:
        _command_history[user_id] = []

    # Избегаем дубликатов подряд
    if not _command_history[user_id] or _command_history[user_id][-1] != cmd:
        _command_history[user_id].append(cmd)

    # Ограничиваем историю 50 командами
    if len(_command_history[user_id]) > 50:
        _command_history[user_id] = _command_history[user_id][-50:]

    _save_history()

def _get_history(user_id, limit=10):
    """Получает последние команды из истории"""
    if user_id not in _command_history:
        return []
    return _command_history[user_id][-limit:]

# Загружаем историю при импорте модуля
_load_history()


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("💻 Ввести команду", callback_data="term_input"),
        telebot.types.InlineKeyboardButton("📜 История", callback_data="term_history"),
    )
    kb.add(telebot.types.InlineKeyboardButton("🗑 Очистить историю", callback_data="term_clear_history"))
    bot.send_message(message.chat.id, "💻 *Терминал* (cmd):", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in ("term_input", "term_history", "term_clear_history"))
    def handle_terminal(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if call.data == "term_input":
            msg = bot.send_message(call.message.chat.id, "💻 Введи команду:")
            bot.register_next_step_handler(msg, run_cmd)

        elif call.data == "term_history":
            user_id = call.from_user.id
            history = _get_history(user_id, limit=10)

            if not history:
                bot.send_message(call.message.chat.id, "📜 История команд пуста")
                return

            kb = telebot.types.InlineKeyboardMarkup(row_width=1)
            for i, cmd in enumerate(reversed(history), 1):
                # Обрезаем длинные команды для кнопки
                label = cmd if len(cmd) <= 40 else cmd[:37] + "..."
                kb.add(telebot.types.InlineKeyboardButton(
                    f"{i}. {label}",
                    callback_data=f"term_run_{len(history) - i}"
                ))

            bot.send_message(call.message.chat.id,
                           "📜 *История команд:*\nВыбери команду для повторного запуска:",
                           reply_markup=kb)

        elif call.data == "term_clear_history":
            user_id = call.from_user.id
            if user_id in _command_history:
                _command_history[user_id] = []
                _save_history()
            bot.send_message(call.message.chat.id, "🗑 История команд очищена")
            logging.info(f"Command history cleared for user {user_id}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("term_run_"))
    def run_from_history(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        try:
            user_id = call.from_user.id
            index = int(call.data.replace("term_run_", ""))
            history = _get_history(user_id, limit=50)

            if 0 <= index < len(history):
                cmd = history[index]
                bot.send_message(call.message.chat.id, f"💻 Выполняю: `{cmd}`")
                _execute(bot, call.message.chat.id, cmd, user_id)
            else:
                bot.send_message(call.message.chat.id, "❌ Команда не найдена в истории")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
            logging.exception("Error running command from history")

    @bot.message_handler(commands=["cmd"])
    def cmd_cmd(message):
        if not is_allowed(message): return
        parts = message.text.split(" ", 1)
        if len(parts) < 2:
            msg = bot.send_message(message.chat.id, "💻 Введи команду:")
            bot.register_next_step_handler(msg, run_cmd)
        else:
            _execute(bot, message.chat.id, parts[1], message.from_user.id)

    def run_cmd(message):
        if not is_allowed(message): return
        _execute(bot, message.chat.id, message.text.strip(), message.from_user.id)


def _execute(bot, chat_id, cmd, user_id=None):
    # Добавляем в историю
    if user_id:
        _add_to_history(user_id, cmd)

    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=30, encoding="cp866", errors="replace"
        )
        output = result.stdout or result.stderr or "(нет вывода)"

        # Попытка декодировать UTF-8 если cp866 дал мусор
        if result.stdout and "�" in output:
            try:
                result_utf8 = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=30, encoding="utf-8", errors="replace"
                )
                output = result_utf8.stdout or result_utf8.stderr or "(нет вывода)"
            except Exception:
                pass

        if len(output) > 3800:
            output = output[:3800] + "\n...(обрезано)"
        bot.send_message(chat_id, f"```\n{output}\n```")
        logging.info(f"Terminal command executed: {cmd[:50]}")
    except subprocess.TimeoutExpired:
        bot.send_message(chat_id, "⏱ Команда выполнялась слишком долго (таймаут 30с)")
        logging.warning(f"Terminal timeout: {cmd}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка выполнения: {e}")
        logging.exception(f"Terminal error executing: {cmd}")
