# handlers/installer.py — удалённая установка программ

import os
import subprocess
import logging
import telebot
import tempfile
import threading

def register(bot, message):
    kb = telebot.types.InlineKeyboardMarkup()
    kb.add(
        telebot.types.InlineKeyboardButton("📦 Установить из файла", callback_data="inst_file"),
        telebot.types.InlineKeyboardButton("🌐 Установить по URL", callback_data="inst_url"),
    )
    kb.add(
        telebot.types.InlineKeyboardButton("📋 Winget поиск", callback_data="inst_winget_search"),
        telebot.types.InlineKeyboardButton("⚡ Winget установка", callback_data="inst_winget_install"),
    )
    bot.send_message(message.chat.id, "📦 *Установка программ:*", reply_markup=kb)


def _install_file(file_path, chat_id, bot):
    """Устанавливает программу из файла"""
    try:
        ext = os.path.splitext(file_path)[1].lower()

        if ext == ".msi":
            # MSI установка через msiexec
            cmd = f'msiexec /i "{file_path}" /qn /norestart'
        elif ext == ".exe":
            # EXE установка с тихим режимом
            cmd = f'"{file_path}" /S /silent /quiet /verysilent /norestart'
        else:
            bot.send_message(chat_id, f"❌ Неподдерживаемый формат: {ext}")
            return

        bot.send_message(chat_id, f"📦 Запускаю установку...\n`{cmd}`")

        result = subprocess.run(cmd, shell=True, capture_output=True,
                              text=True, timeout=300)

        if result.returncode == 0:
            bot.send_message(chat_id, "✅ Установка завершена успешно")
            logging.info(f"Software installed: {file_path}")
        else:
            bot.send_message(chat_id,
                           f"⚠️ Установка завершена с кодом {result.returncode}\n"
                           f"```{result.stderr[:500]}```")
            logging.warning(f"Installation finished with code {result.returncode}")

    except subprocess.TimeoutExpired:
        bot.send_message(chat_id, "⏱ Установка превысила таймаут 5 минут")
        logging.warning(f"Installation timeout: {file_path}")
    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка установки: {e}")
        logging.exception("Installation error")


def _download_and_install(url, chat_id, bot):
    """Скачивает и устанавливает программу по URL"""
    try:
        import requests

        bot.send_message(chat_id, f"⬇️ Скачиваю файл...\n`{url}`")

        # Определяем расширение из URL
        ext = ".exe"
        if url.lower().endswith(".msi"):
            ext = ".msi"

        # Скачиваем файл
        response = requests.get(url, stream=True, timeout=60)
        response.raise_for_status()

        tmp_file = tempfile.mktemp(suffix=ext)

        with open(tmp_file, "wb") as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)

        file_size = os.path.getsize(tmp_file)
        bot.send_message(chat_id, f"✅ Файл скачан ({file_size // 1024} KB)")

        # Устанавливаем
        _install_file(tmp_file, chat_id, bot)

        # Удаляем временный файл
        try:
            os.remove(tmp_file)
        except Exception:
            pass

    except Exception as e:
        bot.send_message(chat_id, f"❌ Ошибка скачивания: {e}")
        logging.exception("Download error")


def setup(bot: telebot.TeleBot, is_allowed):

    @bot.callback_query_handler(func=lambda c: c.data.startswith("inst_"))
    def handle_installer(call):
        if not is_allowed(call): return
        bot.answer_callback_query(call.id)

        if call.data == "inst_file":
            msg = bot.send_message(call.message.chat.id,
                                 "📦 Отправь установочный файл (.exe или .msi)")
            # Обработчик файла будет ниже

        elif call.data == "inst_url":
            msg = bot.send_message(call.message.chat.id,
                                 "🌐 Введи URL установочного файла (.exe или .msi):")
            bot.register_next_step_handler(msg, handle_url_install)

        elif call.data == "inst_winget_search":
            msg = bot.send_message(call.message.chat.id,
                                 "🔍 Введи название программы для поиска в Winget:")
            bot.register_next_step_handler(msg, handle_winget_search)

        elif call.data == "inst_winget_install":
            msg = bot.send_message(call.message.chat.id,
                                 "⚡ Введи ID программы из Winget (например: Google.Chrome):")
            bot.register_next_step_handler(msg, handle_winget_install)

    def handle_url_install(message):
        if not is_allowed(message): return
        url = message.text.strip()

        if not url.startswith("http"):
            bot.send_message(message.chat.id, "❌ URL должен начинаться с http:// или https://")
            return

        # Запускаем установку в отдельном потоке
        threading.Thread(target=_download_and_install,
                        args=(url, message.chat.id, bot),
                        daemon=True).start()

    def handle_winget_search(message):
        if not is_allowed(message): return
        query = message.text.strip()

        try:
            bot.send_message(message.chat.id, f"🔍 Ищу: `{query}`")

            result = subprocess.run(
                f'winget search "{query}"',
                shell=True, capture_output=True, text=True,
                timeout=30, encoding="utf-8", errors="replace"
            )

            output = result.stdout or result.stderr or "(нет результатов)"

            if len(output) > 3800:
                output = output[:3800] + "\n...(обрезано)"

            bot.send_message(message.chat.id, f"```\n{output}\n```")
            logging.info(f"Winget search: {query}")

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка поиска: {e}")
            logging.exception("Winget search error")

    def handle_winget_install(message):
        if not is_allowed(message): return
        package_id = message.text.strip()

        try:
            bot.send_message(message.chat.id, f"⚡ Устанавливаю: `{package_id}`")

            def install():
                try:
                    result = subprocess.run(
                        f'winget install --id {package_id} --silent --accept-package-agreements --accept-source-agreements',
                        shell=True, capture_output=True, text=True,
                        timeout=600, encoding="utf-8", errors="replace"
                    )

                    if result.returncode == 0:
                        bot.send_message(message.chat.id, f"✅ {package_id} установлен успешно")
                        logging.info(f"Winget installed: {package_id}")
                    else:
                        output = result.stderr or result.stdout or "(нет вывода)"
                        bot.send_message(message.chat.id,
                                       f"⚠️ Установка завершена с кодом {result.returncode}\n"
                                       f"```{output[:500]}```")
                        logging.warning(f"Winget install failed: {package_id}")

                except subprocess.TimeoutExpired:
                    bot.send_message(message.chat.id, "⏱ Установка превысила таймаут 10 минут")
                except Exception as e:
                    bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
                    logging.exception("Winget install error")

            threading.Thread(target=install, daemon=True).start()

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
            logging.exception("Winget install error")

    # Обработчик загруженных файлов
    @bot.message_handler(content_types=["document"])
    def handle_document(message):
        if not is_allowed(message): return

        # Проверяем расширение
        if not message.document or not message.document.file_name:
            return

        file_name = message.document.file_name
        if not (file_name.endswith(".exe") or file_name.endswith(".msi")):
            return  # Не установочный файл, пропускаем

        try:
            bot.send_message(message.chat.id, f"📥 Скачиваю: `{file_name}`")

            file_info = bot.get_file(message.document.file_id)
            downloaded = bot.download_file(file_info.file_path)

            ext = os.path.splitext(file_name)[1]
            tmp_file = tempfile.mktemp(suffix=ext)

            with open(tmp_file, "wb") as f:
                f.write(downloaded)

            bot.send_message(message.chat.id, "✅ Файл получен, начинаю установку...")

            # Устанавливаем в отдельном потоке
            threading.Thread(target=_install_file,
                           args=(tmp_file, message.chat.id, bot),
                           daemon=True).start()

        except Exception as e:
            bot.send_message(message.chat.id, f"❌ Ошибка: {e}")
            logging.exception("Document handler error")
