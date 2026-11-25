"""Telegram entry points and navigation for the user-facing bot UI."""

from __future__ import annotations

import time
from html import escape
from types import SimpleNamespace

import psutil
from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions

from .ui import InlineKeyboardButton

from config import Config
from database import db
from messages import Script

START_TIME = time.time()


def home_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🚀  Start forwarding", callback_data="quick_forward"),
                InlineKeyboardButton("📊  My dashboard", callback_data="dashboard"),
            ],
            [
                InlineKeyboardButton("⚙️  Settings", callback_data="settings#main"),
                InlineKeyboardButton("📖  Help", callback_data="help"),
            ],
            [
                InlineKeyboardButton("ℹ️  About", callback_data="about"),
                InlineKeyboardButton("📡  Service status", callback_data="status"),
            ],
        ]
    )


def home_text(name: str) -> str:
    return Script.START_TXT.format(escape(name or "there"))


async def dashboard_text(user_id: int) -> str:
    """Return a compact, per-user view of setup readiness and task progress."""
    account = await db.get_bot(user_id)
    account_kind = "Bot"
    if not account:
        account = await db.get_userbot(user_id)
        account_kind = "User account"

    channels = await db.get_user_channels(user_id)
    active = await db.is_forwad_exit(user_id)
    details = await db.get_forward_details(user_id) if active else {}

    account_line = "Not connected"
    if account:
        username = account.get("username")
        account_line = f"{account_kind}: {escape(account.get('name') or 'Connected')}"
        if username:
            account_line += f" (@{escape(username)})"

    if active:
        fetched = int(details.get("fetched") or 0)
        limit = int(details.get("limit") or 0)
        task_line = f"Running · {fetched:,} of {limit:,} messages scanned"
    else:
        task_line = "No active forwarding task"

    if account and channels:
        readiness = "Ready to forward"
    elif not account and not channels:
        readiness = "Connect an account and add a destination to get started"
    elif not account:
        readiness = "Connect a bot or user account to continue"
    else:
        readiness = "Add a destination channel to continue"

    destinations = "\n".join(
        f"• {escape(str(channel.get('title') or 'Untitled chat'))}"
        for channel in channels[:4]
    ) or "• No destinations added"
    if len(channels) > 4:
        destinations += f"\n• and {len(channels) - 4} more"

    return (
        "<b>📊 Your dashboard</b>\n\n"
        f"<b>Setup:</b> {escape(readiness)}\n"
        f"<b>Connected:</b> {account_line}\n"
        f"<b>Destinations:</b> {len(channels)}\n{destinations}\n\n"
        f"<b>Forwarding:</b> {escape(task_line)}"
    )


@Client.on_message(filters.private & filters.command(["start"]))
async def start(client, message):
    user = message.from_user
    if not await db.is_user_exist(user.id):
        await db.add_user(user.id, user.first_name)
    await client.send_message(
        chat_id=message.chat.id,
        text=home_text(user.first_name),
        reply_markup=home_keyboard(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_message(filters.private & filters.command(["status"]))
async def user_status(client, message):
    await message.reply_text(
        await dashboard_text(message.from_user.id),
        reply_markup=home_keyboard(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_message(filters.private & filters.command(["restart"]) & filters.user(Config.BOT_OWNER))
async def restart(client, message):
    # Restarts belong to the process manager, not a Telegram shell command.
    await message.reply_text(
        "<b>Restart is managed by your hosting platform.</b>\n"
        "Restart or redeploy the worker from its dashboard."
    )


@Client.on_callback_query(filters.regex(r"^quick_forward$"))
async def quick_forward(client, query):
    if query.message.chat.id != query.from_user.id:
        return await query.answer(
            "Open the bot in a private chat to start forwarding.", show_alert=True
        )
    await query.answer()
    # Reuse the exact same setup flow as /forward while retaining the clicker's
    # identity (the callback's Message.from_user would otherwise be the bot).
    from .public import begin_forward

    context = SimpleNamespace(
        from_user=query.from_user,
        chat=query.message.chat,
        reply=query.message.reply,
        reply_text=query.message.reply_text,
    )
    await begin_forward(client, context)


@Client.on_callback_query(filters.regex(r"^(?:home|back)$"))
async def home(client, query):
    await query.answer()
    await query.message.edit_text(
        home_text(query.from_user.first_name),
        reply_markup=home_keyboard(),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^dashboard$"))
async def dashboard(client, query):
    await query.answer()
    await query.message.edit_text(
        await dashboard_text(query.from_user.id),
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🔄  Refresh", callback_data="dashboard")],
                [InlineKeyboardButton("🏠 Main menu", callback_data="home")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^help$"))
async def help_page(client, query):
    await query.answer()
    await query.message.edit_text(
        Script.HELP_TXT,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🚦  Quick start", callback_data="how_to_use")],
                [
                    InlineKeyboardButton("⚙️  Settings", callback_data="settings#main"),
                    InlineKeyboardButton("🏠 Home", callback_data="home"),
                ],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^how_to_use$"))
async def how_to_use(client, query):
    await query.answer()
    await query.message.edit_text(
        Script.HOW_USE_TXT,
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("🏠 Main menu", callback_data="home")]]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^about$"))
async def about(client, query):
    await query.answer()
    await query.message.edit_text(
        Script.ABOUT_TXT,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊  Service stats", callback_data="status")],
                [InlineKeyboardButton("🏠 Main menu", callback_data="home")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^status$"))
async def status(client, query):
    users_count, bots_count = await db.total_users_bots_count()
    forwardings = await db.forwad_count()
    uptime = await get_bot_uptime(START_TIME)
    await query.answer()
    await query.message.edit_text(
        Script.STATUS_TXT.format(uptime, users_count, bots_count, forwardings),
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("🖥  System details", callback_data="systm_sts")],
                [InlineKeyboardButton("🏠 Main menu", callback_data="home")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


@Client.on_callback_query(filters.regex(r"^systm_sts$"))
async def sys_status(client, query):
    disk_usage = psutil.disk_usage("/")
    total_space = disk_usage.total / (1024**3)
    used_space = disk_usage.used / (1024**3)
    free_space = disk_usage.free / (1024**3)
    text = (
        "<b>🖥 System status</b>\n\n"
        f"<b>CPU:</b> <code>{psutil.cpu_percent()}%</code>\n"
        f"<b>Memory:</b> <code>{psutil.virtual_memory().percent}%</code>\n"
        f"<b>Disk used:</b> <code>{used_space:.2f} / {total_space:.2f} GB</code>\n"
        f"<b>Disk free:</b> <code>{free_space:.2f} GB</code>"
    )
    await query.answer()
    await query.message.edit_text(
        text,
        reply_markup=InlineKeyboardMarkup(
            [
                [InlineKeyboardButton("📊 Service stats", callback_data="status")],
                [InlineKeyboardButton("🏠 Main menu", callback_data="home")],
            ]
        ),
        link_preview_options=LinkPreviewOptions(is_disabled=True),
    )


async def get_bot_uptime(start_time: float) -> str:
    total_seconds = max(0, int(time.time() - start_time))
    days, remainder = divmod(total_seconds, 86_400)
    hours, remainder = divmod(remainder, 3_600)
    minutes, seconds = divmod(remainder, 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours or days:
        parts.append(f"{hours}h")
    if minutes or hours or days:
        parts.append(f"{minutes}m")
    parts.append(f"{seconds}s")
    return " ".join(parts)
