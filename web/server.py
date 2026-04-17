# web/server.py — Flask + Cloudflare Tunnel + MJPEG + WebSocket + Security

import subprocess, threading, logging, time, re, os, io, json, hashlib, hmac, secrets
from datetime import datetime, timedelta
from collections import defaultdict

import mss, cv2, numpy as np, pyautogui
from flask import (Flask, Response, request, jsonify,
                   render_template, redirect, session)
from flask_sock import Sock

from config import (FLASK_PORT, WEB_PANEL_PASSWORD, SESSION_LIFETIME_HOURS,
                    MAX_LOGIN_ATTEMPTS, BAN_DURATION_MINUTES, NOTIFY_ON_WEB_LOGIN)

app  = Flask(__name__, template_folder="templates")
sock = Sock(app)
app.secret_key = secrets.token_hex(32)
app.permanent_session_lifetime = timedelta(hours=SESSION_LIFETIME_HOURS)

_tunnel_url     = None
_tunnel_process = None
_bot_ref        = None          # устанавливается из bot.py
_allowed_ids    = []

# ── Thread safety ─────────────────────────────────────────────────────────────
_lock = threading.Lock()

# ── Rate limiting ─────────────────────────────────────────────────────────────
_login_attempts  = defaultdict(int)      # ip → count
_banned_until    = {}                    # ip → datetime

def _get_ip():
    return request.headers.get("X-Forwarded-For", request.remote_addr or "unknown").split(",")[0].strip()

def _is_banned(ip):
    with _lock:
        until = _banned_until.get(ip)
        if until and datetime.now() < until:
            return True
        if ip in _banned_until:
            del _banned_until[ip]
            _login_attempts[ip] = 0
        return False

def _record_fail(ip):
    with _lock:
        _login_attempts[ip] += 1
        if _login_attempts[ip] >= MAX_LOGIN_ATTEMPTS:
            _banned_until[ip] = datetime.now() + timedelta(minutes=BAN_DURATION_MINUTES)
            _log_security(f"IP забанен после {MAX_LOGIN_ATTEMPTS} попыток: {ip}")
            return True
        return False

def _log_security(msg):
    with open("security.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")
    logging.warning(f"[SECURITY] {msg}")

# ── Туннель ───────────────────────────────────────────────────────────────────
def get_tunnel_url():
    return _tunnel_url

def set_bot_ref(bot, allowed_ids):
    global _bot_ref, _allowed_ids
    _bot_ref      = bot
    _allowed_ids  = allowed_ids

def _notify_telegram(text):
    if _bot_ref:
        for uid in _allowed_ids:
            try:   _bot_ref.send_message(uid, text)
            except: pass

def _start_cloudflared():
    global _tunnel_url, _tunnel_process
    try:
        cf = os.path.join(os.path.dirname(__file__), "..", "cloudflared.exe")
        if not os.path.exists(cf):
            cf = "cloudflared"
        _tunnel_process = subprocess.Popen(
            [cf, "tunnel", "--url", f"http://localhost:{FLASK_PORT}"],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        for line in _tunnel_process.stdout:
            m = re.search(r"https://[a-z0-9\-]+\.trycloudflare\.com", line)
            if m:
                _tunnel_url = m.group(0)
                logging.info(f"Tunnel: {_tunnel_url}")
                break
    except Exception as e:
        logging.error(f"cloudflared error: {e}")

def start_web_server():
    threading.Thread(target=_start_cloudflared, daemon=True).start()
    app.run(host="127.0.0.1", port=FLASK_PORT, threaded=True, use_reloader=False)

# ── Auth ──────────────────────────────────────────────────────────────────────
def _require_auth():
    if not session.get("auth"):
        return False
    exp = session.get("expires")
    if exp and datetime.now() > datetime.fromisoformat(exp):
        session.clear()
        return False
    return True

@app.route("/login", methods=["GET", "POST"])
def login():
    ip = _get_ip()
    if _is_banned(ip):
        remaining = int((_banned_until[ip] - datetime.now()).total_seconds() // 60) + 1
        return render_template("login.html",
                               error=f"🚫 Слишком много попыток. Подожди {remaining} мин.")
    if request.method == "POST":
        pwd = request.form.get("password", "")
        if hmac.compare_digest(pwd, WEB_PANEL_PASSWORD):
            session.permanent = True
            session["auth"]    = True
            session["expires"] = (datetime.now() +
                                  timedelta(hours=SESSION_LIFETIME_HOURS)).isoformat()
            session["ip"]      = ip
            _login_attempts[ip] = 0
            _log_security(f"Успешный вход: {ip}")
            if NOTIFY_ON_WEB_LOGIN:
                _notify_telegram(f"🌐 *Вход в веб-панель*\nIP: `{ip}`\n"
                                 f"Время: {datetime.now().strftime('%H:%M:%S')}")
            return redirect("/")
        else:
            banned = _record_fail(ip)
            _log_security(f"Неверный пароль от {ip} (попытка {_login_attempts[ip]})")
            if banned:
                err = f"🚫 Забанен на {BAN_DURATION_MINUTES} мин."
            else:
                left = MAX_LOGIN_ATTEMPTS - _login_attempts[ip]
                err  = f"❌ Неверный пароль. Осталось попыток: {left}"
            return render_template("login.html", error=err)
    return render_template("login.html", error=None)

@app.route("/logout")
def logout():
    ip = _get_ip()
    _log_security(f"Выход: {ip}")
    session.clear()
    return redirect("/login")

# ── Главная ───────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    if not _require_auth():
        return redirect("/login")
    with mss.mss() as sct:
        mon = sct.monitors[1]
    return render_template("panel.html",
                           native_w=mon["width"], native_h=mon["height"])

# ── MJPEG stream ──────────────────────────────────────────────────────────────
stream_config = {"quality": 2, "interval": 1.0, "adaptive": True}
QUALITY_PRESETS = {
    1: {"jpeg_quality": 40, "scale": 0.5,  "interval": 1.5},
    2: {"jpeg_quality": 60, "scale": 1.0,  "interval": 1.0},
    3: {"jpeg_quality": 80, "scale": 1.0,  "interval": 0.8},
}

# Per-client frame hash для избежания race conditions
_client_frame_hashes = {}
_client_lock = threading.Lock()

# Адаптивное качество
_client_stats = {}  # client_id -> {"fps": [], "last_frame_time": time}

def _update_client_stats(client_id):
    """Обновляет статистику клиента для адаптивного качества"""
    now = time.time()
    if client_id not in _client_stats:
        _client_stats[client_id] = {"fps": [], "last_frame_time": now}
        return

    stats = _client_stats[client_id]
    if stats["last_frame_time"]:
        frame_time = now - stats["last_frame_time"]
        fps = 1.0 / frame_time if frame_time > 0 else 0
        stats["fps"].append(fps)

        # Храним последние 10 значений
        if len(stats["fps"]) > 10:
            stats["fps"] = stats["fps"][-10:]

    stats["last_frame_time"] = now

def _get_adaptive_quality(client_id):
    """Определяет оптимальное качество на основе FPS клиента"""
    if not stream_config.get("adaptive", False):
        return stream_config["quality"]

    if client_id not in _client_stats or not _client_stats[client_id]["fps"]:
        return stream_config["quality"]

    avg_fps = sum(_client_stats[client_id]["fps"]) / len(_client_stats[client_id]["fps"])

    # Если FPS низкий, снижаем качество
    if avg_fps < 5:
        return 1  # Эконом
    elif avg_fps < 15:
        return 2  # Стандарт
    else:
        return stream_config["quality"]  # Пользовательское

def _frames():
    client_id = id(threading.current_thread())
    with mss.mss() as sct:
        monitor = sct.monitors[1]
        while True:
            # Адаптивное качество
            quality = _get_adaptive_quality(client_id)
            preset = QUALITY_PRESETS[quality]
            interval = stream_config["interval"]

            try:
                img = np.array(sct.grab(monitor))
                img = cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
                if preset["scale"] < 1.0:
                    h, w = img.shape[:2]
                    img  = cv2.resize(img, (int(w*preset["scale"]),
                                           int(h*preset["scale"])),
                                      interpolation=cv2.INTER_LINEAR)
                # Дельта-сжатие — пропускаем почти одинаковые кадры (per-client)
                small     = cv2.resize(img, (160, 90))
                fhash     = hashlib.md5(small.tobytes()).hexdigest()

                with _client_lock:
                    prev_hash = _client_frame_hashes.get(client_id)
                    if fhash == prev_hash:
                        time.sleep(interval)
                        continue
                    _client_frame_hashes[client_id] = fhash

                param = [int(cv2.IMWRITE_JPEG_QUALITY), preset["jpeg_quality"]]
                _, buf = cv2.imencode(".jpg", img, param)

                # Обновляем статистику
                _update_client_stats(client_id)

                yield (b"--frame\r\nContent-Type: image/jpeg\r\n\r\n"
                       + buf.tobytes() + b"\r\n")
            except Exception as e:
                logging.exception("Frame generation error")
            finally:
                time.sleep(interval)

    # Cleanup при отключении клиента
    with _client_lock:
        _client_frame_hashes.pop(client_id, None)
        _client_stats.pop(client_id, None)

@app.route("/video_feed")
def video_feed():
    if not _require_auth():
        return Response("Unauthorized", status=401)
    return Response(_frames(), mimetype="multipart/x-mixed-replace; boundary=frame")

# ── System stats API ──────────────────────────────────────────────────────────
@app.route("/api/system_stats")
def system_stats():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401

    try:
        import psutil

        # CPU
        cpu_percent = psutil.cpu_percent(interval=0.1)
        cpu_count = psutil.cpu_count()

        # RAM
        mem = psutil.virtual_memory()
        ram_percent = mem.percent
        ram_used = mem.used // (1024 ** 3)  # GB
        ram_total = mem.total // (1024 ** 3)  # GB

        # Disk
        disk = psutil.disk_usage('/')
        disk_percent = disk.percent
        disk_used = disk.used // (1024 ** 3)  # GB
        disk_total = disk.total // (1024 ** 3)  # GB

        # Network
        net = psutil.net_io_counters()
        net_sent = net.bytes_sent // (1024 ** 2)  # MB
        net_recv = net.bytes_recv // (1024 ** 2)  # MB

        return jsonify({
            "cpu": {
                "percent": cpu_percent,
                "count": cpu_count
            },
            "ram": {
                "percent": ram_percent,
                "used": ram_used,
                "total": ram_total
            },
            "disk": {
                "percent": disk_percent,
                "used": disk_used,
                "total": disk_total
            },
            "network": {
                "sent": net_sent,
                "recv": net_recv
            }
        })
    except Exception as e:
        logging.exception("System stats error")
        return jsonify({"error": str(e)}), 500

# ── Clipboard sync API ────────────────────────────────────────────────────────
@app.route("/api/clipboard", methods=["GET", "POST"])
def clipboard_sync():
    if not _require_auth():
        return jsonify({"error": "unauthorized"}), 401

    try:
        import pyperclip

        if request.method == "GET":
            # Получить содержимое буфера обмена
            text = pyperclip.paste()
            return jsonify({"text": text})

        elif request.method == "POST":
            # Установить содержимое буфера обмена
            data = request.json or {}
            text = data.get("text", "")
            pyperclip.copy(text)
            return jsonify({"ok": True})

    except Exception as e:
        logging.exception("Clipboard sync error")
        return jsonify({"error": str(e)}), 500

# ── WebSocket мышь (низкая задержка) ──────────────────────────────────────────
@sock.route("/ws/mouse")
def ws_mouse(ws):
    if not session.get("auth"):
        ws.close()
        return
    while True:
        try:
            raw = ws.receive(timeout=30)
            if raw is None:
                break
            if raw == "ping":
                ws.send("pong")
                continue
            data = json.loads(raw)
            t = data.get("t")
            if t == "move":
                pyautogui.moveTo(int(data["x"]), int(data["y"]))
            elif t == "click":
                btn = data.get("b", "left")
                if data.get("d"):
                    pyautogui.doubleClick(button=btn)
                else:
                    pyautogui.click(button=btn)
            elif t == "scroll":
                pyautogui.scroll(int(data.get("c", 3)))
            elif t == "keydown":
                pyautogui.keyDown(data.get("k", ""))
            elif t == "keyup":
                pyautogui.keyUp(data.get("k", ""))
        except Exception as e:
            logging.exception("WebSocket mouse error")
            break

# ── REST API (качество, ввод) ─────────────────────────────────────────────────
def _auth_json():
    if not _require_auth():
        return False
    return True

@app.route("/set_quality", methods=["POST"])
def set_quality():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    q = int((request.json or {}).get("quality", 2))
    if q in QUALITY_PRESETS:
        stream_config["quality"]  = q
        stream_config["interval"] = QUALITY_PRESETS[q]["interval"]
    return jsonify({"ok": True})

@app.route("/set_interval", methods=["POST"])
def set_interval():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    iv = float((request.json or {}).get("interval", 1.0))
    stream_config["interval"] = max(0.3, min(5.0, iv))
    return jsonify({"ok": True})

@app.route("/mouse_move", methods=["POST"])
def mouse_move():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    d = request.json or {}
    try:
        pyautogui.moveTo(int(d["x"]), int(d["y"]))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/mouse_click", methods=["POST"])
def mouse_click():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    d = request.json or {}
    try:
        if d.get("double"): pyautogui.doubleClick(button=d.get("button","left"))
        else:               pyautogui.click(button=d.get("button","left"))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/mouse_scroll", methods=["POST"])
def mouse_scroll():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    try:
        pyautogui.scroll(int((request.json or {}).get("clicks", 3)))
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/key_type", methods=["POST"])
def key_type():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    text = (request.json or {}).get("text", "")
    try:
        # Фикс кириллицы: через буфер обмена
        import pyperclip
        pyperclip.copy(text)
        pyautogui.hotkey("ctrl", "v")
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/key_press", methods=["POST"])
def key_press():
    if not _auth_json(): return jsonify({"error":"unauthorized"}), 401
    key = (request.json or {}).get("key", "")
    try:
        if key: pyautogui.press(key)
        return jsonify({"ok": True})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ── Файловый менеджер ─────────────────────────────────────────────────────────
@app.route("/api/files/list", methods=["POST"])
def files_list():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.json or {}
        path = data.get("path", os.path.expanduser("~"))

        if not os.path.exists(path):
            return jsonify({"error": "Path not found"}), 404

        items = []
        for name in os.listdir(path):
            full_path = os.path.join(path, name)
            try:
                stat = os.stat(full_path)
                items.append({
                    "name": name,
                    "path": full_path,
                    "is_dir": os.path.isdir(full_path),
                    "size": stat.st_size if not os.path.isdir(full_path) else 0,
                    "modified": datetime.fromtimestamp(stat.st_mtime).isoformat()
                })
            except Exception:
                pass

        items.sort(key=lambda x: (not x["is_dir"], x["name"].lower()))

        parent = os.path.dirname(path) if path != os.path.dirname(path) else None

        return jsonify({
            "path": path,
            "parent": parent,
            "items": items
        })
    except Exception as e:
        logging.exception("Files list error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/download", methods=["POST"])
def files_download():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        from flask import send_file
        data = request.json or {}
        path = data.get("path", "")

        if not os.path.exists(path) or not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404

        return send_file(path, as_attachment=True, download_name=os.path.basename(path))
    except Exception as e:
        logging.exception("File download error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/upload", methods=["POST"])
def files_upload():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        if "file" not in request.files:
            return jsonify({"error": "No file"}), 400

        file = request.files["file"]
        path = request.form.get("path", os.path.expanduser("~"))

        if not os.path.exists(path) or not os.path.isdir(path):
            return jsonify({"error": "Invalid path"}), 400

        # Безопасное имя файла
        from werkzeug.utils import secure_filename
        safe_filename = secure_filename(file.filename)

        if not safe_filename:
            return jsonify({"error": "Invalid filename"}), 400

        filepath = os.path.join(path, safe_filename)

        # Проверка размера файла (макс 100MB)
        file.seek(0, os.SEEK_END)
        file_size = file.tell()
        file.seek(0)

        if file_size > 100 * 1024 * 1024:
            return jsonify({"error": "File too large (max 100MB)"}), 400

        file.save(filepath)

        logging.info(f"File uploaded: {filepath}")
        return jsonify({"ok": True, "path": filepath})
    except Exception as e:
        logging.exception("File upload error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/delete", methods=["POST"])
def files_delete():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.json or {}
        path = data.get("path", "")

        if not os.path.exists(path):
            return jsonify({"error": "Path not found"}), 404

        if os.path.isfile(path):
            os.remove(path)
        elif os.path.isdir(path):
            import shutil
            shutil.rmtree(path)

        logging.info(f"Deleted: {path}")
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("File delete error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/files/create_folder", methods=["POST"])
def files_create_folder():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.json or {}
        path = data.get("path", "")
        name = data.get("name", "New Folder")

        if not os.path.exists(path) or not os.path.isdir(path):
            return jsonify({"error": "Invalid path"}), 400

        new_path = os.path.join(path, name)
        os.makedirs(new_path, exist_ok=True)

        logging.info(f"Folder created: {new_path}")
        return jsonify({"ok": True, "path": new_path})
    except Exception as e:
        logging.exception("Create folder error")
        return jsonify({"error": str(e)}), 500

# ── Текстовый редактор ────────────────────────────────────────────────────────
@app.route("/api/editor/read", methods=["POST"])
def editor_read():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.json or {}
        path = data.get("path", "")

        if not os.path.exists(path) or not os.path.isfile(path):
            return jsonify({"error": "File not found"}), 404

        # Проверка размера файла (макс 1MB)
        if os.path.getsize(path) > 1024 * 1024:
            return jsonify({"error": "File too large (max 1MB)"}), 400

        with open(path, "r", encoding="utf-8", errors="replace") as f:
            content = f.read()

        return jsonify({"content": content, "path": path})
    except Exception as e:
        logging.exception("Editor read error")
        return jsonify({"error": str(e)}), 500

@app.route("/api/editor/save", methods=["POST"])
def editor_save():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    try:
        data = request.json or {}
        path = data.get("path", "")
        content = data.get("content", "")

        if not path:
            return jsonify({"error": "No path"}), 400

        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logging.info(f"File saved: {path}")
        return jsonify({"ok": True})
    except Exception as e:
        logging.exception("Editor save error")
        return jsonify({"error": str(e)}), 500

# ── Статус безопасности ───────────────────────────────────────────────────────
@app.route("/api/security_status")
def security_status():
    if not _require_auth():
        return jsonify({"error":"unauthorized"}), 401
    banned = {ip: v.isoformat() for ip, v in _banned_until.items()
              if datetime.now() < v}
    return jsonify({"banned_ips": banned,
                    "session_ip": session.get("ip"),
                    "expires":    session.get("expires")})
