
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
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions

from database import db
from messages import Script

from .ui import InlineKeyboardButton
from .utils import STS, get_forward_origin, get_forwarded_chat
from .clients import get_client, update_configs
from .prompts import ask as prompt_for_input

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
    return await begin_forward(
        bot,
        query.message,
        user_id=user_id,
        selected_destination=(destination["chat_id"], destination["title"]),
    )


@Client.on_callback_query(filters.regex(r"^choose_source#"))
async def choose_source(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to choose a source.", show_alert=True)
    _, destination_id, source_id = query.data.split("#", 2)
    destination, source = await _get_saved_destination_source(user_id, destination_id, source_id)
    if destination is None or source is None:
        return await query.answer("That saved chat is no longer available.", show_alert=True)
    await query.answer()
    return await begin_forward(
        bot,
        query.message,
        user_id=user_id,
        selected_destination=(destination["chat_id"], destination["title"]),
        selected_source=source,
    )


@Client.on_callback_query(filters.regex(r"^add_source#"))
async def add_source(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to add a source.", show_alert=True)
    _, destination_id, mode = query.data.split("#", 2)
    destination = await _get_destination(user_id, destination_id)
    if destination is None:
        return await query.answer("That destination is no longer available.", show_alert=True)
    await query.answer()
    return await begin_forward(
        bot,
        query.message,
        user_id=user_id,
        selected_destination=(destination["chat_id"], destination["title"]),
        save_new_source=mode == "save",
    )


@Client.on_callback_query(filters.regex(r"^manage_sources#"))
async def manage_sources(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to manage sources.", show_alert=True)
    destination_id = query.data.split("#", 1)[1]
    destination = await _get_destination(user_id, destination_id)
    if destination is None:
        return await query.answer("That destination is no longer available.", show_alert=True)
    await query.answer()
    return await show_source_manager(query.message, user_id, destination)


@Client.on_callback_query(filters.regex(r"^back_to_sources#"))
async def back_to_sources(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to continue.", show_alert=True)
    destination = await _get_destination(user_id, query.data.split("#", 1)[1])
    if destination is None:
        return await query.answer("That destination is no longer available.", show_alert=True)
    sources = (await db.get_configs(user_id)).get("sources") or []
    await query.answer()
    return await query.message.edit_text(
        f"<b>📚 Choose a source for {escape(str(destination['title']))}</b>",
        reply_markup=source_picker_markup(sources, destination["chat_id"]),
    )


@Client.on_callback_query(filters.regex(r"^remove_source#"))
async def remove_source(bot, query):
    user_id = query.from_user.id
    if query.message.chat.id != user_id:
        return await query.answer("Open the bot in a private chat to manage sources.", show_alert=True)
    _, destination_id, source_id = query.data.split("#", 2)
    destination = await _get_destination(user_id, destination_id)
    if destination is None:
        return await query.answer("That destination is no longer available.", show_alert=True)
    configs = await db.get_configs(user_id)
    sources = configs.get("sources") or []
    sources = [source for source in sources if str(source.get("chat_id")) != source_id]
    await db.update_configs(user_id, {**configs, "sources": sources})
    await query.answer("Saved source removed.")
    return await show_source_manager(query.message, user_id, destination)


async def _get_destination(user_id, destination_id):
    channels = await db.get_user_channels(user_id)
    return next((item for item in channels if str(item["chat_id"]) == str(destination_id)), None)


async def _get_saved_destination_source(user_id, destination_id, source_id):
    destination = await _get_destination(user_id, destination_id)
    sources = (await db.get_configs(user_id)).get("sources") or []
    source = next((item for item in sources if str(item.get("chat_id")) == str(source_id)), None)
    return destination, source


def source_picker_markup(sources, destination_id):
    buttons = [
        [InlineKeyboardButton(
            f"📚 {escape(str(source.get('title') or source['chat_id']))}",
            callback_data=f"choose_source#{destination_id}#{source['chat_id']}",
        )]
        for source in sources
    ]
    buttons.extend(
        [
            [InlineKeyboardButton("➕ Add and save a new source", callback_data=f"add_source#{destination_id}#save")],
            [InlineKeyboardButton("🔗 Use another source once", callback_data=f"add_source#{destination_id}#once")],
            [InlineKeyboardButton("🗑️ Remove a saved source", callback_data=f"manage_sources#{destination_id}")],
            [InlineKeyboardButton("❌ Cancel", callback_data="choose_destination#cancel")],
        ]
    )
    return InlineKeyboardMarkup(buttons)


def source_manager_markup(sources, destination_id):
    buttons = [
        [InlineKeyboardButton(
            f"🗑️ {escape(str(source.get('title') or source['chat_id']))}",
            callback_data=f"remove_source#{destination_id}#{source['chat_id']}",
        )]
        for source in sources
    ]
    buttons.append([InlineKeyboardButton("⬅️ Keep sources / Back", callback_data=f"back_to_sources#{destination_id}")])
    return InlineKeyboardMarkup(buttons)


async def show_source_manager(message, user_id, destination):
    sources = (await db.get_configs(user_id)).get("sources") or []
    if not sources:
        return await message.edit_text(
            "<b>No saved sources.</b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back", callback_data=f"back_to_sources#{destination['chat_id']}")]]
            ),
        )
    return await message.edit_text(
        "<b>🗑️ Remove saved sources</b>\n\n"
        "Tap a source to delete it. Sources not selected here will be kept.",
        reply_markup=source_manager_markup(sources, destination["chat_id"]),
    )


async def latest_source_message_id(user_id, chat_id):
    """Find the latest message using the user's connected forwarding account."""
    account = await db.get_bot(user_id)
    if account is None:
        account = await db.get_userbot(user_id)
    if account is None:
        raise RuntimeError("No forwarding account is connected")

    is_bot = bool(account.get("is_bot"))
    session = account.get("token") if is_bot else account.get("session")
    if not session:
        raise RuntimeError("The saved forwarding account has no usable session")
    client = await get_client(session, is_bot=is_bot)
    started = False
    try:
        await client.start()
        started = True
        async for source_message in client.get_chat_history(chat_id, limit=1):
            return source_message.id
        return None
    finally:
        if started:
            await client.stop()


async def begin_forward(
    bot,
    message,
    user_id=None,
    selected_destination=None,
    selected_source=None,
    save_new_source=None,
):
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
    saved_sources = (await db.get_configs(user_id)).get("sources") or []
    if selected_source is None and save_new_source is None:
        if saved_sources:
            return await message.reply_text(
                "<b>📚 Choose a source channel</b>\n"
                "Pick a saved source, add another, or use a source once without saving it.",
                reply_markup=source_picker_markup(saved_sources, toid),
            )
        save_new_source = True

    if selected_source:
        chat_id = selected_source["chat_id"]
        source_id = selected_source["chat_id"]
        title = selected_source.get("title") or str(source_id)
        try:
            last_msg_id = await latest_source_message_id(user_id, chat_id)
        except Exception:
            logger.exception("Could not load the latest message from saved source for user %s", user_id)
            return await message.reply_text(
                "<b>Could not read this saved source.</b> Make sure the connected account can access it."
            )
        if last_msg_id is None:
            return await message.reply_text(
                "<b>No messages were found in this saved source.</b> Send a message to the channel first, then try again."
            )
    else:
        try:
            fromid = await prompt_for_input(
                bot, message.chat.id, Script.FROM_MSG, filters=filters.all, timeout=600
            )
        except TimeoutError:
            return await message.reply_text("<b>Source selection timed out.</b> Start again with <code>/forward</code>.")
        if fromid.text and fromid.text.strip().lower() == "/cancel":
            return await message.reply(Script.CANCEL)

        origin = get_forward_origin(fromid)
        source_chat = get_forwarded_chat(fromid)
        if fromid.text and not getattr(origin, "date", None):
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
            last_msg_id = getattr(origin, "message_id", None)
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
            resolved_source = await bot.get_chat(chat_id)
            source_id = resolved_source.id
            title = resolved_source.title or str(source_id)
        except (PrivateChat, ChannelPrivate, ChannelInvalid):
            source_id = source_chat.id if source_chat else chat_id
            title = source_chat.title if source_chat else str(source_id)
        except (UsernameInvalid, UsernameNotModified):
            return await message.reply('<b>That Telegram link could not be resolved.</b> Check it and try again.')
        except Exception:
            logger.exception("Could not resolve forwarding source for user %s", user_id)
            return await message.reply("<b>Could not load that chat.</b> Check the source link and connected account access.")

        if save_new_source:
            source = {"chat_id": source_id, "title": title}
            if not any(str(item.get("chat_id")) == str(source_id) for item in saved_sources):
                saved_sources.append(source)
                await update_configs(user_id, "sources", saved_sources)

    try:
        skipno = await prompt_for_input(bot,
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
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=reply_markup
    )
    STS(forward_id).store(chat_id, toid, skip_count, int(last_msg_id))
