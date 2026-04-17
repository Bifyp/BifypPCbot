# handlers/macros.py — макросы клавиатуры и мыши

import os
import json
import logging
import telebot
import threading
import time

try:
    import pyautogui
    HAS_PYAUTOGUI = True
except ImportError:
    HAS_PYAUTOGUI = False

# Файл с макросами
_macros_file = "macros.json"
_macros = {}  # macro_id -> macro_data
_recording = {}  # user_id -> recording_data
_playing = {}  # user_id -> stop_event

def _load_macros():
    """Загружает макросы из файла"""
    global _macros
    if os.path.exists(_macros_file):
        try:
            with open(_macros_file, "r", encoding="utf-8") as f:
                _macros = json.load(f)
        except Exception as e:
            logging.warning(f"Failed to load macros: {e}")
            _macros = {}

def _save_macros():
    """Сохраняет макросы в файл"""
    try:
        with open(_macros_file, "w", encoding="utf-8") as f:
            json.dump(_macros, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.warning(f"Failed to save macros: {e}")

def _generate_macro_id():
    """Генерирует уникальный ID макроса"""
    import random
    while True:
        macro_id = f"macro_{random.randint(1000, 9999)}"
        if macro_id not in _macros:
            return macro_id

def _record_macro(duration, user_id):
    """Записывает действия пользователя"""
    if not HAS_PYAUTOGUI:
        return None

    actions = []
    start_time = time.time()
    last_pos = pyautogui.position()

    try:
        while time.time() - start_time < duration:
            current_pos = pyautogui.position()

            # Записываем движение мыши если позиция изменилась
            if current_pos != last_pos:
                actions.append({
                    "type": "move",
                    "x": current_pos[0],
                    "y": current_pos[1],
                    "time": time.time() - start_time
                })
                last_pos = current_pos

            time.sleep(0.05)  # 50ms между проверками

    except Exception as e:
        logging.exception("Macro recording error")
        return None

    return actions

def _play_macro(actions, repeat=1):
    """Воспроизводит макрос"""
    if not HAS_PYAUTOGUI or not actions:
        return

    try:
        for _ in range(repeat):
            start_time = time.time()

            for action in actions:
                # Ждём до нужного времени
                target_time = action["time"]
                current_time = time.time() - start_time

                if target_time > current_time:
                    time.sleep(target_time - current_time)

                # Выполняем действие
                if action["type"] == "move":
                    pyautogui.moveTo(action["x"], action["y"])
                elif action["type"] == "click":
                    pyautogui.click(button=action.get("button", "left"))
                elif action["type"] == "keypress":
                    pyautogui.press(action["key"])
                elif action["type"] == "type":
                    pyautogui.write(action["text"])

    except Exception as e:
        logging.exception("Macro playback error")

def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.row(
        telebot.types.InlineKeyboardButton("🔴 Записать макрос", callback_data="macro_record"),
        telebot.types.InlineKeyboardButton("📋 Мои макросы", callback_data="macro_list"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("➕ Создать простой", callback_data="macro_simple"),
        telebot.types.InlineKeyboardButton("🗑 Удалить", callback_data="macro_delete"),
    )
    bot.send_message(message.chat.id, "⌨️ *Макросы:*", reply_markup=kb)

def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("macro_"))
    def handle_macro(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if not HAS_PYAUTOGUI:
            bot.send_message(call.message.chat.id, "❌ pyautogui не установлен")
            return

        if call.data == "macro_record":
            msg = bot.send_message(call.message.chat.id,
                                 "🔴 *Запись макроса*\n\n"
                                 "Введи длительность записи в секундах (5-60):")
            bot.register_next_step_handler(msg, start_recording)

        elif call.data == "macro_simple":
            kb = telebot.types.InlineKeyboardMarkup(row_width=2)
            kb.add(
                telebot.types.InlineKeyboardButton("⌨️ Текст", callback_data="macro_type_text"),
                telebot.types.InlineKeyboardButton("🖱 Клик", callback_data="macro_type_click"),
            )
            kb.add(
                telebot.types.InlineKeyboardButton("🔑 Клавиша", callback_data="macro_type_key"),
                telebot.types.InlineKeyboardButton("⏱ Задержка", callback_data="macro_type_delay"),
            )
            bot.send_message(call.message.chat.id,
                           "➕ *Создать простой макрос*\n\nВыбери тип действия:",
                           reply_markup=kb)

        elif call.data == "macro_list":
            if not _macros:
                bot.send_message(call.message.chat.id, "📋 Нет сохранённых макросов")
                return

            text = "📋 *Сохранённые макросы:*\n\n"
            for macro_id, macro in _macros.items():
                text += (f"*{macro['name']}*\n"
                        f"ID: `{macro_id}`\n"
                        f"Действий: {len(macro.get('actions', []))}\n"
                        f"Тип: {macro.get('type', 'recorded')}\n\n")

            if len(text) > 3800:
                text = text[:3800] + "...(обрезано)"

            kb = telebot.types.InlineKeyboardMarkup(row_width=1)
            for macro_id, macro in list(_macros.items())[:10]:
                kb.add(telebot.types.InlineKeyboardButton(
                    f"▶️ {macro['name']}",
                    callback_data=f"macro_play_{macro_id}"
                ))

            bot.send_message(call.message.chat.id, text, reply_markup=kb)

        elif call.data == "macro_delete":
            if not _macros:
                bot.send_message(call.message.chat.id, "📋 Нет макросов для удаления")
                return

            kb = telebot.types.InlineKeyboardMarkup(row_width=1)
            for macro_id, macro in _macros.items():
                kb.add(telebot.types.InlineKeyboardButton(
                    f"🗑 {macro['name']}",
                    callback_data=f"macro_del_{macro_id}"
                ))

            bot.send_message(call.message.chat.id,
                           "🗑 *Выбери макрос для удаления:*",
                           reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("macro_play_"))
    def play_macro(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        macro_id = call.data.replace("macro_play_", "")

        if macro_id not in _macros:
            bot.send_message(call.message.chat.id, "❌ Макрос не найден")
            return

        macro = _macros[macro_id]

        # Спрашиваем количество повторений
        kb = telebot.types.InlineKeyboardMarkup()
        kb.row(
            telebot.types.InlineKeyboardButton("1x", callback_data=f"macro_run_{macro_id}_1"),
            telebot.types.InlineKeyboardButton("3x", callback_data=f"macro_run_{macro_id}_3"),
            telebot.types.InlineKeyboardButton("5x", callback_data=f"macro_run_{macro_id}_5"),
        )
        kb.add(telebot.types.InlineKeyboardButton("♾️ Бесконечно", callback_data=f"macro_run_{macro_id}_inf"))

        bot.send_message(call.message.chat.id,
                       f"▶️ *Запуск макроса:* `{macro['name']}`\n\n"
                       f"Сколько раз повторить?",
                       reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data.startswith("macro_run_"))
    def run_macro(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id, "▶️ Запускаю...")

        parts = call.data.replace("macro_run_", "").split("_")
        macro_id = parts[0]
        repeat = parts[1]

        if macro_id not in _macros:
            bot.send_message(call.message.chat.id, "❌ Макрос не найден")
            return

        macro = _macros[macro_id]

        if repeat == "inf":
            # Бесконечный цикл
            bot.send_message(call.message.chat.id,
                           f"♾️ Запущен бесконечный макрос: `{macro['name']}`\n"
                           f"Для остановки используй /stop_macro")

            def infinite_play():
                user_id = call.from_user.id
                stop_event = threading.Event()
                _playing[user_id] = stop_event

                while not stop_event.is_set():
                    _play_macro(macro.get("actions", []), repeat=1)
                    time.sleep(0.5)

                del _playing[user_id]

            threading.Thread(target=infinite_play, daemon=True).start()
        else:
            repeat_count = int(repeat)
            bot.send_message(call.message.chat.id,
                           f"▶️ Запускаю макрос `{macro['name']}` {repeat_count}x")

            def play():
                _play_macro(macro.get("actions", []), repeat=repeat_count)
                bot.send_message(call.message.chat.id,
                               f"✅ Макрос `{macro['name']}` выполнен")

            threading.Thread(target=play, daemon=True).start()

        logging.info(f"Macro executed: {macro_id} x{repeat}")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("macro_del_"))
    def delete_macro(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        macro_id = call.data.replace("macro_del_", "")

        if macro_id in _macros:
            macro_name = _macros[macro_id]["name"]
            del _macros[macro_id]
            _save_macros()

            bot.send_message(call.message.chat.id, f"🗑 Макрос удалён: `{macro_name}`")
            logging.info(f"Macro deleted: {macro_id}")
        else:
            bot.send_message(call.message.chat.id, "❌ Макрос не найден")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("macro_type_"))
    def create_simple(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        action_type = call.data.replace("macro_type_", "")

        if action_type == "text":
            msg = bot.send_message(call.message.chat.id,
                                 "⌨️ Введи текст для ввода:")
            bot.register_next_step_handler(msg, create_text_macro)

        elif action_type == "click":
            msg = bot.send_message(call.message.chat.id,
                                 "🖱 Введи координаты клика (x y), например: 500 300")
            bot.register_next_step_handler(msg, create_click_macro)

        elif action_type == "key":
            msg = bot.send_message(call.message.chat.id,
                                 "🔑 Введи название клавиши (enter, space, ctrl, alt и т.д.):")
            bot.register_next_step_handler(msg, create_key_macro)

        elif action_type == "delay":
            msg = bot.send_message(call.message.chat.id,
                                 "⏱ Введи задержку в секундах:")
            bot.register_next_step_handler(msg, create_delay_macro)

    def start_recording(message):
        if not is_allowed(message): return

        try:
            duration = int(message.text.strip())
            if not 5 <= duration <= 60:
                bot.send_message(message.chat.id, "❌ Длительность должна быть от 5 до 60 секунд")
                return
        except ValueError:
            bot.send_message(message.chat.id, "❌ Введи число")
            return

        bot.send_message(message.chat.id,
                       f"🔴 Запись начнётся через 3 секунды...\n"
                       f"Длительность: {duration} сек")

        def record():
            time.sleep(3)
            bot.send_message(message.chat.id, "🔴 ЗАПИСЬ НАЧАЛАСЬ!")

            actions = _record_macro(duration, message.from_user.id)

            if actions:
                bot.send_message(message.chat.id,
                               f"✅ Запись завершена!\n"
                               f"Записано действий: {len(actions)}\n\n"
                               f"Введи название для макроса:")

                # Сохраняем во временное хранилище
                _recording[message.from_user.id] = actions
            else:
                bot.send_message(message.chat.id, "❌ Ошибка записи")

        threading.Thread(target=record, daemon=True).start()

    @bot.message_handler(commands=["stop_macro"])
    def stop_macro(message):
        if not is_allowed(message): return
        user_id = message.from_user.id

        if user_id in _playing:
            _playing[user_id].set()
            bot.send_message(message.chat.id, "⏹ Макрос остановлен")
        else:
            bot.send_message(message.chat.id, "⚠️ Нет запущенных макросов")

    def create_text_macro(message):
        if not is_allowed(message): return
        text = message.text.strip()

        macro_id = _generate_macro_id()
        _macros[macro_id] = {
            "name": f"Текст: {text[:20]}...",
            "type": "simple",
            "actions": [{"type": "type", "text": text, "time": 0}]
        }
        _save_macros()

        bot.send_message(message.chat.id, f"✅ Макрос создан: `{macro_id}`")

    def create_click_macro(message):
        if not is_allowed(message): return

        try:
            x, y = map(int, message.text.strip().split())
            macro_id = _generate_macro_id()
            _macros[macro_id] = {
                "name": f"Клик ({x}, {y})",
                "type": "simple",
                "actions": [
                    {"type": "move", "x": x, "y": y, "time": 0},
                    {"type": "click", "button": "left", "time": 0.1}
                ]
            }
            _save_macros()

            bot.send_message(message.chat.id, f"✅ Макрос создан: `{macro_id}`")
        except Exception:
            bot.send_message(message.chat.id, "❌ Неверный формат. Используй: x y")

    def create_key_macro(message):
        if not is_allowed(message): return
        key = message.text.strip()

        macro_id = _generate_macro_id()
        _macros[macro_id] = {
            "name": f"Клавиша: {key}",
            "type": "simple",
            "actions": [{"type": "keypress", "key": key, "time": 0}]
        }
        _save_macros()

        bot.send_message(message.chat.id, f"✅ Макрос создан: `{macro_id}`")

    def create_delay_macro(message):
        if not is_allowed(message): return

        try:
            delay = float(message.text.strip())
            macro_id = _generate_macro_id()
            _macros[macro_id] = {
                "name": f"Задержка {delay}с",
                "type": "simple",
                "actions": [{"type": "delay", "time": delay}]
            }
            _save_macros()

            bot.send_message(message.chat.id, f"✅ Макрос создан: `{macro_id}`")
        except Exception:
            bot.send_message(message.chat.id, "❌ Введи число")

# Загружаем макросы при импорте
_load_macros()
