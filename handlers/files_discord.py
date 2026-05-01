# handlers/files_discord.py — файловый менеджер для Discord

import os
import shutil
import logging
import discord
import hashlib
from config import DEFAULT_FOLDER

# Текущая папка для каждого пользователя
_current_dirs = {}

# Маппинг хешей на полные пути
_path_cache = {}

def _hash_path(path: str) -> str:
    return hashlib.md5(path.encode('utf-8')).hexdigest()[:16]

def _store_path(path: str) -> str:
    path_hash = _hash_path(path)
    _path_cache[path_hash] = path
    return path_hash

def _get_path(path_hash: str) -> str:
    return _path_cache.get(path_hash, path_hash)

def _cdir(uid):
    return _current_dirs.get(uid, DEFAULT_FOLDER)

def _fmt_size(b):
    if b < 1024: return f"{b}B"
    if b < 1024**2: return f"{b//1024}KB"
    if b < 1024**3: return f"{b//1024**2}MB"
    return f"{b//1024**3}GB"


async def handle_discord(interaction: discord.Interaction):
    """Главный обработчик файлового менеджера"""
    uid = interaction.user.id
    path = _cdir(uid)
    await _send_dir(interaction, uid, path)


async def _send_dir(interaction: discord.Interaction, uid: int, path: str, edit: bool = False):
    """Отправка списка файлов и папок"""
    try:
        entries = os.listdir(path)
    except PermissionError:
        text = f"❌ Нет доступа: `{path}`"
        if edit:
            await interaction.response.edit_message(content=text)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        logging.error(f"Permission denied: {path}")
        return
    except FileNotFoundError:
        text = f"❌ Папка не найдена: `{path}`"
        if edit:
            await interaction.response.edit_message(content=text)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        logging.error(f"Directory not found: {path}")
        return
    except Exception as e:
        text = f"❌ Ошибка: {e}"
        if edit:
            await interaction.response.edit_message(content=text)
        else:
            await interaction.response.send_message(text, ephemeral=True)
        logging.exception(f"Error listing directory {path}")
        return

    _current_dirs[uid] = path
    dirs = sorted([e for e in entries if os.path.isdir(os.path.join(path, e))])

    skip_extensions = ('.lnk', '.ini', '.url')
    fls = sorted([e for e in entries
                  if os.path.isfile(os.path.join(path, e))
                  and not e.lower().endswith(skip_extensions)])

    view = FileManagerView(uid, path, dirs, fls)
    text = f"📁 `{path}`\n{len(dirs)} папок, {len(fls)} файлов"

    if edit:
        await interaction.response.edit_message(content=text, view=view)
    else:
        await interaction.response.send_message(text, view=view, ephemeral=True)


class FileManagerView(discord.ui.View):
    def __init__(self, uid: int, path: str, dirs: list, files: list):
        super().__init__(timeout=300)
        self.uid = uid
        self.path = path

        # Кнопка "вверх"
        parent = os.path.dirname(path)
        if parent != path:
            parent_hash = _store_path(parent)
            btn_up = discord.ui.Button(label="⬆️ ..", style=discord.ButtonStyle.secondary, custom_id=f"fl_cd_{parent_hash}")
            btn_up.callback = self.navigate_callback
            self.add_item(btn_up)

        # Папки (до 10)
        for d in dirs[:10]:
            full = os.path.join(path, d)
            full_hash = _store_path(full)
            btn = discord.ui.Button(label=f"📂 {d[:75]}", style=discord.ButtonStyle.primary, custom_id=f"fl_cd_{full_hash}", row=min(len(self.children) // 5, 4))
            btn.callback = self.navigate_callback
            self.add_item(btn)
            if len(self.children) >= 20:  # Discord max 25 components
                break

        # Файлы (до оставшихся слотов)
        for f in files:
            if len(self.children) >= 20:
                break
            full = os.path.join(path, f)
            try:
                size = os.path.getsize(full)
                label = f"📄 {f[:60]} ({_fmt_size(size)})"
            except:
                label = f"📄 {f[:75]}"

            full_hash = _store_path(full)
            btn = discord.ui.Button(label=label[:80], style=discord.ButtonStyle.secondary, custom_id=f"fl_file_{full_hash}", row=min(len(self.children) // 5, 4))
            btn.callback = self.file_callback
            self.add_item(btn)

    async def navigate_callback(self, interaction: discord.Interaction):
        """Навигация по папкам"""
        path_hash = interaction.data['custom_id'].replace("fl_cd_", "")
        path = _get_path(path_hash)
        await _send_dir(interaction, self.uid, path, edit=True)

    async def file_callback(self, interaction: discord.Interaction):
        """Действия с файлом"""
        path_hash = interaction.data['custom_id'].replace("fl_file_", "")
        path = _get_path(path_hash)

        try:
            size = os.path.getsize(path)
            view = FileActionsView(path)
            text = f"📄 `{os.path.basename(path)}`\n💾 Размер: {_fmt_size(size)}"
            await interaction.response.send_message(text, view=view, ephemeral=True)
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка: {e}", ephemeral=True)


class FileActionsView(discord.ui.View):
    def __init__(self, file_path: str):
        super().__init__(timeout=60)
        self.file_path = file_path

    @discord.ui.button(label="📥 Скачать", style=discord.ButtonStyle.success, custom_id="fl_download")
    async def download_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer()
        try:
            if not os.path.exists(self.file_path):
                await interaction.followup.send(f"❌ Файл не найден", ephemeral=True)
                return

            size = os.path.getsize(self.file_path)
            if size > 25 * 1024 * 1024:  # Discord limit 25MB
                await interaction.followup.send("❌ Файл больше 25MB — нельзя отправить через Discord", ephemeral=True)
                return

            file = discord.File(self.file_path, filename=os.path.basename(self.file_path))
            await interaction.followup.send(f"📄 {os.path.basename(self.file_path)}", file=file, ephemeral=True)
            logging.info(f"File downloaded: {self.file_path}")
        except Exception as e:
            await interaction.followup.send(f"❌ Ошибка: {e}", ephemeral=True)
            logging.exception(f"Error downloading {self.file_path}")

    @discord.ui.button(label="🗑 Удалить", style=discord.ButtonStyle.danger, custom_id="fl_delete")
    async def delete_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        view = ConfirmDeleteView(self.file_path)
        await interaction.response.send_message(
            f"⚠️ Удалить `{os.path.basename(self.file_path)}`?",
            view=view,
            ephemeral=True
        )


class ConfirmDeleteView(discord.ui.View):
    def __init__(self, file_path: str):
        super().__init__(timeout=30)
        self.file_path = file_path

    @discord.ui.button(label="✅ Да, удалить", style=discord.ButtonStyle.danger, custom_id="fl_confirm_delete")
    async def confirm_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        try:
            if os.path.isdir(self.file_path):
                shutil.rmtree(self.file_path)
            else:
                os.remove(self.file_path)
            await interaction.response.send_message(f"🗑 Удалено: `{os.path.basename(self.file_path)}`", ephemeral=True)
            logging.info(f"Deleted: {self.file_path}")
        except Exception as e:
            await interaction.response.send_message(f"❌ Ошибка удаления: {e}", ephemeral=True)
            logging.exception(f"Error deleting {self.file_path}")

    @discord.ui.button(label="❌ Отмена", style=discord.ButtonStyle.secondary, custom_id="fl_cancel_delete")
    async def cancel_btn(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_message("❌ Отменено", ephemeral=True)
