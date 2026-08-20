# handlers/terminal.py

import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List

import telebot

BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_FILE = BASE_DIR / "terminal_history.json"
SHORTCUTS_FILE = BASE_DIR / "terminal_shortcuts.json"
MAX_HISTORY = 50
DEFAULT_TIMEOUT = 30
MAX_OUTPUT_MESSAGE = 3500
MAX_OUTPUT_FILE = 180_000

DANGEROUS_PATTERNS = [
    r"\brd\s+/s\s+/q\b", r"\brmdir\s+/s\s+/q\b", r"\bdel\s+/[a-z]*[sq][a-z]*\b",
    r"\bformat\b", r"\bdiskpart\b", r"\bbcdedit\b", r"\breg\s+delete\b",
    r"\bshutdown\b", r"\brestart-computer\b", r"\bstop-computer\b",
]

_command_history: Dict[int, List[str]] = {}
_user_shortcuts: Dict[int, Dict[str, str]] = {}
_sessions: Dict[int, "TerminalSession"] = {}
_sessions_lock = threading.Lock()


@dataclass
class TerminalSession:
    cwd: Path
    shell: str = "cmd"
    last_command: str = ""
    running: bool = False
    started_at: float = 0.0


def _default_shortcuts() -> Dict[str, str]:
    home = Path.home()
    return {
        "home": str(home),
        "desktop": str(home / "Desktop"),
        "downloads": str(home / "Downloads"),
        "documents": str(home / "Documents"),
        "pictures": str(home / "Pictures"),
        "bot": str(BASE_DIR),
        "temp": tempfile.gettempdir(),
        "c": "C:\\\\",
    }


def _shortcuts_for(user_id: int) -> Dict[str, str]:
    data = _default_shortcuts()
    data.update(_user_shortcuts.get(user_id, {}))
    return data


def _user_session(user_id: int) -> TerminalSession:
    with _sessions_lock:
        if user_id not in _sessions:
            _sessions[user_id] = TerminalSession(cwd=Path.home())
        return _sessions[user_id]


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        logging.warning(f"Failed to load {path.name}: {e}")
        return default


def _save_json(path: Path, data) -> None:
    try:
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as e:
        logging.warning(f"Failed to save {path.name}: {e}")


def _load_state() -> None:
    global _command_history, _user_shortcuts
    raw_history = _load_json(HISTORY_FILE, {})
    raw_shortcuts = _load_json(SHORTCUTS_FILE, {})
    _command_history = {int(k): list(v) for k, v in raw_history.items()}
    _user_shortcuts = {int(k): dict(v) for k, v in raw_shortcuts.items()}


def _save_history() -> None:
    _save_json(HISTORY_FILE, _command_history)


def _save_shortcuts() -> None:
    _save_json(SHORTCUTS_FILE, _user_shortcuts)


def _add_to_history(user_id: int, cmd: str) -> None:
    cmd = cmd.strip()
    if not cmd:
        return
    _command_history.setdefault(user_id, [])
    if not _command_history[user_id] or _command_history[user_id][-1] != cmd:
        _command_history[user_id].append(cmd)
    _command_history[user_id] = _command_history[user_id][-MAX_HISTORY:]
    _save_history()


def _get_history(user_id: int, limit: int = 10) -> List[str]:
    return _command_history.get(user_id, [])[-limit:]


def _escape_md(text: str) -> str:
    return text.replace("```", "'''")


def _short_path(path: Path) -> str:
    s = str(path)
    try:
        home = str(Path.home())
        if s.lower().startswith(home.lower()):
            return "~" + s[len(home):]
    except Exception:
        pass
    return s


def _split_first_arg(text: str) -> str:
    return text.split(" ", 1)[1].strip() if " " in text else ""


def _looks_dangerous(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(re.search(pattern, lowered) for pattern in DANGEROUS_PATTERNS)


def _build_shell_command(cmd: str, shell_name: str):
    if shell_name == "powershell":
        return ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", cmd]
    return ["cmd", "/d", "/s", "/c", cmd]


def _decode_output(data: bytes) -> str:
    if not data:
        return ""
    for enc in ("utf-8", "cp866", "cp1251"):
        try:
            return data.decode(enc)
        except UnicodeDecodeError:
            pass
    return data.decode("utf-8", errors="replace")


def _resolve_path(text: str, session: TerminalSession, user_id: int) -> Path:
    value = text.strip().strip('"')
    shortcuts = _shortcuts_for(user_id)
    if value in shortcuts:
        value = shortcuts[value]
    elif value.startswith("@") and value[1:] in shortcuts:
        value = shortcuts[value[1:]]
    elif value.startswith("~"):
        value = str(Path.home()) + value[1:]
    p = Path(value) if os.path.isabs(value) else session.cwd / value
    return p.resolve()


def _format_help() -> str:
    return (
        "💻 *Удобный терминал*\n\n"
        "Главное: больше не нужно каждый раз писать длинный путь.\n"
        "Один раз сделай `cd downloads`, `cd desktop`, `cd bot` или сохрани свою папку.\n\n"
        "*Папки и сокращения:*\n"
        "`cd downloads` — перейти в Загрузки\n"
        "`cd desktop` — перейти на Рабочий стол\n"
        "`cd bot` — папка проекта\n"
        "`ls` / `dir` — список файлов\n"
        "`up` — папка выше\n"
        "`roots` — список быстрых папок\n"
        "`save work` — сохранить текущую папку как `work`\n"
        "`go work` или `cd work` — перейти в неё\n"
        "`delroot work` — удалить своё сокращение\n\n"
        "*Остальное:*\n"
        "`shell cmd` / `shell powershell` — выбрать оболочку\n"
        "`history` — история\n"
        "`pwd` — текущая папка\n"
        "`/cmd команда` — выполнить команду сразу\n"
    )


def _main_keyboard() -> telebot.types.InlineKeyboardMarkup:
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💻 Ввести", callback_data="term_input"),
        telebot.types.InlineKeyboardButton("📂 Быстрые папки", callback_data="term_roots"),
        telebot.types.InlineKeyboardButton("⬆️ Выше", callback_data="term_up"),
        telebot.types.InlineKeyboardButton("📋 dir", callback_data="term_quick_dir"),
        telebot.types.InlineKeyboardButton("💾 Запомнить тут", callback_data="term_save_here"),
        telebot.types.InlineKeyboardButton("📜 История", callback_data="term_history"),
        telebot.types.InlineKeyboardButton("🧰 Shell", callback_data="term_shell"),
        telebot.types.InlineKeyboardButton("❓ Помощь", callback_data="term_help"),
    )
    return kb


def _shell_keyboard() -> telebot.types.InlineKeyboardMarkup:
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("cmd", callback_data="term_set_shell_cmd"),
        telebot.types.InlineKeyboardButton("PowerShell", callback_data="term_set_shell_powershell"),
    )
    return kb


def _roots_keyboard(user_id: int) -> telebot.types.InlineKeyboardMarkup:
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    shortcuts = _shortcuts_for(user_id)
    for name in shortcuts:
        kb.add(telebot.types.InlineKeyboardButton(f"📁 {name}", callback_data=f"term_go_{name}"))
    return kb


_load_state()


def register(bot, message):
    user_id = message.from_user.id
    session = _user_session(user_id)
    bot.send_message(
        message.chat.id,
        f"💻 *Терминал*\nShell: `{session.shell}`\nПапка: `{_short_path(session.cwd)}`\n\n"
        f"Подсказка: нажми *Быстрые папки* или напиши `cd downloads`.",
        reply_markup=_main_keyboard(),
    )


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("term_"))
    def handle_terminal(call):
        if not is_allowed(call):
            return
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        session = _user_session(user_id)
        data = call.data

        if data == "term_input":
            msg = bot.send_message(call.message.chat.id, f"💻 Команда\n`{session.shell}` · `{_short_path(session.cwd)}`")
            bot.register_next_step_handler(msg, run_cmd)
        elif data == "term_history":
            _send_history(bot, call.message.chat.id, user_id)
        elif data == "term_roots":
            _send_roots(bot, call.message.chat.id, user_id)
        elif data == "term_up":
            session.cwd = session.cwd.parent
            bot.send_message(call.message.chat.id, f"📂 `{_short_path(session.cwd)}`", reply_markup=_main_keyboard())
        elif data == "term_quick_dir":
            _execute_async(bot, call.message.chat.id, "dir", user_id)
        elif data == "term_save_here":
            msg = bot.send_message(call.message.chat.id, "💾 Как назвать эту папку? Например: `work`")
            bot.register_next_step_handler(msg, save_here)
        elif data == "term_clear_history":
            _command_history[user_id] = []
            _save_history()
            bot.send_message(call.message.chat.id, "🗑 История команд очищена")
        elif data == "term_pwd":
            bot.send_message(call.message.chat.id, f"📂 `{_short_path(session.cwd)}`")
        elif data == "term_help":
            bot.send_message(call.message.chat.id, _format_help())
        elif data == "term_shell":
            bot.send_message(call.message.chat.id, "🧰 Выбери оболочку:", reply_markup=_shell_keyboard())
        elif data.startswith("term_set_shell_"):
            shell = data.replace("term_set_shell_", "")
            session.shell = "powershell" if shell == "powershell" else "cmd"
            bot.send_message(call.message.chat.id, f"✅ Shell: `{session.shell}`")
        elif data.startswith("term_run_"):
            index = int(data.replace("term_run_", ""))
            history = _get_history(user_id, limit=MAX_HISTORY)
            if 0 <= index < len(history):
                _execute_async(bot, call.message.chat.id, history[index], user_id)
        elif data.startswith("term_go_"):
            name = data.replace("term_go_", "", 1)
            _change_dir(bot, call.message.chat.id, name, user_id)

    @bot.message_handler(commands=["cmd"])
    def cmd_cmd(message):
        if not is_allowed(message):
            return
        cmd = _split_first_arg(message.text or "")
        if not cmd:
            msg = bot.send_message(message.chat.id, "💻 Введи команду:")
            bot.register_next_step_handler(msg, run_cmd)
            return
        _execute_async(bot, message.chat.id, cmd, message.from_user.id)

    def run_cmd(message):
        if not is_allowed(message):
            return
        cmd = (message.text or "").strip()
        if not cmd:
            bot.send_message(message.chat.id, "❌ Пустая команда")
            return
        _execute_async(bot, message.chat.id, cmd, message.from_user.id)

    def save_here(message):
        if not is_allowed(message):
            return
        name = (message.text or "").strip().lower()
        if not re.fullmatch(r"[a-zA-Z0-9_-]{1,20}", name):
            bot.send_message(message.chat.id, "❌ Название: только буквы/цифры/_/-, до 20 символов")
            return
        session = _user_session(message.from_user.id)
        _user_shortcuts.setdefault(message.from_user.id, {})[name] = str(session.cwd)
        _save_shortcuts()
        bot.send_message(message.chat.id, f"✅ Сохранил: `{name}` → `{_short_path(session.cwd)}`")


def _send_history(bot, chat_id: int, user_id: int) -> None:
    history = _get_history(user_id, limit=10)
    if not history:
        bot.send_message(chat_id, "📜 История команд пуста")
        return
    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    for i, cmd in enumerate(reversed(history), 1):
        label = cmd if len(cmd) <= 45 else cmd[:42] + "..."
        kb.add(telebot.types.InlineKeyboardButton(f"{i}. {label}", callback_data=f"term_run_{len(history) - i}"))
    bot.send_message(chat_id, "📜 *История команд:*", reply_markup=kb)


def _send_roots(bot, chat_id: int, user_id: int) -> None:
    lines = ["📂 *Быстрые папки:*"]
    for name, path in _shortcuts_for(user_id).items():
        lines.append(f"`{name}` → `{_short_path(Path(path))}`")
    lines.append("\nНапиши `cd имя` или нажми кнопку ниже.")
    bot.send_message(chat_id, "\n".join(lines), reply_markup=_roots_keyboard(user_id))


def _change_dir(bot, chat_id: int, target: str, user_id: int) -> None:
    session = _user_session(user_id)
    new_cwd = _resolve_path(target, session, user_id)
    if not new_cwd.exists() or not new_cwd.is_dir():
        bot.send_message(chat_id, f"❌ Папка не найдена:\n`{_escape_md(str(new_cwd))}`")
        return
    session.cwd = new_cwd
    bot.send_message(chat_id, f"📂 `{_short_path(session.cwd)}`", reply_markup=_main_keyboard())


def _execute_async(bot, chat_id: int, cmd: str, user_id: int) -> None:
    session = _user_session(user_id)
    if session.running:
        elapsed = int(time.time() - session.started_at)
        bot.send_message(chat_id, f"⏳ Уже выполняется: `{_escape_md(session.last_command)}` ({elapsed}с)")
        return
    threading.Thread(target=_execute, args=(bot, chat_id, cmd, user_id), daemon=True, name=f"terminal-{user_id}").start()


def _execute(bot, chat_id: int, raw_cmd: str, user_id: int) -> None:
    session = _user_session(user_id)
    cmd = raw_cmd.strip()
    timeout = DEFAULT_TIMEOUT
    session.running = True
    session.started_at = time.time()
    session.last_command = cmd

    try:
        lowered = cmd.lower().strip()
        if lowered in ("help", "/help", "?"):
            bot.send_message(chat_id, _format_help())
            return
        if lowered in ("pwd", "cd"):
            bot.send_message(chat_id, f"📂 `{_short_path(session.cwd)}`")
            return
        if lowered in ("ls", "ll"):
            cmd = "dir"
            lowered = "dir"
        if lowered in ("up", ".."):
            session.cwd = session.cwd.parent
            bot.send_message(chat_id, f"📂 `{_short_path(session.cwd)}`", reply_markup=_main_keyboard())
            return
        if lowered in ("roots", "папки", "shortcuts"):
            _send_roots(bot, chat_id, user_id)
            return
        if lowered in ("history", "история"):
            _send_history(bot, chat_id, user_id)
            return
        if lowered in ("clear", "очистить"):
            _command_history[user_id] = []
            _save_history()
            bot.send_message(chat_id, "🗑 История команд очищена")
            return
        if lowered.startswith("save "):
            name = lowered.split(None, 1)[1].strip()
            if not re.fullmatch(r"[a-zA-Z0-9_-]{1,20}", name):
                bot.send_message(chat_id, "❌ Название: только буквы/цифры/_/-, до 20 символов")
                return
            _user_shortcuts.setdefault(user_id, {})[name] = str(session.cwd)
            _save_shortcuts()
            bot.send_message(chat_id, f"✅ Сохранил: `{name}` → `{_short_path(session.cwd)}`")
            return
        if lowered.startswith("delroot "):
            name = lowered.split(None, 1)[1].strip()
            if name in _user_shortcuts.get(user_id, {}):
                del _user_shortcuts[user_id][name]
                _save_shortcuts()
                bot.send_message(chat_id, f"🗑 Удалил сокращение `{name}`")
            else:
                bot.send_message(chat_id, f"❌ Нет своего сокращения `{name}`")
            return
        if lowered.startswith("go "):
            _change_dir(bot, chat_id, cmd.split(None, 1)[1], user_id)
            return
        if lowered.startswith("cd "):
            _change_dir(bot, chat_id, cmd[3:].strip(), user_id)
            return
        if lowered.startswith("shell "):
            value = lowered.split(None, 1)[1].strip()
            if value in ("cmd", "powershell"):
                session.shell = value
                bot.send_message(chat_id, f"✅ Shell: `{session.shell}`")
            else:
                bot.send_message(chat_id, "❌ Доступно: `shell cmd` или `shell powershell`")
            return
        if lowered.startswith("timeout "):
            try:
                timeout = max(1, min(300, int(lowered.split(None, 1)[1])))
                bot.send_message(chat_id, f"✅ Таймаут следующей команды: `{timeout}` сек")
            except ValueError:
                bot.send_message(chat_id, "❌ Пример: `timeout 60`")
            return

        force = False
        if cmd.startswith("!force "):
            force = True
            cmd = cmd[len("!force "):].strip()
        if _looks_dangerous(cmd) and not force:
            bot.send_message(chat_id, "⚠️ Команда выглядит опасной. Если уверен — отправь с `!force`.")
            return

        _add_to_history(user_id, raw_cmd)
        bot.send_message(chat_id, f"▶️ `{_escape_md(cmd)}`\n📂 `{_short_path(session.cwd)}`")
        started = time.time()
        proc = subprocess.run(_build_shell_command(cmd, session.shell), cwd=str(session.cwd), capture_output=True, timeout=timeout, shell=False)
        elapsed = time.time() - started
        output = (_decode_output(proc.stdout) + _decode_output(proc.stderr)).strip() or "(нет вывода)"
        _send_output(bot, chat_id, f"✅ Код: `{proc.returncode}` · ⏱ `{elapsed:.1f}с`\n", output)
        logging.info("Terminal command executed by %s: %s", user_id, cmd[:200])
    except subprocess.TimeoutExpired:
        bot.send_message(chat_id, f"⏱ Таймаут: команда выполнялась дольше `{timeout}` сек")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка выполнения:\n`{_escape_md(str(e))}`")
        logging.exception("Terminal error executing: %s", cmd)
    finally:
        session.running = False


def _send_output(bot, chat_id: int, header: str, output: str) -> None:
    safe_output = _escape_md(output)
    if len(safe_output) <= MAX_OUTPUT_MESSAGE:
        bot.send_message(chat_id, f"{header}```\n{safe_output}\n```", reply_markup=_main_keyboard())
        return
    preview = safe_output[:MAX_OUTPUT_MESSAGE] + "\n...(полный вывод файлом)"
    bot.send_message(chat_id, f"{header}```\n{preview}\n```", reply_markup=_main_keyboard())
    file_output = output[:MAX_OUTPUT_FILE]
    if len(output) > MAX_OUTPUT_FILE:
        file_output += "\n...(файл обрезан)"
    temp_name = None
    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(file_output)
            temp_name = f.name
        with open(temp_name, "rb") as doc:
            bot.send_document(chat_id, doc, caption="📄 Полный вывод команды")
    except Exception:
        logging.exception("Failed to send terminal output file")
    finally:
        if temp_name:
            try:
                os.remove(temp_name)
            except Exception:
                pass
