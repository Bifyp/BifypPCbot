# watchdog.py — автоперезапуск bot.py если упал

import subprocess
import time
import logging
import sys
import os
from pathlib import Path

logging.basicConfig(
    filename="watchdog.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8",
)

SCRIPT = "bot.py"
RESTART_DELAY = 5  # seconds (base)
MAX_DELAY = 60


def load_dotenv_min(dotenv_path: Path) -> None:
    """Минимальная загрузка .env без зависимостей.

    Нужна, чтобы watchdog мог запускать bot.py с окружением,
    даже если запуск идёт двойным кликом по .vbs.

    Правила:
    - строки вида KEY=VALUE
    - игнорируем пустые строки и комментарии #
    - не перезаписываем уже заданные переменные окружения
    """
    if not dotenv_path.exists():
        return
    try:
        for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            k, v = line.split("=", 1)
            k = k.strip()
            v = v.strip().strip('"').strip("'")
            if k and k not in os.environ:
                os.environ[k] = v
    except Exception as e:
        logging.warning(f"Failed to read .env: {e}")


def main():
    logging.info("Watchdog started")

    base_dir = Path(__file__).resolve().parent
    load_dotenv_min(base_dir / ".env")

    script_path = base_dir / SCRIPT
    if not script_path.exists():
        logging.error(f"Script not found: {script_path}")
        raise SystemExit(2)

    delay = RESTART_DELAY
    while True:
        logging.info(f"Starting {script_path.name}...")
        proc = subprocess.Popen(
            [sys.executable, str(script_path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            cwd=str(base_dir),
            env=os.environ.copy(),
        )
        code = proc.wait()

        # если бот работал долго и завершился — сбрасываем backoff
        if delay > RESTART_DELAY:
            delay = RESTART_DELAY

        logging.warning(f"{script_path.name} exited with code {code}. Restarting in {delay}s...")
        time.sleep(delay)

        # если бот падает мгновенно — увеличиваем задержку (backoff)
        if code != 0:
            delay = min(MAX_DELAY, max(RESTART_DELAY, delay * 2))


if __name__ == "__main__":
    main()
