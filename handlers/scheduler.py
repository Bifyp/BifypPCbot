# handlers/scheduler.py — планировщик задач с настройкой через Telegram

import os
import json
import logging
import telebot
import threading
import time
from datetime import datetime, timedelta
import subprocess

# Файл с задачами
_tasks_file = "scheduled_tasks.json"
_tasks = {}  # task_id -> task_data
_task_threads = {}  # task_id -> threading.Event (stop)

# Временное хранилище для создания задач
_temp_task_data = {}  # user_id -> task_data

def _load_tasks():
    """Загружает задачи из файла"""
    global _tasks
    if os.path.exists(_tasks_file):
        try:
            with open(_tasks_file, "r", encoding="utf-8") as f:
                _tasks = json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load scheduled tasks: {e}")
            _tasks = {}

def _save_tasks():
    """Сохраняет задачи в файл"""
    try:
        with open(_tasks_file, "w", encoding="utf-8") as f:
            json.dump(_tasks, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save scheduled tasks: {e}")

def _generate_task_id():
    """Генерирует уникальный ID задачи"""
    import random
    while True:
        task_id = f"task_{random.randint(1000, 9999)}"
        if task_id not in _tasks:
            return task_id

def _parse_time(time_str):
    """Парсит время в формате HH:MM"""
    try:
        h, m = map(int, time_str.split(":"))
        if 0 <= h <= 23 and 0 <= m <= 59:
            return h, m
        return None
    except Exception:
        return None

def _run_task(task_id, bot, allowed_ids):
    """Выполняет задачу по расписанию"""
    if task_id not in _tasks:
        return

    task = _tasks[task_id]
    stop_event = threading.Event()
    _task_threads[task_id] = stop_event

    while not stop_event.is_set():
        try:
            now = datetime.now()
            task_time = _parse_time(task["time"])

            if not task_time:
                break

            h, m = task_time
            target = now.replace(hour=h, minute=m, second=0, microsecond=0)

            # Если время уже прошло сегодня, планируем на завтра
            if target <= now:
                target += timedelta(days=1)

            # Ждём до времени выполнения
            wait_seconds = (target - now).total_seconds()

            if stop_event.wait(timeout=wait_seconds):
                break  # Задача остановлена

            # Выполняем команду
            cmd = task["command"]
            logging.info(f"Executing scheduled task {task_id}: {cmd}")

            try:
                result = subprocess.run(
                    cmd, shell=True, capture_output=True, text=True,
                    timeout=300, encoding="utf-8", errors="replace"
                )

                output = result.stdout or result.stderr or "(нет вывода)"
                if len(output) > 500:
                    output = output[:500] + "...(обрезано)"

                # Отправляем уведомление
                for uid in allowed_ids:
                    try:
                        bot.send_message(uid,
                            f"⏰ *Задача выполнена:* `{task['name']}`\n"
                            f"🕐 Время: {task['time']}\n"
                            f"💻 Команда: `{cmd}`\n"
                            f"```\n{output}\n```")
                    except Exception:
                        pass

            except subprocess.TimeoutExpired:
                logging.warning(f"Scheduled task {task_id} timeout")
                for uid in allowed_ids:
                    try:
                        bot.send_message(uid,
                            f"⏱ *Задача превысила таймаут:* `{task['name']}`")
                    except Exception:
                        pass

            except Exception as e:
                logging.exception(f"Scheduled task {task_id} error")
                for uid in allowed_ids:
                    try:
                        bot.send_message(uid,
                            f"❌ *Ошибка задачи:* `{task['name']}`\n{e}")
                    except Exception:
                        pass

            # Если задача одноразовая, удаляем её
            if not task.get("repeat", True):
                del _tasks[task_id]
                _save_tasks()
                break

        except Exception as e:
            logging.exception(f"Task runner error for {task_id}")
            break

    # Cleanup
    if task_id in _task_threads:
        del _task_threads[task_id]

def start_scheduler(bot, allowed_ids):
    """Запускает все сохранённые задачи"""
    _load_tasks()
    for task_id in list(_tasks.keys()):
        threading.Thread(target=_run_task,
                        args=(task_id, bot, allowed_ids),
                        daemon=True).start()
    logging.info(f"Scheduler started with {len(_tasks)} tasks")

def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("➕ Добавить задачу", callback_data="sched_add"),
        telebot.types.InlineKeyboardButton("📋 Список задач", callback_data="sched_list"),
    )
    kb.add(telebot.types.InlineKeyboardButton("🗑 Удалить задачу", callback_data="sched_delete"))
    bot.send_message(message.chat.id, "⏰ *Планировщик задач:*", reply_markup=kb)

def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sched_"))
    def handle_scheduler(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if call.data == "sched_add":
            msg = bot.send_message(call.message.chat.id,
                                 "➕ *Новая задача*\n\n"
                                 "Введи название задачи:")
            bot.register_next_step_handler(msg, ask_task_name)

        elif call.data == "sched_list":
            if not _tasks:
                bot.send_message(call.message.chat.id, "📋 Нет запланированных задач")
                return

            text = "📋 *Запланированные задачи:*\n\n"
            for task_id, task in _tasks.items():
                status = "🟢 Активна" if task_id in _task_threads else "🔴 Остановлена"
                repeat = "🔁 Повторяется" if task.get("repeat", True) else "1️⃣ Одноразовая"
                text += (f"*{task['name']}*\n"
                        f"ID: `{task_id}`\n"
                        f"🕐 Время: {task['time']}\n"
                        f"💻 Команда: `{task['command']}`\n"
                        f"{status} | {repeat}\n\n")

            if len(text) > 3800:
                text = text[:3800] + "...(обрезано)"

            bot.send_message(call.message.chat.id, text)

        elif call.data == "sched_delete":
            if not _tasks:
                bot.send_message(call.message.chat.id, "📋 Нет задач для удаления")
                return

            kb = telebot.types.InlineKeyboardMarkup(row_width=1)
            for task_id, task in _tasks.items():
                kb.add(telebot.types.InlineKeyboardButton(
                    f"🗑 {task['name']} ({task['time']})",
                    callback_data=f"sched_del_{task_id}"
                ))

            bot.send_message(call.message.chat.id,
                           "🗑 *Выбери задачу для удаления:*",
                           reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sched_del_"))
    def delete_task(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        task_id = call.data.replace("sched_del_", "")

        if task_id in _tasks:
            task_name = _tasks[task_id]["name"]

            # Останавливаем поток
            if task_id in _task_threads:
                _task_threads[task_id].set()

            # Удаляем задачу
            del _tasks[task_id]
            _save_tasks()

            bot.send_message(call.message.chat.id, f"🗑 Задача удалена: `{task_name}`")
            logging.info(f"Scheduled task deleted: {task_id}")
        else:
            bot.send_message(call.message.chat.id, "❌ Задача не найдена")

    def ask_task_name(message):
        if not is_allowed(message): return
        name = message.text.strip()

        if not name or len(name) > 50:
            bot.send_message(message.chat.id, "❌ Название должно быть от 1 до 50 символов")
            return

        # Сохраняем во временное хранилище
        user_id = message.from_user.id
        _temp_task_data[user_id] = {"name": name}

        msg = bot.send_message(message.chat.id,
                             f"⏰ Задача: `{name}`\n\n"
                             f"Введи время выполнения (формат HH:MM, например 09:30):")
        bot.register_next_step_handler(msg, ask_task_time)

    def ask_task_time(message):
        if not is_allowed(message): return
        user_id = message.from_user.id

        if user_id not in _temp_task_data:
            bot.send_message(message.chat.id, "❌ Ошибка: начни создание задачи заново")
            return

        time_str = message.text.strip()

        if not _parse_time(time_str):
            bot.send_message(message.chat.id, "❌ Неверный формат времени. Используй HH:MM (например 09:30)")
            return

        _temp_task_data[user_id]["time"] = time_str

        msg = bot.send_message(message.chat.id,
                             f"⏰ Задача: `{_temp_task_data[user_id]['name']}`\n"
                             f"🕐 Время: {time_str}\n\n"
                             f"Введи команду для выполнения:")
        bot.register_next_step_handler(msg, ask_task_command)

    def ask_task_command(message):
        if not is_allowed(message): return
        user_id = message.from_user.id

        if user_id not in _temp_task_data:
            bot.send_message(message.chat.id, "❌ Ошибка: начни создание задачи заново")
            return

        command = message.text.strip()

        if not command:
            bot.send_message(message.chat.id, "❌ Команда не может быть пустой")
            return

        _temp_task_data[user_id]["command"] = command

        # Спрашиваем про повторение
        kb = telebot.types.InlineKeyboardMarkup()
        kb.row(
            telebot.types.InlineKeyboardButton("🔁 Повторять ежедневно", callback_data=f"sched_repeat_yes"),
            telebot.types.InlineKeyboardButton("1️⃣ Один раз", callback_data=f"sched_repeat_no"),
        )

        bot.send_message(message.chat.id,
                       f"⏰ *Задача настроена:*\n"
                       f"Название: `{_temp_task_data[user_id]['name']}`\n"
                       f"Время: {_temp_task_data[user_id]['time']}\n"
                       f"Команда: `{command}`\n\n"
                       f"Повторять задачу?",
                       reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sched_repeat_"))
    def set_repeat(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        user_id = call.from_user.id

        if user_id not in _temp_task_data:
            bot.send_message(call.message.chat.id, "❌ Ошибка: начни создание задачи заново")
            return

        repeat = call.data == "sched_repeat_yes"
        task_data = _temp_task_data[user_id]
        task_data["repeat"] = repeat

        # Создаём задачу
        task_id = _generate_task_id()
        _tasks[task_id] = task_data
        _save_tasks()

        # Запускаем поток для задачи (получаем bot_ref и allowed_ids из глобального контекста)
        # Это будет работать, так как setup вызывается с bot и is_allowed
        threading.Thread(target=_run_task,
                        args=(task_id, bot, [user_id]),
                        daemon=True).start()

        # Очищаем временные данные
        del _temp_task_data[user_id]

        repeat_text = "🔁 Повторяется ежедневно" if repeat else "1️⃣ Выполнится один раз"
        bot.send_message(call.message.chat.id,
                       f"✅ *Задача создана!*\n\n"
                       f"ID: `{task_id}`\n"
                       f"Название: `{task_data['name']}`\n"
                       f"Время: {task_data['time']}\n"
                       f"Команда: `{task_data['command']}`\n"
                       f"{repeat_text}")

        logging.info(f"Scheduled task created: {task_id}")

# Загружаем задачи при импорте
_load_tasks()
