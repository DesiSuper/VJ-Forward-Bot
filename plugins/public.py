
import logging
import re
from functools import partial
from html import escape
from types import SimpleNamespace

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
from forward_review import format_forwarding_settings
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
    await query.message.edit_text("<b>Destination selected. Preparing source selection…</b>")
    return await begin_forward(
        bot,
        _editing_message_context(query, bot),
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
    await query.message.edit_text(
        f"<b>Source selected:</b> {escape(str(source.get('title') or 'Saved channel'))}\n"
        "Preparing forwarding setup…"
    )
    return await begin_forward(
        bot,
        _editing_message_context(query, bot),
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
    await query.message.edit_text("<b>Waiting for the new source channel…</b>")
    return await begin_forward(
        bot,
        _editing_message_context(query, bot),
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


def _editing_message_context(query, bot):
    return SimpleNamespace(
        from_user=query.from_user,
        chat=query.message.chat,
        reply=query.message.edit_text,
        reply_text=query.message.edit_text,
        setup_message=query.message,
        confirmation_reply=partial(bot.send_message, query.message.chat.id),
    )


async def _clear_setup_menu(message, user_id):
    setup_message = getattr(message, "setup_message", None)
    if setup_message is None:
        return
    try:
        await setup_message.delete()
    except Exception:
        logger.warning("Could not remove temporary forwarding menu for user %s", user_id)
        try:
            await setup_message.edit_text("<b>Setup updated. Continue in the latest message.</b>")
        except Exception:
            logger.debug("Could not clear temporary forwarding menu for user %s", user_id)


async def _get_destination(user_id, destination_id):
    channels = await db.get_user_channels(user_id)
    return next((item for item in channels if str(item["chat_id"]) == str(destination_id)), None)


async def _get_saved_destination_source(user_id, destination_id, source_id):
    destination = await _get_destination(user_id, destination_id)
    sources = (await db.get_configs(user_id)).get("sources") or []
    source = next((item for item in sources if str(item.get("chat_id")) == str(source_id)), None)
    return destination, source


async def _remember_source_message_id(user_id, sources, source_id, message_id):
    source = next((item for item in sources if str(item.get("chat_id")) == str(source_id)), None)
    if source is None or source.get("last_message_id") == message_id:
        return
    source["last_message_id"] = int(message_id)
    await update_configs(user_id, "sources", sources)


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
    user_config = await db.get_configs(user_id)
    saved_sources = user_config.get("sources") or []
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
            logger.warning(
                "Could not automatically read latest message from saved source for user %s; using its saved checkpoint if available",
                user_id,
                exc_info=True,
            )
            last_msg_id = None
        if last_msg_id is not None:
            await _remember_source_message_id(user_id, saved_sources, source_id, last_msg_id)
        elif selected_source.get("last_message_id") is not None:
            last_msg_id = int(selected_source["last_message_id"])
        if last_msg_id is None:
            try:
                endpoint_message = await prompt_for_input(
                    bot,
                    message.chat.id,
                    "<b>Source channel selected.</b> I could not fetch its latest message automatically. "
                    "Forward any recent message from this saved channel to continue.\n"
                    "Send <code>/cancel</code> to stop.",
                    filters=filters.all,
                    timeout=600,
                    delete_prompt_and_reply=True,
                )
            except TimeoutError:
                return await message.reply_text("<b>Source selection timed out.</b> Start again with <code>/forward</code>.")
            if (endpoint_message.text or "").strip().lower() == "/cancel":
                return await message.reply(Script.CANCEL)
            endpoint_origin = get_forward_origin(endpoint_message)
            endpoint_chat = get_forwarded_chat(endpoint_message)
            if (
                not getattr(endpoint_origin, "date", None)
                or endpoint_chat is None
                or str(endpoint_chat.id) != str(chat_id)
            ):
                return await message.reply_text(
                    "<b>That message is not from the saved source.</b> Forward a message from the selected channel."
                )
            last_msg_id = getattr(endpoint_origin, "message_id", None)
            if last_msg_id is None:
                return await message.reply_text(
                    "<b>This forwarded message hides its original ID.</b> Try another message from the saved source."
                )
            await _remember_source_message_id(user_id, saved_sources, source_id, last_msg_id)
    else:
        try:
            fromid = await prompt_for_input(
                bot,
                message.chat.id,
                Script.FROM_MSG,
                filters=filters.all,
                timeout=600,
                delete_prompt_and_reply=True,
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
            source = next(
                (item for item in saved_sources if str(item.get("chat_id")) == str(source_id)),
                None,
            )
            if source is None:
                source = {"chat_id": source_id, "title": title}
                saved_sources.append(source)
            source["title"] = title
            source["last_message_id"] = int(last_msg_id)
            await update_configs(user_id, "sources", saved_sources)

    review_data = {
        "botname": str(_bot.get("name") or "Connected account"),
        "botuname": str(_bot.get("username") or "no username"),
        "from_chat": str(title),
        "to_chat": str(to_title),
    }
    skip_prompt_text = (
        "<b>Forwarding setup</b>\n\n"
        f"<b>Account:</b> {escape(review_data['botname'])} (@{escape(review_data['botuname'])})\n"
        f"<b>Source:</b> {escape(review_data['from_chat'])}\n"
        f"<b>Destination:</b> {escape(review_data['to_chat'])}\n\n"
        f"{format_forwarding_settings(user_config)}\n\n"
        "<b>Messages to skip:</b> enter a number (default: <code>0</code>).\n"
        "Tap <b>Start (skip 0)</b> to start now, or open Settings."
    )
    try:
        skipno, skip_prompt = await prompt_for_input(
            bot,
            message.chat.id,
            skip_prompt_text,
            filters=filters.text,
            timeout=600,
            callback_choices={
                "🚀 Start (skip 0)": "0",
                "⚙️ Settings": "__settings__",
                "❌ Cancel": "__cancel__",
            },
            return_prompt=True,
            defer_callback_answer=True,
        )
    except TimeoutError:
        return await message.reply_text("<b>Setup timed out.</b> Start again with <code>/forward</code>.")
    if getattr(skipno, "from_callback", False) and skipno.text == "__cancel__":
        await _clear_setup_menu(message, user_id)
        await skipno.callback_query.answer("Forward setup cancelled.")
        return await skip_prompt.edit_text(Script.CANCEL, reply_markup=None)
    if not skipno.text or skipno.text.strip().lower() == "/cancel":
        try:
            await bot.delete_messages(message.chat.id, [skip_prompt.id, skipno.id])
        except Exception:
            logger.debug("Could not remove cancelled skip prompt for user %s", user_id, exc_info=True)
        await _clear_setup_menu(message, user_id)
        return await message.reply(Script.CANCEL)
    try:
        skip_count = (
            0
            if getattr(skipno, "from_callback", False) and skipno.text == "__settings__"
            else int(skipno.text.strip())
        )
        if skip_count < 0:
            raise ValueError
    except ValueError:
        try:
            await bot.delete_messages(message.chat.id, [skip_prompt.id, skipno.id])
        except Exception:
            logger.debug("Could not remove invalid skip prompt for user %s", user_id, exc_info=True)
        return await skipno.reply_text(
            "<b>Enter a non-negative whole number</b> for messages to skip, or send <code>/cancel</code>."
        )

    forward_id = f"{user_id}-{skipno.id}"
    STS(forward_id).store(
        chat_id,
        toid,
        skip_count,
        int(last_msg_id),
    )
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🚀 Start forwarding", callback_data=f"continue_public_{forward_id}"),
                InlineKeyboardButton("⚙️ Settings", callback_data=f"start_public_{forward_id}"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_public_{forward_id}")],
        ]
    )
    confirmation_text = Script.DOUBLE_CHECK.format(
        botname=escape(review_data["botname"]),
        botuname=escape(review_data["botuname"]),
        from_chat=escape(review_data["from_chat"]),
        to_chat=escape(review_data["to_chat"]),
        skip=escape(str(skip_count)),
    )

    await _clear_setup_menu(message, user_id)

    if getattr(skipno, "from_callback", False):
        callback_query = skipno.callback_query
        routed_query = SimpleNamespace(
            from_user=callback_query.from_user,
            message=callback_query.message,
            answer=callback_query.answer,
        )
        if skipno.text == "__settings__":
            from .forwarding import review_forwarding_task

            routed_query.data = f"start_public_{forward_id}"
            return await review_forwarding_task(bot, routed_query)
        from .forwarding import pub_

        routed_query.data = f"continue_public_{forward_id}"
        return await pub_(bot, routed_query)

    try:
        await bot.delete_messages(message.chat.id, [skipno.id])
    except Exception:
        logger.debug("Could not remove typed skip count for user %s", user_id, exc_info=True)
    return await skip_prompt.edit_text(
        confirmation_text,
        link_preview_options=LinkPreviewOptions(is_disabled=True),
        reply_markup=reply_markup,
    )
