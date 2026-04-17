# handlers/apps.py

import subprocess
import psutil
import os
import glob
import logging
import telebot

_bot = None
_is_allowed = None

QUICK_APPS = {
    "🌐 Chrome":    "chrome",
    "📁 Проводник": "explorer",
    "📝 Блокнот":   "notepad",
    "🖩 Калькулятор": "calc",
    "⚙️ Параметры": "ms-settings:",
    "🎮 Steam":     "steam",
    "📺 VLC":       "vlc",
}


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    btns = [telebot.types.InlineKeyboardButton(name, callback_data=f"app_launch_{cmd}")
            for name, cmd in QUICK_APPS.items()]
    kb.add(*btns)
    kb.row(telebot.types.InlineKeyboardButton("🔍 Поиск .exe", callback_data="app_search"),
           telebot.types.InlineKeyboardButton("📋 Процессы", callback_data="app_procs"))
    bot.send_message(message.chat.id, "🚀 *Приложения:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):
    global _bot, _is_allowed
    _bot = bot
    _is_allowed = is_allowed

    @bot.callback_query_handler(func=lambda c: c.data.startswith("app_launch_"))
    def launch_app(call):
        if not is_allowed(call): return
        cmd = call.data.replace("app_launch_", "")
        try:
            os.startfile(cmd) if ":" in cmd else subprocess.Popen(cmd, shell=True)
            bot.answer_callback_query(call.id, f"✅ Запущено")
            bot.send_message(call.message.chat.id, f"✅ Запущено: `{cmd}`")
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Ошибка")
            bot.send_message(call.message.chat.id, f"❌ Не удалось запустить: {e}")

    @bot.callback_query_handler(func=lambda c: c.data == "app_search")
    def ask_search(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔍 Введи название программы (например: `vlc`):")
        bot.register_next_step_handler(msg, do_search)

    def do_search(message):
        if not is_allowed(message): return
        name = message.text.strip()
        results = []
        search_dirs = [
            "C:\\Program Files", "C:\\Program Files (x86)",
            os.path.expanduser("~\\AppData\\Local"),
        ]
        for d in search_dirs:
            try:
                for f in glob.glob(f"{d}\\**\\{name}*.exe", recursive=True)[:5]:
                    results.append(f)
            except Exception:
                pass
        if results:
            kb = telebot.types.InlineKeyboardMarkup()
            for path in results[:6]:
                label = os.path.basename(path)
                kb.add(telebot.types.InlineKeyboardButton(
                    f"▶️ {label}", callback_data=f"app_run_{path[:50]}"))
            bot.send_message(message.chat.id,
                             f"🔍 Найдено {len(results)} результатов:", reply_markup=kb)
        else:
            bot.send_message(message.chat.id, f"❌ `{name}.exe` не найден")

    @bot.callback_query_handler(func=lambda c: c.data.startswith("app_run_"))
    def run_found(call):
        if not is_allowed(call): return
        path = call.data.replace("app_run_", "")
        try:
            subprocess.Popen(path, shell=True)
            bot.answer_callback_query(call.id, "✅")
            bot.send_message(call.message.chat.id, f"✅ Запускаю: `{path}`")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

    @bot.callback_query_handler(func=lambda c: c.data == "app_procs")
    def show_procs(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        procs = sorted(psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
                       key=lambda p: p.info["memory_percent"] or 0, reverse=True)[:15]
        text = "📋 *Топ процессов по памяти:*\n"
        for p in procs:
            text += f"• `{p.info['name'][:25]}` — RAM {p.info['memory_percent']:.1f}%\n"
        kb = telebot.types.InlineKeyboardMarkup()
        kb.add(telebot.types.InlineKeyboardButton("🔪 Завершить процесс", callback_data="app_kill"))
        bot.send_message(call.message.chat.id, text, reply_markup=kb)

    @bot.callback_query_handler(func=lambda c: c.data == "app_kill")
    def ask_kill(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        msg = bot.send_message(call.message.chat.id, "🔪 Введи имя процесса (например: `notepad.exe`):")
        bot.register_next_step_handler(msg, do_kill)

    def do_kill(message):
        if not is_allowed(message): return
        name = message.text.strip()
        killed = 0
        for proc in psutil.process_iter(["name"]):
            if proc.info["name"].lower() == name.lower():
                proc.kill()
                killed += 1
        if killed:
            bot.send_message(message.chat.id, f"✅ Завершено {killed} процесс(ов): `{name}`")
        else:
            bot.send_message(message.chat.id, f"❌ Процесс `{name}` не найден")
