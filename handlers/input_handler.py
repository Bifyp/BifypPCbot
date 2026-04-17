# handlers/input_handler.py — с фиксом кириллицы через pyperclip

import pyautogui
import pyperclip
import logging
import telebot

pyautogui.FAILSAFE = False


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("⌨️ Hotkey", callback_data="inp_hotkey"),
        telebot.types.InlineKeyboardButton("✏️ Написать текст", callback_data="inp_type"),
        telebot.types.InlineKeyboardButton("🖱 Скролл ↑", callback_data="inp_scroll_up"),
        telebot.types.InlineKeyboardButton("🖱 Скролл ↓", callback_data="inp_scroll_down"),
        telebot.types.InlineKeyboardButton("🖥 Позиция мыши", callback_data="inp_pos"),
        telebot.types.InlineKeyboardButton("🖱 Клик ЛКМ", callback_data="inp_lclick"),
        telebot.types.InlineKeyboardButton("🖱 Клик ПКМ", callback_data="inp_rclick"),
    )
    bot.send_message(message.chat.id, "⌨️ *Ввод (мышь и клавиатура):*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("inp_"))
    def handle_input(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        data = call.data
        try:
            if data == "inp_hotkey":
                msg = bot.send_message(call.message.chat.id,
                    "⌨️ Введи хоткей через + (например: `ctrl+c`, `alt+f4`, `win+d`):")
                bot.register_next_step_handler(msg, do_hotkey)

            elif data == "inp_type":
                msg = bot.send_message(call.message.chat.id,
                    "✏️ Введи текст (кириллица поддерживается):")
                bot.register_next_step_handler(msg, do_type)

            elif data == "inp_scroll_up":
                pyautogui.scroll(5)
                bot.send_message(call.message.chat.id, "🖱 Скролл вверх ×5")

            elif data == "inp_scroll_down":
                pyautogui.scroll(-5)
                bot.send_message(call.message.chat.id, "🖱 Скролл вниз ×5")

            elif data == "inp_pos":
                x, y = pyautogui.position()
                bot.send_message(call.message.chat.id, f"🖱 Позиция курсора: `{x}, {y}`")

            elif data == "inp_lclick":
                pyautogui.click(button="left")
                bot.send_message(call.message.chat.id, "🖱 ЛКМ нажата")

            elif data == "inp_rclick":
                pyautogui.click(button="right")
                bot.send_message(call.message.chat.id, "🖱 ПКМ нажата")

        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

    def do_hotkey(message):
        if not is_allowed(message): return
        keys = message.text.strip().split("+")
        try:
            pyautogui.hotkey(*keys)
            bot.send_message(message.chat.id, f"✅ Нажато: `{message.text.strip()}`")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")

    def do_type(message):
        if not is_allowed(message): return
        try:
            # Фикс кириллицы и спецсимволов — через буфер обмена
            old_clip = ""
            try:
                old_clip = pyperclip.paste()
            except Exception:
                pass
            pyperclip.copy(message.text)
            pyautogui.hotkey("ctrl", "v")
            # Восстанавливаем предыдущий буфер через секунду
            import threading
            def restore():
                import time; time.sleep(1.0)
                try: pyperclip.copy(old_clip)
                except: pass
            threading.Thread(target=restore, daemon=True).start()
            bot.send_message(message.chat.id, f"✅ Текст набран: _{message.text[:50]}_")
        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
