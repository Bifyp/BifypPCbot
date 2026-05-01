# discord_adapter.py — адаптер для handlers под Discord API

import discord
import io
import os
from typing import Union, Optional


class DiscordAdapter:
    """Адаптер для совместимости Telegram handlers с Discord"""

    @staticmethod
    async def send_message(bot_or_interaction: Union[discord.Client, discord.Interaction],
                          user_id: int,
                          text: str,
                          parse_mode: Optional[str] = None):
        """Отправка текстового сообщения"""
        if isinstance(bot_or_interaction, discord.Interaction):
            await bot_or_interaction.response.send_message(text)
        else:
            user = await bot_or_interaction.fetch_user(user_id)
            await user.send(text)

    @staticmethod
    async def send_photo(bot_or_interaction: Union[discord.Client, discord.Interaction],
                        user_id: int,
                        photo: Union[str, bytes, io.BytesIO],
                        caption: Optional[str] = None):
        """Отправка фото"""
        if isinstance(photo, str):
            file = discord.File(photo)
        elif isinstance(photo, bytes):
            file = discord.File(io.BytesIO(photo), filename="image.png")
        elif isinstance(photo, io.BytesIO):
            file = discord.File(photo, filename="image.png")
        else:
            file = discord.File(photo)

        if isinstance(bot_or_interaction, discord.Interaction):
            await bot_or_interaction.response.send_message(content=caption, file=file)
        else:
            user = await bot_or_interaction.fetch_user(user_id)
            await user.send(content=caption, file=file)

    @staticmethod
    async def send_document(bot_or_interaction: Union[discord.Client, discord.Interaction],
                           user_id: int,
                           document: Union[str, bytes, io.BytesIO],
                           caption: Optional[str] = None,
                           filename: Optional[str] = None):
        """Отправка файла"""
        if isinstance(document, str):
            file = discord.File(document)
        elif isinstance(document, bytes):
            file = discord.File(io.BytesIO(document), filename=filename or "file.bin")
        elif isinstance(document, io.BytesIO):
            file = discord.File(document, filename=filename or "file.bin")
        else:
            file = discord.File(document)

        if isinstance(bot_or_interaction, discord.Interaction):
            await bot_or_interaction.response.send_message(content=caption, file=file)
        else:
            user = await bot_or_interaction.fetch_user(user_id)
            await user.send(content=caption, file=file)

    @staticmethod
    async def send_audio(bot_or_interaction: Union[discord.Client, discord.Interaction],
                        user_id: int,
                        audio: Union[str, bytes, io.BytesIO],
                        caption: Optional[str] = None,
                        filename: Optional[str] = None):
        """Отправка аудио"""
        await DiscordAdapter.send_document(bot_or_interaction, user_id, audio, caption, filename)

    @staticmethod
    async def send_video(bot_or_interaction: Union[discord.Client, discord.Interaction],
                        user_id: int,
                        video: Union[str, bytes, io.BytesIO],
                        caption: Optional[str] = None,
                        filename: Optional[str] = None):
        """Отправка видео"""
        await DiscordAdapter.send_document(bot_or_interaction, user_id, video, caption, filename)

    @staticmethod
    def create_inline_keyboard(buttons: list) -> discord.ui.View:
        """Создание inline клавиатуры"""
        view = discord.ui.View(timeout=None)

        for row_idx, row in enumerate(buttons):
            for btn in row:
                button = discord.ui.Button(
                    label=btn.get("text", "Button"),
                    style=discord.ButtonStyle.primary,
                    custom_id=btn.get("callback_data", "btn"),
                    row=row_idx
                )
                view.add_item(button)

        return view

    @staticmethod
    def create_reply_keyboard(buttons: list) -> str:
        """Reply клавиатура в Discord не поддерживается, возвращаем текст"""
        keyboard_text = "\n".join([" | ".join(row) for row in buttons])
        return f"\n\n**Доступные команды:**\n{keyboard_text}"
