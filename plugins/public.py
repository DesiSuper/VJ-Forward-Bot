
import logging
import re
from html import escape

from pyrogram import Client, enums, filters
from pyrogram.errors.exceptions.bad_request_400 import (
    ChannelInvalid,
    ChannelPrivate,
    UsernameInvalid,
    UsernameNotModified,
)
from pyrogram.errors.exceptions.not_acceptable_406 import ChannelPrivate as PrivateChat
from pyrogram.types import InlineKeyboardMarkup

from database import db
from messages import Script

from .ui import InlineKeyboardButton
from .utils import STS

logger = logging.getLogger(__name__)


@Client.on_message(filters.private & filters.command(["forward"]))
async def run(bot, message):
    return await begin_forward(bot, message)


@Client.on_callback_query(filters.regex(r"^choose_destination#"))
async def choose_destination(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to choose a destination.", show_alert=True)
    selected = query.data.split("#", 1)[1]
    if selected == "cancel":
        await query.answer()
        return await query.message.edit_text("❌ Forward setup cancelled.")
    channels = await db.get_user_channels(user_id)
    destination = next((channel for channel in channels if str(channel["chat_id"]) == selected), None)
    if destination is None:
        return await query.answer("That destination is no longer available.", show_alert=True)
    await query.answer()
    await query.message.edit_text(f"✅ Destination selected: <b>{escape(str(destination['title']))}</b>")
    return await begin_forward(
        bot,
        query.message,
        user_id=user_id,
        selected_destination=(destination["chat_id"], destination["title"]),
    )


async def begin_forward(bot, message, user_id=None, selected_destination=None):
    """Run the forwarding setup flow from either /forward or the home menu."""
    user_id = user_id or message.from_user.id
    _bot = await db.get_bot(user_id)
    if not _bot:
      _bot = await db.get_userbot(user_id)
      if not _bot:
          return await message.reply("<b>No forwarding account is connected.</b> Add one in <code>/settings</code> to continue.")
    channels = await db.get_user_channels(user_id)
    if not channels:
       return await message.reply_text("<b>No destination is configured.</b> Add a destination in <code>/settings</code> first.")
    if selected_destination is not None:
       toid, to_title = selected_destination
    elif len(channels) > 1:
       buttons = [
           [InlineKeyboardButton(f"📣 {channel['title']}", callback_data=f"choose_destination#{channel['chat_id']}")]
           for channel in channels
       ]
       buttons.append([InlineKeyboardButton("❌ Cancel", callback_data="choose_destination#cancel")])
       return await message.reply_text(
           "<b>📣 Choose a destination</b>\nSelect where this task should forward messages.",
           reply_markup=InlineKeyboardMarkup(buttons),
       )
    else:
       toid = channels[0]['chat_id']
       to_title = channels[0]['title']
    try:
        fromid = await bot.ask(message.chat.id, Script.FROM_MSG, filters=filters.all, timeout=600)
    except TimeoutError:
        return await message.reply_text("<b>Source selection timed out.</b> Start again with <code>/forward</code>.")
    if fromid.text and fromid.text.strip().lower() == "/cancel":
        return await message.reply(Script.CANCEL)

    source_chat = getattr(fromid, "forward_from_chat", None)
    if fromid.text and not getattr(fromid, "forward_date", None):
        regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
        match = regex.match(fromid.text.strip().replace("?single", ""))
        if not match:
            return await message.reply('<b>That message link is invalid.</b> Send a valid Telegram message link.')
        chat_id = match.group(4)
        last_msg_id = int(match.group(5))
        if chat_id.isnumeric():
            chat_id = int("-100" + chat_id)
    elif source_chat and source_chat.type in {
        enums.ChatType.CHANNEL,
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
        enums.ChatType.FORUM,
    }:
        last_msg_id = getattr(fromid, "forward_from_message_id", None)
        if last_msg_id is None:
            return await message.reply_text(
                "<b>This forwarded message hides its original message ID.</b> Send a link to a message in that chat instead."
            )
        chat_id = source_chat.username or source_chat.id
    else:
        return await message.reply_text(
            "<b>Could not identify the source chat.</b> Forward a group/channel message or send its message link."
        )
    try:
        title = (await bot.get_chat(chat_id)).title
  #  except ChannelInvalid:
        #return await fromid.reply("**Given source chat is copyrighted channel/group. you can't forward messages from there**")
    except (PrivateChat, ChannelPrivate, ChannelInvalid):
        title = "private" if fromid.text else fromid.forward_from_chat.title
    except (UsernameInvalid, UsernameNotModified):
        return await message.reply('<b>That Telegram link could not be resolved.</b> Check it and try again.')
    except Exception:
        logger.exception("Could not resolve forwarding source for user %s", user_id)
        return await message.reply("<b>Could not load that chat.</b> Check the source link and connected account access.")
    try:
        skipno = await bot.ask(
            message.chat.id,
            Script.SKIP_MSG,
            filters=filters.text,
            timeout=600,
        )
    except TimeoutError:
        return await message.reply_text("<b>Setup timed out.</b> Start again with <code>/forward</code>.")
    if not skipno.text or skipno.text.strip().lower() == "/cancel":
        return await message.reply(Script.CANCEL)
    try:
        skip_count = int(skipno.text.strip())
        if skip_count < 0:
            raise ValueError
    except ValueError:
        return await skipno.reply_text(
            "<b>Enter a non-negative whole number</b> for messages to skip, or send <code>/cancel</code>."
        )
    forward_id = f"{user_id}-{skipno.id}"
    buttons = [[
        InlineKeyboardButton('🚀 Start forwarding', callback_data=f"start_public_{forward_id}"),
        InlineKeyboardButton('❌ Cancel', callback_data="close_btn")
    ]]
    reply_markup = InlineKeyboardMarkup(buttons)
    await message.reply_text(
        text=Script.DOUBLE_CHECK.format(
            botname=escape(str(_bot.get('name') or 'Connected account')),
            botuname=escape(str(_bot.get('username') or 'no username')),
            from_chat=escape(str(title)),
            to_chat=escape(str(to_title)),
            skip=escape(str(skip_count)),
        ),
        disable_web_page_preview=True,
        reply_markup=reply_markup
    )
    STS(forward_id).store(chat_id, toid, skip_count, int(last_msg_id))
