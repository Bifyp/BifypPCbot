# handlers/alerts.py — мониторинг + детект чужой активности

import psutil, os, time, threading, logging
import telebot
from config import ACTIVITY_DETECT, ACTIVITY_IDLE_SECONDS

_cfg = {
    "cpu":  85,
    "ram":  90,
    "disk": 95,
    "enabled": True,
}
_known_usb   = set()
_last_alerts = {}   # key -> timestamp
_last_bot_action = [time.time()]   # список чтобы мутировать из хендлеров


def touch_activity():
    """Вызывается из других хендлеров при каждом действии бота."""
    _last_bot_action[0] = time.time()


def register(bot, message):
    touch_activity()
    status = "✅ Включены" if _cfg["enabled"] else "❌ Выключены"
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton(
            "❌ Выключить" if _cfg["enabled"] else "✅ Включить",
            callback_data="alt_toggle"),
        telebot.types.InlineKeyboardButton("⚙️ Пороги", callback_data="alt_thresh"),
    )
    bot.send_message(message.chat.id,
        f"🔔 *Алерты*\nСтатус: {status}\n"
        f"CPU > `{_cfg['cpu']}%`\nRAM > `{_cfg['ram']}%`\nДиск > `{_cfg['disk']}%`\n"
        f"Детект активности: `{'вкл' if ACTIVITY_DETECT else 'выкл'}`",
        reply_markup=kb)


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in ("alt_toggle","alt_thresh"))
    def handle(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        if call.data == "alt_toggle":
            _cfg["enabled"] = not _cfg["enabled"]
            bot.send_message(call.message.chat.id,
                f"🔔 Алерты: {'✅ Включены' if _cfg['enabled'] else '❌ Выключены'}")
        elif call.data == "alt_thresh":
            msg = bot.send_message(call.message.chat.id,
                "⚙️ Введи пороги через пробел (CPU RAM DISK):\nПример: `80 85 90`")
            bot.register_next_step_handler(msg, set_thresh)

    def set_thresh(message):
        if not is_allowed(message): return
        try:
            p = list(map(int, message.text.strip().split()))
            _cfg["cpu"], _cfg["ram"], _cfg["disk"] = p[0], p[1], p[2]
            bot.send_message(message.chat.id,
                f"✅ CPU>`{p[0]}%` RAM>`{p[1]}%` Диск>`{p[2]}%`")
        except Exception:
            bot.send_message(message.chat.id, "❌ Формат: `80 85 90`")


def _cooldown(key, seconds=300):
    now = time.time()
    if now - _last_alerts.get(key, 0) > seconds:
        _last_alerts[key] = now
        return True
    return False


def start_monitoring(bot: telebot.TeleBot, user_ids: list):
    global _known_usb
    _known_usb = set(d.device for d in psutil.disk_partitions()
                     if "removable" in d.opts.lower())

    def notify(text):
        for uid in user_ids:
            try: bot.send_message(uid, text)
            except Exception: pass

    # ── Детект чужой активности ──────────────────────────────────────────────
    _prev_mouse = [None]

    def activity_monitor():
        import pyautogui
        while True:
            try:
                if ACTIVITY_DETECT:
                    idle = time.time() - _last_bot_action[0]
                    if idle > ACTIVITY_IDLE_SECONDS:
                        pos = pyautogui.position()
                        prev = _prev_mouse[0]
                        if prev and (abs(pos.x - prev[0]) > 5 or abs(pos.y - prev[1]) > 5):
                            if _cooldown("activity", 120):
                                notify(
                                    f"👀 *Обнаружена активность на ПК!*\n"
                                    f"Мышь двигается без команды бота.\n"
                                    f"Позиция: `{pos.x}, {pos.y}`")
                        _prev_mouse[0] = (pos.x, pos.y)
            except Exception as e:
                logging.debug(f"activity monitor: {e}")
            time.sleep(3)

    threading.Thread(target=activity_monitor, daemon=True).start()

    # ── Основной цикл ────────────────────────────────────────────────────────
    while True:
        try:
            if not _cfg["enabled"]:
                time.sleep(10); continue

            cpu = psutil.cpu_percent(interval=2)
            if cpu > _cfg["cpu"] and _cooldown("cpu"):
                notify(f"🔥 *Высокая нагрузка CPU!* `{cpu}%`")

            ram = psutil.virtual_memory().percent
            if ram > _cfg["ram"] and _cooldown("ram"):
                notify(f"💾 *Мало памяти!* RAM: `{ram}%`")

            try:
                disk = psutil.disk_usage("C:\\").percent
                if disk > _cfg["disk"] and _cooldown("disk", 1800):
                    notify(f"💿 *Диск C почти заполнен!* `{disk}%`")
            except Exception: pass

            # USB
            current = set(d.device for d in psutil.disk_partitions()
                          if "removable" in d.opts.lower())
            for dev in current - _known_usb:
                notify(f"🔌 *USB подключён:* `{dev}`")
            for dev in _known_usb - current:
                notify(f"🔌 *USB отключён:* `{dev}`")
            _known_usb = current

        except Exception as e:
            logging.error(f"monitoring: {e}")

        time.sleep(15)
