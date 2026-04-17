# handlers/network.py — информация о сети

import subprocess
import socket
import logging
import threading
import telebot

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("🌐 Внешний IP",    callback_data="net_extip"),
        telebot.types.InlineKeyboardButton("🏠 Локальный IP",  callback_data="net_localip"),
        telebot.types.InlineKeyboardButton("📶 Интерфейсы",    callback_data="net_ifaces"),
        telebot.types.InlineKeyboardButton("📊 Трафик",        callback_data="net_traffic"),
        telebot.types.InlineKeyboardButton("📡 Пинг хоста",   callback_data="net_ping"),
    )
    bot.send_message(message.chat.id, "🌐 *Сеть:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("net_"))
    def handle_net(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        data = call.data

        try:
            if data == "net_extip":
                def get_ext():
                    try:
                        result = subprocess.run(
                            "powershell (Invoke-WebRequest -Uri 'https://api.ipify.org').Content",
                            capture_output=True, text=True, shell=True, timeout=10)
                        ip = result.stdout.strip()
                        bot.send_message(call.message.chat.id, f"🌐 Внешний IP: `{ip}`")
                    except Exception as e:
                        bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")
                threading.Thread(target=get_ext, daemon=True).start()

            elif data == "net_localip":
                hostname = socket.gethostname()
                local_ip = socket.gethostbyname(hostname)
                bot.send_message(call.message.chat.id,
                                 f"🏠 Хост: `{hostname}`\nLAN IP: `{local_ip}`")

            elif data == "net_ifaces":
                if not HAS_PSUTIL:
                    bot.send_message(call.message.chat.id, "❌ psutil не установлен")
                    return
                addrs = psutil.net_if_addrs()
                text  = "📶 *Сетевые интерфейсы:*\n"
                for name, addr_list in list(addrs.items())[:8]:
                    for a in addr_list:
                        if a.family == socket.AF_INET:
                            text += f"• `{name}`: {a.address}\n"
                bot.send_message(call.message.chat.id, text)

            elif data == "net_traffic":
                if not HAS_PSUTIL:
                    bot.send_message(call.message.chat.id, "❌ psutil не установлен")
                    return
                stats = psutil.net_io_counters()
                sent  = stats.bytes_sent  // 1024**2
                recv  = stats.bytes_recv  // 1024**2
                bot.send_message(call.message.chat.id,
                                 f"📊 *Трафик с запуска:*\n"
                                 f"📤 Отправлено: `{sent} MB`\n"
                                 f"📥 Получено:   `{recv} MB`")

            elif data == "net_ping":
                msg = bot.send_message(call.message.chat.id,
                                       "📡 Введи хост для пинга (например: `8.8.8.8`):")
                bot.register_next_step_handler(msg, do_ping)

        except Exception as e:
            bot.send_message(call.message.chat.id, f"❌ Ошибка: {e}")

    def do_ping(message):
        if not is_allowed(message): return
        host = message.text.strip()
        def run_ping():
            try:
                result = subprocess.run(
                    f"ping -n 4 {host}", capture_output=True,
                    text=True, shell=True, timeout=15, encoding="cp866")
                out = result.stdout or result.stderr
                if len(out) > 3500: out = out[:3500] + "..."
                bot.send_message(message.chat.id, f"```\n{out}\n```")
            except Exception as e:
                bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
        threading.Thread(target=run_ping, daemon=True).start()
