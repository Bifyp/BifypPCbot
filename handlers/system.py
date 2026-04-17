# handlers/system.py — система + Wake-on-LAN + автозагрузка + Wi-Fi

import psutil, platform, subprocess, datetime, logging, socket, struct, winreg
import telebot
from config import WOL_MAC


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("📊 Состояние",     callback_data="sys_info"),
        telebot.types.InlineKeyboardButton("🌡 Температура",   callback_data="sys_temp"),
        telebot.types.InlineKeyboardButton("📶 Wi-Fi сети",    callback_data="sys_wifi"),
        telebot.types.InlineKeyboardButton("🚀 Автозагрузка",  callback_data="sys_startup"),
        telebot.types.InlineKeyboardButton("🔄 Перезагрузка",  callback_data="sys_reboot"),
        telebot.types.InlineKeyboardButton("⏻ Выключение",     callback_data="sys_shutdown"),
        telebot.types.InlineKeyboardButton("💤 Сон",           callback_data="sys_sleep"),
        telebot.types.InlineKeyboardButton("🔒 Блокировка",    callback_data="sys_lock"),
        telebot.types.InlineKeyboardButton("📡 Wake-on-LAN",   callback_data="sys_wol"),
    )
    bot.send_message(message.chat.id, "⚙️ *Система:*", reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("sys_"))
    def handle(call):
        if not is_allowed(call): return
        data = call.data
        cid  = call.message.chat.id

        if data == "sys_info":
            bot.answer_callback_query(call.id)
            _send_sysinfo(bot, cid)

        elif data == "sys_temp":
            bot.answer_callback_query(call.id)
            _send_temps(bot, cid)

        elif data == "sys_wifi":
            bot.answer_callback_query(call.id)
            _send_wifi(bot, cid)

        elif data == "sys_startup":
            bot.answer_callback_query(call.id)
            _send_startup(bot, cid)

        elif data == "sys_wol":
            bot.answer_callback_query(call.id)
            try:
                _wake_on_lan(WOL_MAC)
                bot.send_message(cid, f"📡 Magic packet отправлен → `{WOL_MAC}`")
            except Exception as e:
                bot.send_message(cid, f"❌ WoL ошибка: {e}")

        elif data == "sys_sleep":
            bot.answer_callback_query(call.id)
            subprocess.run("rundll32.exe powrprof.dll,SetSuspendState 0,1,0", shell=True)
            bot.send_message(cid, "💤 Уходим в сон...")

        elif data == "sys_lock":
            bot.answer_callback_query(call.id)
            import ctypes; ctypes.windll.user32.LockWorkStation()
            bot.send_message(cid, "🔒 Экран заблокирован")

        elif data in ("sys_reboot","sys_shutdown"):
            bot.answer_callback_query(call.id)
            action = "перезагрузить" if "reboot" in data else "выключить"
            kb = telebot.types.InlineKeyboardMarkup()
            kb.row(
                telebot.types.InlineKeyboardButton("✅ Да", callback_data=f"sys_ok_{data}"),
                telebot.types.InlineKeyboardButton("❌ Нет", callback_data="sys_cancel"),
            )
            bot.send_message(cid, f"⚠️ Ты уверен, что хочешь {action} ПК?", reply_markup=kb)

        elif data.startswith("sys_ok_"):
            bot.answer_callback_query(call.id)
            if "reboot" in data:
                bot.send_message(cid, "🔄 Перезагружаю...")
                subprocess.run("shutdown /r /t 5", shell=True)
            else:
                bot.send_message(cid, "⏻ Выключаю через 5 сек...")
                subprocess.run("shutdown /s /t 5", shell=True)

        elif data == "sys_cancel":
            bot.answer_callback_query(call.id, "Отменено")
            bot.send_message(cid, "❌ Отменено")

        elif data.startswith("sys_startup_dis_"):
            bot.answer_callback_query(call.id)
            name = data.replace("sys_startup_dis_","")
            _disable_startup(bot, cid, name)


def _send_sysinfo(bot, cid):
    try:
        cpu   = psutil.cpu_percent(interval=1)
        ram   = psutil.virtual_memory()
        disk  = psutil.disk_usage("C:\\")
        boot  = datetime.datetime.fromtimestamp(psutil.boot_time())
        uptime = datetime.datetime.now() - boot
        net   = psutil.net_io_counters()
        text = (
            f"📊 *Состояние системы:*\n"
            f"🖥 CPU: `{cpu}%`\n"
            f"💾 RAM: `{ram.used//1024**2}MB / {ram.total//1024**2}MB` ({ram.percent}%)\n"
            f"💿 Диск C: `{disk.used//1024**3}GB / {disk.total//1024**3}GB` ({disk.percent}%)\n"
            f"🌐 Сеть ↑`{net.bytes_sent//1024**2}MB` ↓`{net.bytes_recv//1024**2}MB`\n"
            f"⏱ Uptime: `{str(uptime).split('.')[0]}`\n"
            f"🖥 ОС: `{platform.version()[:60]}`"
        )
        bot.send_message(cid, text)
    except Exception as e:
        bot.send_message(cid, f"❌ {e}")


def _send_temps(bot, cid):
    try:
        temps = psutil.sensors_temperatures()
        if not temps:
            bot.send_message(cid, "🌡 Данные температуры недоступны на Windows без OpenHardwareMonitor")
            return
        text = "🌡 *Температуры:*\n"
        for name, entries in temps.items():
            for e in entries:
                text += f"• {name}/{e.label}: `{e.current}°C`\n"
        bot.send_message(cid, text)
    except Exception as e:
        bot.send_message(cid, f"❌ {e}")


def _send_wifi(bot, cid):
    try:
        result = subprocess.run("netsh wlan show networks mode=bssid",
                                capture_output=True, text=True, shell=True, encoding="cp866")
        lines = result.stdout.strip().split("\n")
        networks = []
        current = {}
        for line in lines:
            line = line.strip()
            if line.startswith("SSID") and "BSSID" not in line:
                if current: networks.append(current)
                current = {"ssid": line.split(":",1)[-1].strip()}
            elif "Сигнал" in line or "Signal" in line:
                current["signal"] = line.split(":",1)[-1].strip()
            elif "Тип проверки" in line or "Authentication" in line:
                current["auth"] = line.split(":",1)[-1].strip()
        if current: networks.append(current)

        if not networks:
            bot.send_message(cid, "📶 Wi-Fi сети не найдены (или Wi-Fi выключен)")
            return
        text = "📶 *Доступные Wi-Fi сети:*\n"
        for n in networks[:12]:
            ssid   = n.get("ssid","?")
            signal = n.get("signal","?")
            auth   = n.get("auth","?")
            text += f"• `{ssid}` — {signal} ({auth})\n"
        bot.send_message(cid, text)
    except Exception as e:
        bot.send_message(cid, f"❌ {e}")


def _send_startup(bot, cid):
    try:
        items = []
        reg_paths = [
            (winreg.HKEY_CURRENT_USER,
             r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE,
             r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ]
        for hive, path in reg_paths:
            try:
                key = winreg.OpenKey(hive, path)
                i = 0
                while True:
                    try:
                        name, val, _ = winreg.EnumValue(key, i)
                        items.append({"name": name, "val": val})
                        i += 1
                    except OSError: break
            except Exception: pass

        if not items:
            bot.send_message(cid, "🚀 Автозагрузка пуста")
            return

        kb = telebot.types.InlineKeyboardMarkup(row_width=1)
        text = "🚀 *Автозагрузка Windows:*\n"
        for item in items[:15]:
            text += f"• `{item['name']}`\n"
            kb.add(telebot.types.InlineKeyboardButton(
                f"🗑 {item['name'][:35]}", callback_data=f"sys_startup_dis_{item['name'][:40]}"))
        bot.send_message(cid, text, reply_markup=kb)
    except Exception as e:
        bot.send_message(cid, f"❌ {e}")


def _disable_startup(bot, cid, name):
    try:
        for hive, path in [
            (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Run"),
            (winreg.HKEY_LOCAL_MACHINE, r"Software\Microsoft\Windows\CurrentVersion\Run"),
        ]:
            try:
                key = winreg.OpenKey(hive, path, 0, winreg.KEY_SET_VALUE)
                winreg.DeleteValue(key, name)
                bot.send_message(cid, f"✅ Удалено из автозагрузки: `{name}`")
                return
            except Exception: pass
        bot.send_message(cid, f"❌ Не найдено: `{name}`")
    except Exception as e:
        bot.send_message(cid, f"❌ {e}")


def _wake_on_lan(mac: str):
    mac_bytes = bytes.fromhex(mac.replace(":","").replace("-",""))
    magic = b"\xff" * 6 + mac_bytes * 16
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        s.sendto(magic, ("<broadcast>", 9))
