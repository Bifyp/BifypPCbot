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
from typing import Dict, List, Optional

import telebot

# ──────────────────────────────────────────────────────────────────────────────
# Настройки
# ──────────────────────────────────────────────────────────────────────────────

BASE_DIR = Path(__file__).resolve().parents[1]
HISTORY_FILE = BASE_DIR / "terminal_history.json"
MAX_HISTORY = 50
DEFAULT_TIMEOUT = 30
MAX_OUTPUT_MESSAGE = 3500
MAX_OUTPUT_FILE = 180_000

# Команды, которые слишком опасно запускать случайно из Telegram.
# Если очень нужно — используй префикс: !force <команда>
DANGEROUS_PATTERNS = [
    r"\brd\s+/s\s+/q\b",
    r"\brmdir\s+/s\s+/q\b",
    r"\bdel\s+/[a-z]*[sq][a-z]*\b",
    r"\bformat\b",
    r"\bdiskpart\b",
    r"\bbcdedit\b",
    r"\breg\s+delete\b",
    r"\bshutdown\b",
    r"\brestart-computer\b",
    r"\bstop-computer\b",
]

_command_history: Dict[int, List[str]] = {}
_sessions: Dict[int, "TerminalSession"] = {}
_sessions_lock = threading.Lock()


@dataclass
class TerminalSession:
    cwd: Path
    shell: str = "cmd"
    last_command: str = ""
    running: bool = False
    started_at: float = 0.0


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции
# ──────────────────────────────────────────────────────────────────────────────


def _user_session(user_id: int) -> TerminalSession:
    with _sessions_lock:
        if user_id not in _sessions:
            _sessions[user_id] = TerminalSession(cwd=Path.home())
        return _sessions[user_id]


def _load_history() -> None:
    global _command_history
    if not HISTORY_FILE.exists():
        return
    try:
        raw = json.loads(HISTORY_FILE.read_text(encoding="utf-8"))
        _command_history = {int(k): list(v) for k, v in raw.items()}
    except Exception as e:
        logging.warning(f"Failed to load terminal history: {e}")
        _command_history = {}


def _save_history() -> None:
    try:
        HISTORY_FILE.write_text(
            json.dumps(_command_history, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception as e:
        logging.warning(f"Failed to save terminal history: {e}")


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
    # В проекте бот запущен с parse_mode="Markdown". Внутри ``` ломаются только ```.
    return text.replace("```", "'''" )


def _short_path(path: Path) -> str:
    try:
        home = Path.home()
        return str(path).replace(str(home), "~", 1)
    except Exception:
        return str(path)


def _split_first_arg(text: str) -> str:
    return text.split(" ", 1)[1].strip() if " " in text else ""


def _looks_dangerous(cmd: str) -> bool:
    lowered = cmd.lower()
    return any(re.search(pattern, lowered) for pattern in DANGEROUS_PATTERNS)


def _build_shell_command(cmd: str, shell_name: str):
    if shell_name == "powershell":
        return [
            "powershell",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-Command",
            cmd,
        ]
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


def _format_help() -> str:
    return (
        "💻 *Терминал*\n\n"
        "Команды:\n"
        "`/cmd dir` — выполнить команду\n"
        "`cd C:\\Users` — сменить папку с сохранением cwd\n"
        "`pwd` — текущая папка\n"
        "`shell cmd` / `shell powershell` — выбрать оболочку\n"
        "`timeout 60` — таймаут для следующей команды\n"
        "`history` — история\n"
        "`clear` — очистить историю\n"
        "`help` — помощь\n\n"
        "Для опасных команд нужен префикс `!force`, например:\n"
        "`!force shutdown /s /t 0`"
    )


def _main_keyboard() -> telebot.types.InlineKeyboardMarkup:
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("💻 Ввести", callback_data="term_input"),
        telebot.types.InlineKeyboardButton("📜 История", callback_data="term_history"),
        telebot.types.InlineKeyboardButton("📂 Папка", callback_data="term_pwd"),
        telebot.types.InlineKeyboardButton("🧰 Shell", callback_data="term_shell"),
        telebot.types.InlineKeyboardButton("❓ Помощь", callback_data="term_help"),
        telebot.types.InlineKeyboardButton("🗑 Очистить", callback_data="term_clear_history"),
    )
    return kb


def _shell_keyboard() -> telebot.types.InlineKeyboardMarkup:
    kb = telebot.types.InlineKeyboardMarkup(row_width=2)
    kb.add(
        telebot.types.InlineKeyboardButton("cmd", callback_data="term_set_shell_cmd"),
        telebot.types.InlineKeyboardButton("PowerShell", callback_data="term_set_shell_powershell"),
    )
    return kb


_load_history()


# ──────────────────────────────────────────────────────────────────────────────
# Telegram handlers
# ──────────────────────────────────────────────────────────────────────────────


def register(bot, message):
    user_id = message.from_user.id
    session = _user_session(user_id)
    bot.send_message(
        message.chat.id,
        f"💻 *Терминал*\nShell: `{session.shell}`\nПапка: `{_short_path(session.cwd)}`",
        reply_markup=_main_keyboard(),
    )


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data in (
        "term_input",
        "term_history",
        "term_clear_history",
        "term_pwd",
        "term_help",
        "term_shell",
    ) or c.data.startswith("term_set_shell_") or c.data.startswith("term_run_"))
    def handle_terminal(call):
        if not is_allowed(call):
            return
        bot.answer_callback_query(call.id)
        user_id = call.from_user.id
        session = _user_session(user_id)

        if call.data == "term_input":
            msg = bot.send_message(
                call.message.chat.id,
                f"💻 Введи команду\n`{session.shell}` · `{_short_path(session.cwd)}`",
            )
            bot.register_next_step_handler(msg, run_cmd)
            return

        if call.data == "term_history":
            _send_history(bot, call.message.chat.id, user_id)
            return

        if call.data == "term_clear_history":
            _command_history[user_id] = []
            _save_history()
            bot.send_message(call.message.chat.id, "🗑 История команд очищена")
            return

        if call.data == "term_pwd":
            bot.send_message(call.message.chat.id, f"📂 `{_short_path(session.cwd)}`")
            return

        if call.data == "term_help":
            bot.send_message(call.message.chat.id, _format_help())
            return

        if call.data == "term_shell":
            bot.send_message(call.message.chat.id, "🧰 Выбери оболочку:", reply_markup=_shell_keyboard())
            return

        if call.data.startswith("term_set_shell_"):
            shell = call.data.replace("term_set_shell_", "")
            session.shell = "powershell" if shell == "powershell" else "cmd"
            bot.send_message(call.message.chat.id, f"✅ Shell: `{session.shell}`")
            return

        if call.data.startswith("term_run_"):
            try:
                index = int(call.data.replace("term_run_", ""))
                history = _get_history(user_id, limit=MAX_HISTORY)
                if 0 <= index < len(history):
                    _execute_async(bot, call.message.chat.id, history[index], user_id)
                else:
                    bot.send_message(call.message.chat.id, "❌ Команда не найдена в истории")
            except Exception as e:
                bot.send_message(call.message.chat.id, f"❌ Ошибка: `{_escape_md(str(e))}`")
            return

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


def _send_history(bot, chat_id: int, user_id: int) -> None:
    history = _get_history(user_id, limit=10)
    if not history:
        bot.send_message(chat_id, "📜 История команд пуста")
        return

    kb = telebot.types.InlineKeyboardMarkup(row_width=1)
    for i, cmd in enumerate(reversed(history), 1):
        label = cmd if len(cmd) <= 45 else cmd[:42] + "..."
        # В истории порядок старый→новый, поэтому индекс считаем от конца.
        kb.add(telebot.types.InlineKeyboardButton(f"{i}. {label}", callback_data=f"term_run_{len(history) - i}"))

    text = "📜 *История команд:*\nВыбери команду для повторного запуска:"
    bot.send_message(chat_id, text, reply_markup=kb)


# ──────────────────────────────────────────────────────────────────────────────
# Выполнение команд
# ──────────────────────────────────────────────────────────────────────────────


def _execute_async(bot, chat_id: int, cmd: str, user_id: int) -> None:
    session = _user_session(user_id)
    if session.running:
        elapsed = int(time.time() - session.started_at)
        bot.send_message(chat_id, f"⏳ Уже выполняется: `{_escape_md(session.last_command)}` ({elapsed}с)")
        return

    t = threading.Thread(
        target=_execute,
        args=(bot, chat_id, cmd, user_id),
        daemon=True,
        name=f"terminal-{user_id}",
    )
    t.start()


def _execute(bot, chat_id: int, raw_cmd: str, user_id: int) -> None:
    session = _user_session(user_id)
    cmd = raw_cmd.strip()
    timeout = DEFAULT_TIMEOUT

    session.running = True
    session.started_at = time.time()
    session.last_command = cmd

    try:
        # Встроенные команды терминала бота
        lowered = cmd.lower().strip()
        if lowered in ("help", "/help", "?"):
            bot.send_message(chat_id, _format_help())
            return
        if lowered in ("pwd", "cd"):
            bot.send_message(chat_id, f"📂 `{_short_path(session.cwd)}`")
            return
        if lowered in ("history", "история"):
            _send_history(bot, chat_id, user_id)
            return
        if lowered in ("clear", "очистить"):
            _command_history[user_id] = []
            _save_history()
            bot.send_message(chat_id, "🗑 История команд очищена")
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
                cmd = ""
                bot.send_message(chat_id, f"✅ Таймаут следующей команды: `{timeout}` сек")
            except ValueError:
                bot.send_message(chat_id, "❌ Пример: `timeout 60`")
            return
        if lowered.startswith("cd "):
            target = cmd[3:].strip().strip('"')
            new_cwd = Path(target) if os.path.isabs(target) else session.cwd / target
            new_cwd = new_cwd.resolve()
            if not new_cwd.exists() or not new_cwd.is_dir():
                bot.send_message(chat_id, f"❌ Папка не найдена:\n`{_escape_md(str(new_cwd))}`")
                return
            session.cwd = new_cwd
            bot.send_message(chat_id, f"📂 `{_short_path(session.cwd)}`")
            return

        force = False
        if cmd.startswith("!force "):
            force = True
            cmd = cmd[len("!force "):].strip()

        if _looks_dangerous(cmd) and not force:
            bot.send_message(
                chat_id,
                "⚠️ Команда выглядит опасной и не запущена.\n"
                "Если уверен — отправь её с префиксом `!force`.",
            )
            return

        _add_to_history(user_id, raw_cmd)
        bot.send_message(chat_id, f"▶️ `{_escape_md(cmd)}`\n📂 `{_short_path(session.cwd)}`")

        started = time.time()
        proc = subprocess.run(
            _build_shell_command(cmd, session.shell),
            cwd=str(session.cwd),
            capture_output=True,
            timeout=timeout,
            shell=False,
        )
        elapsed = time.time() - started
        output = _decode_output(proc.stdout) + _decode_output(proc.stderr)
        output = output.strip() or "(нет вывода)"

        # Если команда сама вывела новую директорию через cd /d && cd, не угадываем.
        header = f"✅ Код: `{proc.returncode}` · ⏱ `{elapsed:.1f}с`\n"
        _send_output(bot, chat_id, header, output)
        logging.info("Terminal command executed by %s: %s", user_id, cmd[:200])

    except subprocess.TimeoutExpired:
        bot.send_message(chat_id, f"⏱ Таймаут: команда выполнялась дольше `{timeout}` сек")
        logging.warning("Terminal timeout by %s: %s", user_id, cmd[:200])
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка выполнения:\n`{_escape_md(str(e))}`")
        logging.exception("Terminal error executing: %s", cmd)
    finally:
        session.running = False


def _send_output(bot, chat_id: int, header: str, output: str) -> None:
    safe_output = _escape_md(output)
    if len(safe_output) <= MAX_OUTPUT_MESSAGE:
        bot.send_message(chat_id, f"{header}```\n{safe_output}\n```")
        return

    preview = safe_output[:MAX_OUTPUT_MESSAGE] + "\n...(полный вывод файлом)"
    bot.send_message(chat_id, f"{header}```\n{preview}\n```")

    file_output = output[:MAX_OUTPUT_FILE]
    if len(output) > MAX_OUTPUT_FILE:
        file_output += "\n...(файл обрезан)"

    try:
        with tempfile.NamedTemporaryFile("w", delete=False, suffix=".txt", encoding="utf-8") as f:
            f.write(file_output)
            temp_name = f.name
        with open(temp_name, "rb") as doc:
            bot.send_document(chat_id, doc, caption="📄 Полный вывод команды")
    except Exception:
        logging.exception("Failed to send terminal output file")
    finally:
        try:
            os.remove(temp_name)
        except Exception:
            pass
