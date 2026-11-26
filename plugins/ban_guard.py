"""Restrict private bot interactions and callbacks to the configured owner."""

from html import escape

from pyrogram import Client, StopPropagation, filters

from config import Config, temp
from database import db


@Client.on_message(filters.private, group=-2)
async def block_banned_messages(client, message):
    user = getattr(message, "from_user", None)
    if user is None:
        return
    status = await db.get_ban_status(user.id)
    if status.get("is_banned") or user.id in temp.BANNED_USERS:
        reason = status.get("ban_reason") or "No reason provided"
        await message.reply_text(
            f"<b>Access to this bot is restricted.</b>\n{escape(str(reason))}"
        )
        raise StopPropagation
    if not Config.is_bot_owner(user.id):
        raise StopPropagation


@Client.on_callback_query(group=-2)
async def block_banned_callbacks(client, query):
    user = getattr(query, "from_user", None)
    if user is None:
        return
    status = await db.get_ban_status(user.id)
    if status.get("is_banned") or user.id in temp.BANNED_USERS:
        await query.answer("Access to this bot is restricted.", show_alert=True)
        raise StopPropagation
    if not Config.is_bot_owner(user.id):
        await query.answer()
        raise StopPropagation
