@echo off
:: start_bot.bat — запуск PC Control Bot при старте Windows
:: Добавь в Планировщик задач: триггер "При входе в систему"

cd /d "%~dp0"

:: Ждём 30 секунд после загрузки (чтобы сеть поднялась)
timeout /t 30 /nobreak >nul

:: Запускаем watchdog (он следит за bot.py и перезапускает если упал)
start "" /min pythonw watchdog.py

exit
