# handlers/screenshot.py — скриншоты + запись экрана + живой мониторинг

import mss, io, logging, time, threading, os, tempfile, hashlib
import telebot
from PIL import Image, ImageDraw

_monitor_threads = {}   # chat_id -> threading.Event (stop)

# Кеш скриншотов
_screenshot_cache = {}  # hash -> (timestamp, image_bytes)
_cache_ttl = 5  # секунды
_cache_lock = threading.Lock()

def _get_screen_hash(img_bytes):
    """Вычисляет хеш изображения для кеширования"""
    return hashlib.md5(img_bytes[:1000]).hexdigest()  # Используем первые 1000 байт

def _get_cached_screenshot(with_cursor=False, region=None):
    """Получает скриншот из кеша или создаёт новый"""
    cache_key = f"{with_cursor}_{region}"

    with _cache_lock:
        if cache_key in _screenshot_cache:
            timestamp, img_bytes = _screenshot_cache[cache_key]
            # Проверяем TTL
            if time.time() - timestamp < _cache_ttl:
                logging.debug(f"Screenshot cache hit: {cache_key}")
                buf = io.BytesIO(img_bytes)
                buf.seek(0)
                return buf

    # Создаём новый скриншот
    buf = _take(with_cursor, region)
    img_bytes = buf.getvalue()

    # Сохраняем в кеш
    with _cache_lock:
        _screenshot_cache[cache_key] = (time.time(), img_bytes)

        # Очищаем старые записи (больше 10)
        if len(_screenshot_cache) > 10:
            oldest_key = min(_screenshot_cache.keys(),
                           key=lambda k: _screenshot_cache[k][0])
            del _screenshot_cache[oldest_key]

    buf.seek(0)
    return buf


def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("📸 Весь экран",      callback_data="scr_full"),
        telebot.types.InlineKeyboardButton("🖱 С курсором",      callback_data="scr_cursor"),
        telebot.types.InlineKeyboardButton("✂️ Область",         callback_data="scr_area"),
        telebot.types.InlineKeyboardButton("🎥 Записать видео",  callback_data="scr_rec"),
        telebot.types.InlineKeyboardButton("👁 Мониторинг вкл",  callback_data="scr_mon_start"),
        telebot.types.InlineKeyboardButton("⏹ Мониторинг стоп", callback_data="scr_mon_stop"),
    )
    bot.send_message(message.chat.id, "📸 *Скриншот и запись:*", reply_markup=kb)


def _take(with_cursor=False, region=None, optimize=True):
    with mss.mss() as sct:
        mon = region if region else sct.monitors[1]
        img_raw = sct.grab(mon)
        pil = Image.frombytes("RGB", img_raw.size, img_raw.bgra, "raw", "BGRX")

    if with_cursor:
        try:
            import pyautogui
            cx, cy = pyautogui.position()
            d = ImageDraw.Draw(pil)
            r = 8
            d.ellipse([cx-r, cy-r, cx+r, cy+r], outline="red", width=3)
            d.line([cx-14, cy, cx+14, cy], fill="red", width=2)
            d.line([cx, cy-14, cx, cy+14], fill="red", width=2)
        except Exception:
            pass

    buf = io.BytesIO()

    # Оптимизация: используем JPEG для больших изображений
    if optimize and pil.size[0] * pil.size[1] > 1920 * 1080:
        pil.save(buf, format="JPEG", quality=85, optimize=True)
    else:
        pil.save(buf, format="PNG", optimize=True)

    buf.seek(0)
    return buf


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in (
        "scr_full","scr_cursor","scr_area","scr_rec","scr_mon_start","scr_mon_stop"))
    def handle(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)
        cid = call.message.chat.id
        data = call.data

        if data == "scr_full":
            try:
                bot.send_photo(cid, _get_cached_screenshot(), caption="📸 Скриншот")
                logging.info("Screenshot taken (full)")
            except Exception as e:
                bot.send_message(cid, f"❌ {e}")
                logging.exception("Screenshot error (full)")

        elif data == "scr_cursor":
            try:
                bot.send_photo(cid, _get_cached_screenshot(with_cursor=True), caption="📸 С курсором")
                logging.info("Screenshot taken (with cursor)")
            except Exception as e:
                bot.send_message(cid, f"❌ {e}")
                logging.exception("Screenshot error (cursor)")

        elif data == "scr_area":
            msg = bot.send_message(cid,
                "✂️ Введи координаты области: `x1 y1 x2 y2`\nПример: `0 0 1280 720`")
            bot.register_next_step_handler(msg, lambda m: _area_shot(bot, m, is_allowed))

        elif data == "scr_rec":
            msg = bot.send_message(cid,
                "🎥 Сколько секунд записывать? (1-30)")
            bot.register_next_step_handler(msg, lambda m: _record(bot, m, is_allowed))

        elif data == "scr_mon_start":
            if cid in _monitor_threads:
                bot.send_message(cid, "⚠️ Мониторинг уже запущен")
                return
            msg2 = bot.send_message(cid, "👁 Интервал (секунд, например `10`):")
            bot.register_next_step_handler(msg2, lambda m: _start_monitor(bot, m, is_allowed))

        elif data == "scr_mon_stop":
            if cid in _monitor_threads:
                _monitor_threads[cid].set()
                del _monitor_threads[cid]
                bot.send_message(cid, "⏹ Мониторинг остановлен")
            else:
                bot.send_message(cid, "⚠️ Мониторинг не запущен")


def _area_shot(bot, message, is_allowed):
    if not is_allowed(message): return
    try:
        parts = list(map(int, message.text.strip().split()))
        x1,y1,x2,y2 = parts
        region = {"left":x1,"top":y1,"width":x2-x1,"height":y2-y1}
        bot.send_photo(message.chat.id, _take(region=region),
                       caption=f"✂️ Область {x1},{y1}→{x2},{y2}")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Ошибка: {e}\nФормат: `x1 y1 x2 y2`")


def _record(bot, message, is_allowed):
    if not is_allowed(message): return
    cid = message.chat.id
    try:
        secs = max(1, min(30, int(message.text.strip())))
    except ValueError:
        bot.send_message(cid, "❌ Введи число от 1 до 30")
        return

    bot.send_message(cid, f"🎥 Записываю {secs} сек...")

    def do_rec():
        tmp = None
        tmp_compressed = None
        out = None
        try:
            tmp = tempfile.mktemp(suffix=".mp4")
            with mss.mss() as sct:
                mon = sct.monitors[1]
                w, h = mon["width"], mon["height"]

                # Уменьшаем разрешение для больших экранов
                scale = 1.0
                if w > 1920 or h > 1080:
                    scale = min(1920 / w, 1080 / h)
                    w = int(w * scale)
                    h = int(h * scale)

                import cv2
                import numpy as np

                # Используем H264 для лучшего сжатия
                fourcc = cv2.VideoWriter_fourcc(*"avc1")
                out = cv2.VideoWriter(tmp, fourcc, 10, (w, h))

                if not out.isOpened():
                    # Fallback на mp4v
                    fourcc = cv2.VideoWriter_fourcc(*"mp4v")
                    out = cv2.VideoWriter(tmp, fourcc, 10, (w, h))

                if not out.isOpened():
                    raise RuntimeError("Не удалось инициализировать VideoWriter")

                t0 = time.time()
                frame_count = 0
                while time.time() - t0 < secs:
                    frame = sct.grab(mon)
                    img = cv2.cvtColor(np.array(frame), cv2.COLOR_BGRA2BGR)

                    # Масштабируем если нужно
                    if scale < 1.0:
                        img = cv2.resize(img, (w, h), interpolation=cv2.INTER_LINEAR)

                    out.write(img)
                    frame_count += 1
                    time.sleep(0.1)

            if out is not None:
                out.release()

            file_size = os.path.getsize(tmp)
            logging.info(f"Video recorded: {frame_count} frames, {file_size // 1024}KB")

            # Если файл больше 40MB, пытаемся сжать
            if file_size > 40 * 1024 * 1024:
                bot.send_message(cid, "⚙️ Сжимаю видео...")
                tmp_compressed = tempfile.mktemp(suffix=".mp4")

                # Сжатие через ffmpeg если доступен
                try:
                    import subprocess
                    result = subprocess.run(
                        f'ffmpeg -i "{tmp}" -vcodec libx264 -crf 28 "{tmp_compressed}"',
                        shell=True, capture_output=True, timeout=60
                    )
                    if result.returncode == 0 and os.path.exists(tmp_compressed):
                        compressed_size = os.path.getsize(tmp_compressed)
                        if compressed_size < file_size:
                            os.remove(tmp)
                            tmp = tmp_compressed
                            tmp_compressed = None
                            logging.info(f"Video compressed: {compressed_size // 1024}KB")
                except Exception as e:
                    logging.warning(f"Video compression failed: {e}")

            with open(tmp, "rb") as f:
                bot.send_video(cid, f, caption=f"🎥 Запись {secs} сек ({os.path.getsize(tmp) // 1024}KB)")
            logging.info(f"Screen recording completed: {secs}s")

        except Exception as e:
            bot.send_message(cid, f"❌ Ошибка записи: {e}")
            logging.exception("Screen recording error")
        finally:
            if out is not None:
                out.release()
            if tmp and os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except Exception as e:
                    logging.warning(f"Failed to remove temp file {tmp}: {e}")
            if tmp_compressed and os.path.exists(tmp_compressed):
                try:
                    os.remove(tmp_compressed)
                except Exception:
                    pass

    threading.Thread(target=do_rec, daemon=True).start()


def _start_monitor(bot, message, is_allowed):
    if not is_allowed(message): return
    cid = message.chat.id
    try:
        interval = max(5, int(message.text.strip()))
    except ValueError:
        bot.send_message(cid, "❌ Введи число (секунды)")
        return

    stop_event = threading.Event()
    _monitor_threads[cid] = stop_event

    def run():
        bot.send_message(cid, f"👁 Мониторинг запущен, каждые {interval} сек. Нажми ⏹ для остановки")
        while not stop_event.is_set():
            try:
                bot.send_photo(cid, _take(), caption="👁 Авто-скриншот")
            except Exception as e:
                logging.exception("Monitor screenshot error")
                bot.send_message(cid, f"❌ Ошибка мониторинга: {e}")
                break
            stop_event.wait(interval)

        # Cleanup при остановке
        if cid in _monitor_threads:
            del _monitor_threads[cid]
            stop_event.wait(interval)

    threading.Thread(target=run, daemon=True).start()
