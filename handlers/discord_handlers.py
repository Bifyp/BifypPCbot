# handlers/discord_handlers.py — Discord заглушки для всех handlers

import discord
import logging
from handlers import files_discord


async def handle_discord_stub(interaction: discord.Interaction, module_name: str):
    """Базовая заглушка для handlers"""
    embed = discord.Embed(
        title=f"⚙️ {module_name}",
        description="Этот модуль в процессе адаптации под Discord.\nИспользуй веб-панель для полного функционала.",
        color=discord.Color.orange()
    )
    await interaction.response.send_message(embed=embed, ephemeral=True)
    logging.info(f"Discord stub called: {module_name}")


# Экспорт handlers
async def files_discord_handler(interaction):
    await files_discord.handle_discord(interaction)

async def terminal_discord(interaction):
    await handle_discord_stub(interaction, "Терминал")

async def media_discord(interaction):
    await handle_discord_stub(interaction, "Медиа")

async def browser_discord(interaction):
    await handle_discord_stub(interaction, "Браузер")

async def system_discord(interaction):
    await handle_discord_stub(interaction, "Система")

async def apps_discord(interaction):
    await handle_discord_stub(interaction, "Приложения")

async def input_discord(interaction):
    await handle_discord_stub(interaction, "Ввод")

async def clipboard_discord(interaction):
    await handle_discord_stub(interaction, "Буфер обмена")
