# handlers/browser.py

import webbrowser
import subprocess
import logging
import telebot


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("🌐 Открыть URL", callback_data="br_url"),
        telebot.types.InlineKeyboardButton("🔍 Поиск Google", callback_data="br_search"),
        telebot.types.InlineKeyboardButton("📺 YouTube", callback_data="br_yt"),
        telebot.types.InlineKeyboardButton("🔒 Закрыть браузер", callback_data="br_close"),
    )
    bot.send_message(message.chat.id, "🌐 *Браузер:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in (
        "br_url", "br_search", "br_yt", "br_close"))
    def handle_browser(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        data = call.data

        try:
            if data == "br_url":
                msg = bot.send_message(call.message.chat.id, "🌐 Введи URL (например: `https://google.com`):")
                bot.register_next_step_handler(msg, open_url)
            elif data == "br_search":
                msg = bot.send_message(call.message.chat.id, "🔍 Введи поисковый запрос:")
                bot.register_next_step_handler(msg, do_search)
            elif data == "br_yt":
                msg = bot.send_message(call.message.chat.id, "📺 Введи поисковый запрос для YouTube:")
                bot.register_next_step_handler(msg, do_yt)
            elif data == "br_close":
                subprocess.run("taskkill /f /im chrome.exe", shell=True)
                subprocess.run("taskkill /f /im firefox.exe", shell=True)
                subprocess.run("taskkill /f /im msedge.exe", shell=True)
                bot.send_message(call.message.chat.id, "🔒 Браузеры закрыты")
        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

    def open_url(message):
        if not is_allowed(message): return
        url = message.text.strip()
        try:
            webbrowser.open(url)
            bot.send_message(message.chat.id, f"✅ Открываю: {url}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

    def do_search(message):
        if not is_allowed(message): return
        query = message.text.strip()
        try:
            url = f"https://www.google.com/search?q={query.replace(' ', '+')}"
            webbrowser.open(url)
            bot.send_message(message.chat.id, f"🔍 Ищу: {query}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

    def do_yt(message):
        if not is_allowed(message): return
        query = message.text.strip()
        try:
            url = f"https://www.youtube.com/results?search_query={query.replace(' ', '+')}"
            webbrowser.open(url)
            bot.send_message(message.chat.id, f"📺 YouTube: {query}")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
