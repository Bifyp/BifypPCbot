

# watchdog.py — автоперезапуск bot.py если упал

import subprocess
import time
import logging
import sys

logging.basicConfig(
    filename="watchdog.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

SCRIPT = "bot.py"
RESTART_DELAY = 5  # секунд


def main():
    logging.info("Watchdog запущен")
    while True:
        logging.info(f"Запускаю {SCRIPT}...")
        proc = subprocess.Popen(
            [sys.executable, SCRIPT],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL
        )
        code = proc.wait()
        logging.warning(f"{SCRIPT} завершился с кодом {code}. Перезапуск через {RESTART_DELAY}с...")
        time.sleep(RESTART_DELAY)


if __name__ == "__main__":
    main()
