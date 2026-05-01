# bot_discord.py — Discord версия PC Control Bot v3.0

import discord
from discord.ext import commands
import threading
import time
import logging
import os

from config import DISCORD_TOKEN, ALLOWED_IDS
from web.server import start_web_server, set_bot_ref

from handlers import screenshot, alerts, autoscreenshot, scheduler
from handlers.discord_handlers import (
    files_discord_handler as files_discord,
    terminal_discord, media_discord, browser_discord,
    system_discord, apps_discord, input_discord, clipboard_discord
)

logging.basicConfig(
    filename="bot.log",
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    encoding="utf-8"
)

intents = discord.Intents.default()
# intents.message_content = True  # Нужно включить в Developer Portal

bot = commands.Bot(command_prefix="!", intents=intents)


def is_allowed(ctx_or_interaction):
    """Проверка доступа для команд и взаимодействий"""
    if isinstance(ctx_or_interaction, discord.Interaction):
        return ctx_or_interaction.user.id in ALLOWED_IDS
    return ctx_or_interaction.author.id in ALLOWED_IDS


@bot.event
async def on_ready():
    logging.info(f"Discord bot logged in as {bot.user}")
    print(f"Bot online: {bot.user}")

    # Добавляем persistent view для кнопок
    bot.add_view(MainMenuView())

    # Уведомление в DM с кнопками
    for uid in ALLOWED_IDS:
        try:
            user = await bot.fetch_user(uid)
            from web.server import get_tunnel_url
            url = get_tunnel_url() or "_(туннель ещё запускается)_"

            embed = discord.Embed(
                title="PC Control Bot v3.0 онлайн!",
                description=f"🌐 **Веб-панель:** {url}\n🔒 **Сессия:** 2 часа\n📡 **WebSocket:** активен\n\n👇 Используй кнопки ниже:",
                color=discord.Color.green()
            )

            view = MainMenuView()
            await user.send(embed=embed, view=view)
        except Exception as e:
            logging.warning(f"notify error: {e}")


@bot.command(name="start")
async def cmd_start(ctx):
    """Главное меню бота"""
    if not is_allowed(ctx):
        return

    embed = discord.Embed(
        title="🖥 PC Control Bot v3.0",
        description="Выбери раздел:",
        color=discord.Color.blue()
    )

    view = MainMenuView()

    banner = os.path.join(os.path.dirname(__file__), "start_banner.jpg")
    if os.path.exists(banner):
        file = discord.File(banner, filename="banner.jpg")
        embed.set_image(url="attachment://banner.jpg")
        await ctx.send(embed=embed, view=view, file=file)
    else:
        await ctx.send(embed=embed, view=view)


class MainMenuView(discord.ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @discord.ui.button(label="📸 Скриншот", style=discord.ButtonStyle.primary, row=0, custom_id="btn_screenshot")
    async def screenshot_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await screenshot.handle_discord(interaction)

    @discord.ui.button(label="📁 Файлы", style=discord.ButtonStyle.primary, row=0, custom_id="btn_files")
    async def files_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await files_discord(interaction)

    @discord.ui.button(label="💻 Терминал", style=discord.ButtonStyle.primary, row=0, custom_id="btn_terminal")
    async def terminal_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await terminal_discord(interaction)

    @discord.ui.button(label="🔊 Медиа", style=discord.ButtonStyle.primary, row=1, custom_id="btn_media")
    async def media_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await media_discord(interaction)

    @discord.ui.button(label="🌐 Браузер", style=discord.ButtonStyle.primary, row=1, custom_id="btn_browser")
    async def browser_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await browser_discord(interaction)

    @discord.ui.button(label="⚙️ Система", style=discord.ButtonStyle.primary, row=1, custom_id="btn_system")
    async def system_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await system_discord(interaction)

    @discord.ui.button(label="🚀 Приложения", style=discord.ButtonStyle.secondary, row=2, custom_id="btn_apps")
    async def apps_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await apps_discord(interaction)

    @discord.ui.button(label="⌨️ Ввод", style=discord.ButtonStyle.secondary, row=2, custom_id="btn_input")
    async def input_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await input_discord(interaction)

    @discord.ui.button(label="📋 Буфер", style=discord.ButtonStyle.secondary, row=2, custom_id="btn_clipboard")
    async def clipboard_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        await clipboard_discord(interaction)

    @discord.ui.button(label="📹 Веб-панель", style=discord.ButtonStyle.success, row=3, custom_id="btn_webpanel")
    async def remote_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not is_allowed(interaction):
            return
        from web.server import get_tunnel_url
        url = get_tunnel_url()
        if url:
            embed = discord.Embed(
                title="🌐 Веб-панель",
                description=f"**URL:** {url}\n\n🔒 Введи пароль из `config.py`\n⏱ Сессия истекает через 2 часа",
                color=discord.Color.green()
            )
            await interaction.response.send_message(embed=embed, ephemeral=True)
        else:
            await interaction.response.send_message("⏳ Туннель запускается, подожди 10–15 сек...", ephemeral=True)


if __name__ == "__main__":
    logging.info("PC Control Bot v3.0 (Discord) запускается...")

    # Передаём ссылку на бот в web-сервер
    set_bot_ref(bot, ALLOWED_IDS)

    # Flask + cloudflared
    threading.Thread(target=start_web_server, daemon=True).start()

    # Системные алерты
    threading.Thread(target=alerts.start_monitoring,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    # Авто-скриншоты + детект активности
    threading.Thread(target=autoscreenshot.start_auto_tasks,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    # Планировщик задач
    threading.Thread(target=scheduler.start_scheduler,
                     args=(bot, ALLOWED_IDS), daemon=True).start()

    logging.info("Discord bot starting...")
    bot.run(DISCORD_TOKEN)
