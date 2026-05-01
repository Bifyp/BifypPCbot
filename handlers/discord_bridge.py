# handlers/discord_bridge.py — универсальный мост Telegram → Discord

import discord
import io
import os
import logging
from typing import Union, Callable, Any


class TelegramToDiscordBridge:
    """
    Эмулирует Telegram Bot API для Discord.
    Позволяет использовать существующие Telegram handlers без изменений.
    """

    def __init__(self, discord_bot: discord.Client):
        self.discord_bot = discord_bot
        self._callback_handlers = []
        self._message_handlers = []
        self._next_step_handlers = {}

    # ─── Telegram Bot API эмуляция ────────────────────────────────────────────

    def send_message(self, chat_id: int, text: str, reply_markup=None, parse_mode=None):
        """Отправка текстового сообщения"""
        async def _send():
            try:
                user = await self.discord_bot.fetch_user(chat_id)
                view = self._convert_keyboard(reply_markup) if reply_markup else None
                await user.send(text, view=view)
            except Exception as e:
                logging.error(f"send_message error: {e}")

        import asyncio
        asyncio.create_task(_send())

    def send_photo(self, chat_id: int, photo: Union[str, bytes, io.BytesIO], caption: str = None):
        """Отправка фото"""
        async def _send():
            try:
                user = await self.discord_bot.fetch_user(chat_id)

                if isinstance(photo, str):
                    file = discord.File(photo)
                elif isinstance(photo, bytes):
                    file = discord.File(io.BytesIO(photo), filename="image.png")
                elif isinstance(photo, io.BytesIO):
                    file = discord.File(photo, filename="image.png")
                else:
                    file = discord.File(photo)

                await user.send(content=caption, file=file)
            except Exception as e:
                logging.error(f"send_photo error: {e}")

        import asyncio
        asyncio.create_task(_send())

    def send_document(self, chat_id: int, document: Union[str, Any], caption: str = None):
        """Отправка документа"""
        async def _send():
            try:
                user = await self.discord_bot.fetch_user(chat_id)

                if isinstance(document, str):
                    file = discord.File(document)
                else:
                    # document это file-like object
                    filename = getattr(document, 'name', 'file.bin')
                    if hasattr(document, 'read'):
                        file = discord.File(document, filename=os.path.basename(filename))
                    else:
                        file = discord.File(document)

                await user.send(content=caption, file=file)
            except Exception as e:
                logging.error(f"send_document error: {e}")

        import asyncio
        asyncio.create_task(_send())

    def send_video(self, chat_id: int, video: Any, caption: str = None):
        """Отправка видео"""
        self.send_document(chat_id, video, caption)

    def send_audio(self, chat_id: int, audio: Any, caption: str = None):
        """Отправка аудио"""
        self.send_document(chat_id, audio, caption)

    def edit_message_text(self, text: str, chat_id: int, message_id: int, reply_markup=None, parse_mode=None):
        """Редактирование сообщения"""
        # Discord не поддерживает редактирование чужих сообщений через бота
        # Отправляем новое сообщение
        self.send_message(chat_id, text, reply_markup, parse_mode)

    def answer_callback_query(self, callback_query_id: str, text: str = None):
        """Ответ на callback query"""
        # В Discord это defer или followup
        pass

    def reply_to(self, message, text: str, reply_markup=None):
        """Ответ на сообщение"""
        self.send_message(message.chat.id, text, reply_markup)

    def register_next_step_handler(self, message, callback: Callable):
        """Регистрация обработчика следующего сообщения"""
        self._next_step_handlers[message.chat.id] = callback

    def get_file(self, file_id: str):
        """Получение информации о файле"""
        # Заглушка для совместимости
        class FileInfo:
            def __init__(self):
                self.file_path = file_id
        return FileInfo()

    def download_file(self, file_path: str) -> bytes:
        """Скачивание файла"""
        # Заглушка для совместимости
        return b""

    # ─── Регистрация handlers ─────────────────────────────────────────────────

    def callback_query_handler(self, func: Callable = None, **kwargs):
        """Декоратор для callback handlers"""
        def decorator(handler):
            self._callback_handlers.append((func, handler))
            return handler
        return decorator

    def message_handler(self, **kwargs):
        """Декоратор для message handlers"""
        def decorator(handler):
            self._message_handlers.append((kwargs, handler))
            return handler
        return decorator

    # ─── Конвертация клавиатур ────────────────────────────────────────────────

    def _convert_keyboard(self, telegram_markup) -> discord.ui.View:
        """Конвертирует Telegram InlineKeyboardMarkup в Discord View"""
        view = discord.ui.View(timeout=None)

        if not hasattr(telegram_markup, 'keyboard'):
            return view

        for row_idx, row in enumerate(telegram_markup.keyboard[:5]):  # Discord max 5 rows
            for btn in row[:5]:  # Discord max 5 buttons per row
                button = discord.ui.Button(
                    label=btn.text[:80],  # Discord max 80 chars
                    style=discord.ButtonStyle.primary,
                    custom_id=btn.callback_data[:100] if btn.callback_data else f"btn_{row_idx}",
                    row=row_idx
                )

                # Создаём callback для кнопки
                async def btn_callback(interaction: discord.Interaction, callback_data=btn.callback_data):
                    # Эмулируем Telegram CallbackQuery
                    call = self._create_fake_call(interaction, callback_data)

                    # Ищем подходящий handler
                    for func, handler in self._callback_handlers:
                        if func is None or func(call):
                            handler(call)
                            break

                button.callback = btn_callback
                view.add_item(button)

        return view

    def _create_fake_call(self, interaction: discord.Interaction, callback_data: str):
        """Создаёт фейковый Telegram CallbackQuery из Discord Interaction"""
        class FakeCall:
            def __init__(self, inter, data):
                self.id = str(inter.id)
                self.data = data
                self.from_user = FakeUser(inter.user.id)
                self.message = FakeMessage(inter.user.id, inter.channel_id)

        class FakeUser:
            def __init__(self, uid):
                self.id = uid

        class FakeMessage:
            def __init__(self, uid, cid):
                self.chat = FakeChat(cid)
                self.message_id = 0
                self.from_user = FakeUser(uid)

        class FakeChat:
            def __init__(self, cid):
                self.id = cid

        return FakeCall(interaction, callback_data)


# ─── Глобальный экземпляр моста ───────────────────────────────────────────────

_bridge = None

def get_bridge(discord_bot: discord.Client = None) -> TelegramToDiscordBridge:
    """Получить глобальный экземпляр моста"""
    global _bridge
    if _bridge is None and discord_bot:
        _bridge = TelegramToDiscordBridge(discord_bot)
    return _bridge
