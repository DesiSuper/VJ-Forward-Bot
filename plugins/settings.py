
import asyncio
import logging
from functools import wraps
from string import Formatter
from html import escape
from urllib.parse import urlsplit

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions

from .ui import InlineKeyboardButton

from database import db
from messages import Script
from message_filter_presets import MESSAGE_TYPES, filters_for_preset
from forwarding_delay import normalize_random_gap
from forward_review import PENDING_REVIEW, format_forwarding_settings

from .clients import CLIENT, get_configs, update_configs
from .db import connect_user_db
from .prompts import InputPromptAlreadyActive, ask as prompt_for_input
from .utils import get_forward_origin, get_forwarded_chat

CLIENT = CLIENT()
logger = logging.getLogger(__name__)


def validate_caption_template(template: str) -> None:
    """Allow only the documented named placeholders in caption templates."""
    allowed_fields = {"filename", "size", "caption"}
    for _, field_name, format_spec, conversion in Formatter().parse(template):
        if field_name is not None and (
            field_name not in allowed_fields or format_spec or conversion
        ):
            raise ValueError("Use only {filename}, {size}, and {caption} fields.")
    template.format(filename="", size="", caption="")


def valid_size_range(minimum: int, maximum: int) -> bool:
    """Zero disables a bound; active minimums must not exceed maximums."""
    return minimum <= 0 or maximum <= 0 or minimum <= maximum


def mongo_uri_summary(uri: str | None) -> str:
    """Show the host/path without credentials or query-string secrets."""
    try:
        parsed_uri = urlsplit(uri or "")
        hostname = parsed_uri.hostname or "saved MongoDB host"
        port = parsed_uri.port
    except ValueError:
        return "saved MongoDB host (URI needs correction)"
    address = f"{hostname}:{port}" if port else hostname
    scheme = parsed_uri.scheme if parsed_uri.scheme in {"mongodb", "mongodb+srv"} else "mongodb"
    return f"{scheme}://{address}{parsed_uri.path}"


def handle_active_prompt(handler):
    @wraps(handler)
    async def wrapped(bot, query):
        try:
            return await handler(bot, query)
        except InputPromptAlreadyActive:
            return await bot.send_message(
                query.from_user.id,
                "<b>An input prompt is already active.</b> Reply to it or send <code>/cancel</code> before starting another.",
            )

    return wrapped


@Client.on_message(filters.private & filters.command('settings'))
async def settings(client, message):
   task_id = PENDING_REVIEW.get(message.from_user.id)
   text, markup = await settings_dashboard(message.from_user.id, task_id)
   await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r'^settings'))
@handle_active_prompt
async def settings_query(bot, query):
  user_id = query.from_user.id
  i, type = query.data.split("#")
  buttons = [[InlineKeyboardButton('⬅️ Back', callback_data="settings#main")]]
  if type in {"main", "extra", "filters", "nextfilters"}:
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type in {"quick_settings", "filter_presets"}:
     config = await get_configs(user_id)
     text, markup = quick_settings_dashboard(config, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type in {"size_filter", "file_size", "maxfile_size"}:
     config = await get_configs(user_id)
     text, markup = size_filter_dashboard(config, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type in {"time_gap", "random_gap"}:
     config = await get_configs(user_id)
     text, markup = time_gap_dashboard(config, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("gap:"):
     _, minimum, maximum = type.split(":")
     gap = {"min": int(minimum), "max": int(maximum)}
     await update_configs(user_id, "random_gap", gap)
     config = await get_configs(user_id)
     text, markup = time_gap_dashboard(config, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type == "custom_gap":
     await query.answer()
     answer = await prompt_for_input(
         bot,
         user_id,
         "<b>Enter delay in seconds:</b> <code>5-15</code> random, <code>8</code> fixed, <code>0-0</code> off.\n"
         "Maximum: 3600. Send <code>/cancel</code> to stop.",
     )
     if not answer.text or answer.text.strip().lower() == "/cancel":
         return await answer.reply_text("<b>Gap setup cancelled.</b>")
     try:
         parts = answer.text.strip().split("-")
         if len(parts) == 1:
             minimum = maximum = int(parts[0])
         elif len(parts) == 2:
             minimum, maximum = (int(part.strip()) for part in parts)
         else:
             raise ValueError
         if minimum < 0 or maximum < minimum or maximum > 3600:
             raise ValueError
     except ValueError:
         return await answer.reply_text(
             "<b>Invalid range.</b> Enter a range such as <code>5-15</code>, "
             "or a fixed number from 0 to 3600."
         )
     await update_configs(user_id, "random_gap", {"min": minimum, "max": maximum})
     config = await get_configs(user_id)
     dashboard_text, dashboard_markup = time_gap_dashboard(
         config, PENDING_REVIEW.get(user_id)
     )
     return await answer.reply_text(dashboard_text, reply_markup=dashboard_markup)

  elif type=="bots":
     buttons = []
     _bot = await db.get_bot(user_id)
     usr_bot = await db.get_userbot(user_id)
     if _bot is not None:
        buttons.append([InlineKeyboardButton(f"🤖 {_bot['name']}",
                         callback_data="settings#editbot")])
     else:
        buttons.append([InlineKeyboardButton('🤖 Connect bot',
                         callback_data="settings#addbot")])
     if usr_bot is not None:
        buttons.append([InlineKeyboardButton(f"👤 {usr_bot['name']}",
                         callback_data="settings#edituserbot")])
     else:
        buttons.append([InlineKeyboardButton('👤 Connect user account',
                         callback_data="settings#adduserbot")])
     buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#main")])
     await query.message.edit_text(
       "<b>🤖 Connected accounts</b>\n\n"
       "Choose an account to manage it, or connect a bot or user account.",
       reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addbot":
     await query.answer("I’m opening the bot connection prompt in this chat.")
     # Keep the Accounts screen visible while the token prompt is sent. Deleting
     # it first left users with a blank chat if ask/listener setup failed.
     try:
        connected = await CLIENT.add_bot(bot, query)
     except InputPromptAlreadyActive:
        return await bot.send_message(
            user_id,
            "<b>A bot setup prompt is already open.</b> Reply to that prompt, or send <code>/cancel</code>, before starting another.",
        )
     except Exception:
        logger.exception("Could not start bot connection flow for user %s", user_id)
        return await bot.send_message(
            user_id,
            "<b>Could not open bot setup.</b> Please try again from Settings → Accounts.",
        )
     if connected is not True:
        return
     await bot.send_message(
        user_id,
        "<b>✓ Bot connected</b>\n\nYour bot account is ready to use.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('⬅️ Back to accounts', callback_data="settings#bots")]]
        ),
     )

  elif type=="adduserbot":
     await query.answer()
     connected = await CLIENT.add_session(bot, query)
     if connected is not True:
        return
     await bot.send_message(
        user_id,
        "<b>✓ User account connected</b>\n\nYour account is ready to use.",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton('⬅️ Back to accounts', callback_data="settings#bots")]]
        ),
     )

  elif type == "channels":
     destinations = await db.get_user_channels(user_id)
     sources = (await get_configs(user_id)).get("sources") or []
     destination_names = ", ".join(escape(str(item.get("title") or item["chat_id"])) for item in destinations[:4]) or "None saved"
     source_names = ", ".join(escape(str(item.get("title") or item["chat_id"])) for item in sources[:4]) or "None saved"
     buttons = [
         [InlineKeyboardButton(f"📥 Destination channels ({len(destinations)})", callback_data="settings#destinations")],
         [InlineKeyboardButton(f"📤 Source channels ({len(sources)})", callback_data="settings#sources")],
         [InlineKeyboardButton("⬅️ Back", callback_data="settings#main")],
     ]
     await query.message.edit_text(
         "<b>📣 Channels</b>\n\n"
         f"<b>Destinations:</b> {destination_names}\n"
         f"<b>Sources:</b> {source_names}\n\n"
         "Manage saved source and destination channels here.",
         reply_markup=InlineKeyboardMarkup(buttons),
     )

  elif type == "destinations":
     buttons = []
     channels = await db.get_user_channels(user_id)
     for channel in channels:
        buttons.append([InlineKeyboardButton(f"📣 {str(channel['title'])}",
                         callback_data=f"settings#editchannels_{channel['chat_id']}")])
     buttons.append([InlineKeyboardButton('➕ Add destination', callback_data="settings#addchannel")])
     buttons.append([InlineKeyboardButton('⬅️ Back to channels', callback_data="settings#channels")])
     await query.message.edit_text(
       "<b>📥 Destination channels</b>\n\n"
       "Saved destinations are listed below. Add or select one to manage it.",
       reply_markup=InlineKeyboardMarkup(buttons))

  elif type == "sources":
     sources = (await get_configs(user_id)).get("sources") or []
     buttons = [
         [InlineKeyboardButton(
             f"📤 {str(source.get('title') or source['chat_id'])}",
             callback_data=f"settings#editsource_{source['chat_id']}",
         )]
         for source in sources
     ]
     buttons.append([InlineKeyboardButton("➕ Add source channel", callback_data="settings#addsource")])
     buttons.append([InlineKeyboardButton("⬅️ Back to channels", callback_data="settings#channels")])
     source_lines = "\n".join(
         f"• {escape(str(source.get('title') or 'Untitled'))} — <code>{escape(str(source['chat_id']))}</code>"
         for source in sources
     ) or "No source channels saved yet."
     await query.message.edit_text(
         f"<b>📤 Source channels ({len(sources)})</b>\n\n{source_lines}\n\n"
         "Select a saved source to manage it or add another.",
         reply_markup=InlineKeyboardMarkup(buttons),
     )

  elif type == "addsource":
     await query.answer()
     try:
         source_message = await prompt_for_input(
             bot,
             user_id,
             "<b>Add a source channel</b>\n\n"
             "Forward any message from the channel or group you want to save.\n"
             "Send <code>/cancel</code> to stop.",
             filters=filters.all,
             timeout=600,
         )
     except asyncio.TimeoutError:
         return await bot.send_message(user_id, "<b>Source setup timed out.</b> Start again from Settings → Channels.")
     if (source_message.text or "").strip().lower() == "/cancel":
         return await source_message.reply_text(
             "<b>Source setup cancelled.</b>",
             reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ Back to sources", callback_data="settings#sources")]]),
         )
     origin = get_forward_origin(source_message)
     source_chat = get_forwarded_chat(source_message)
     if (
         not getattr(origin, "date", None)
         or source_chat is None
         or source_chat.type not in {
             enums.ChatType.CHANNEL,
             enums.ChatType.GROUP,
             enums.ChatType.SUPERGROUP,
             enums.ChatType.FORUM,
         }
     ):
         return await source_message.reply_text(
             "<b>That message was not forwarded from a source.</b> Forward a message from a channel or group."
         )
     source_id = source_chat.id
     sources = (await get_configs(user_id)).get("sources") or []
     source = next((item for item in sources if str(item.get("chat_id")) == str(source_id)), None)
     is_new_source = source is None
     if source is None:
         source = {"chat_id": source_id, "title": source_chat.title or str(source_id)}
         sources.append(source)
     source_message_id = getattr(origin, "message_id", None)
     if source_message_id is not None:
         source["last_message_id"] = int(source_message_id)
     await update_configs(user_id, "sources", sources)
     notice = "<b>✓ Source channel saved.</b>" if is_new_source else "<b>This source was already saved; its saved message point was refreshed.</b>"
     await source_message.reply_text(
         notice,
         reply_markup=InlineKeyboardMarkup([[InlineKeyboardButton("⬅️ View source channels", callback_data="settings#sources")]]),
     )

  elif type.startswith("editsource_"):
     source_id = type.split("_", 1)[1]
     sources = (await get_configs(user_id)).get("sources") or []
     source = next((item for item in sources if str(item.get("chat_id")) == source_id), None)
     if source is None:
         return await query.answer("That source is no longer saved.", show_alert=True)
     buttons = [
         [InlineKeyboardButton("🗑️ Remove source", callback_data=f"settings#removesource_{source_id}")],
         [InlineKeyboardButton("⬅️ Back to source channels", callback_data="settings#sources")],
     ]
     await query.message.edit_text(
         f"<b>📤 Source channel details</b>\n\n"
         f"<b>Name:</b> {escape(str(source.get('title') or 'Untitled'))}\n"
         f"<b>Chat ID:</b> <code>{escape(str(source_id))}</code>",
         reply_markup=InlineKeyboardMarkup(buttons),
     )

  elif type.startswith("removesource_"):
     source_id = type.split("_", 1)[1]
     configs = await get_configs(user_id)
     sources = [source for source in (configs.get("sources") or []) if str(source.get("chat_id")) != source_id]
     await db.update_configs(user_id, {**configs, "sources": sources})
     buttons = [[InlineKeyboardButton("⬅️ Back to source channels", callback_data="settings#sources")]]
     await query.message.edit_text("<b>✓ Source channel removed.</b>", reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addchannel":
     await query.answer()
     try:
         chat_ids = await prompt_for_input(bot,
             chat_id=user_id,
             text="<b>Add a destination</b>\n\nForward a message from the group or channel where the connected account can post.\nSend <code>/cancel</code> to stop.",
             timeout=600,
         )
     except asyncio.TimeoutError:
         return await bot.send_message(user_id, "<b>Destination setup timed out. Start again from Settings when ready.</b>")
     if not chat_ids.text or chat_ids.text.strip().lower() == "/cancel":
        return await chat_ids.reply_text(
            "<b>Setup cancelled.</b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to destination channels", callback_data="settings#destinations")]]
            ),
        )
     origin = get_forward_origin(chat_ids)
     if not getattr(origin, "date", None):
        return await chat_ids.reply_text(
            "<b>That message was not forwarded.</b> Forward a message from the target group or channel."
        )
     destination = get_forwarded_chat(chat_ids)
     if destination is None:
        return await chat_ids.reply_text(
            "<b>Could not identify a destination chat.</b> Forward a message from a group or channel."
        )
     chat_id = destination.id
     title = destination.title or str(chat_id)
     username = "@" + destination.username if destination.username else "private"
     chat = await db.add_channel(user_id, chat_id, title, username)
     await bot.send_message(
         user_id,
         "<b>✓ Destination added</b>" if chat else "<b>This destination is already saved.</b>",
         reply_markup=InlineKeyboardMarkup(
             [[InlineKeyboardButton('⬅️ Back to destination channels', callback_data="settings#destinations")]]
         ),
     )

  elif type=="editbot":
     bot = await db.get_bot(user_id)
     TEXT = Script.BOT_DETAILS if bot['is_bot'] else Script.USER_DETAILS
     buttons = [[InlineKeyboardButton('🗑️ Remove account', callback_data="settings#removebot")
               ],
               [InlineKeyboardButton('⬅️ Back', callback_data="settings#bots")]]
     await query.message.edit_text(
        TEXT.format(bot['name'], bot['id'], bot['username']),
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="edituserbot":
     bot = await db.get_userbot(user_id)
     TEXT = Script.USER_DETAILS
     buttons = [[InlineKeyboardButton('🗑️ Remove account', callback_data="settings#removeuserbot")
               ],
               [InlineKeyboardButton('⬅️ Back', callback_data="settings#bots")]]
     await query.message.edit_text(
        TEXT.format(bot['name'], bot['id'], bot['username']),
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="removebot":
     await db.remove_bot(user_id)
     await query.message.edit_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="removeuserbot":
     await db.remove_userbot(user_id)
     await query.message.edit_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type.startswith("editchannels"):
     chat_id = type.split('_')[1]
     chat = await db.get_channel_details(user_id, chat_id)
     buttons = [
         [InlineKeyboardButton('✏️ Change destination channel', callback_data=f"settings#changechannel_{chat_id}")],
         [InlineKeyboardButton('🗑️ Remove destination', callback_data=f"settings#removechannel_{chat_id}")],
         [InlineKeyboardButton('⬅️ Back', callback_data="settings#destinations")],
     ]
     await query.message.edit_text(
        f"<b>📣 Destination details</b>\n\n<b>Name:</b> <code>{escape(str(chat['title']))}</code>\n<b>Chat ID:</b> <code>{escape(str(chat['chat_id']))}</code>\n<b>Username:</b> {escape(str(chat['username'] or 'None'))}",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type.startswith("changechannel_"):
     old_chat_id = type.split("_", 1)[1]
     current = await db.get_channel_details(user_id, old_chat_id)
     if current is None:
        return await query.answer("That destination is no longer saved.", show_alert=True)
     await query.answer()
     try:
        forwarded = await prompt_for_input(
            bot,
            user_id,
            "<b>Change destination</b>\n\n"
            "Forward a message from the new chat. Your account must be able to post there.\n"
            "Send <code>/cancel</code> to keep the current one.",
            filters=filters.all,
            timeout=600,
        )
     except asyncio.TimeoutError:
        return await bot.send_message(
            user_id,
            "<b>Destination change timed out.</b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to channels", callback_data="settings#destinations")]]
            ),
        )
     if (forwarded.text or "").strip().lower() == "/cancel":
        return await forwarded.reply_text(
            "<b>Destination change cancelled. Your saved channel is unchanged.</b>",
            reply_markup=InlineKeyboardMarkup(
                [[InlineKeyboardButton("⬅️ Back to channels", callback_data="settings#destinations")]]
            ),
        )
     origin = get_forward_origin(forwarded)
     new_destination = get_forwarded_chat(forwarded)
     if (
         not getattr(origin, "date", None)
         or new_destination is None
         or new_destination.type not in {
             enums.ChatType.CHANNEL,
             enums.ChatType.GROUP,
             enums.ChatType.SUPERGROUP,
             enums.ChatType.FORUM,
         }
     ):
        return await forwarded.reply_text(
            "<b>That message was not forwarded from a group or channel.</b> The saved destination is unchanged."
        )
     new_id = new_destination.id
     title = new_destination.title or str(new_id)
     username = "@" + new_destination.username if new_destination.username else "private"
     updated = await db.update_channel(user_id, int(old_chat_id), new_id, title, username)
     result_text = (
         "<b>✓ Destination channel changed.</b>"
         if updated
         else "<b>This channel is already saved as another destination.</b> The current destination was not changed."
     )
     return await forwarded.reply_text(
         result_text,
         reply_markup=InlineKeyboardMarkup(
             [[InlineKeyboardButton("⬅️ View destination channels", callback_data="settings#destinations")]]
         ),
     )

  elif type.startswith("removechannel"):
     chat_id = type.split('_')[1]
     await db.remove_channel(user_id, chat_id)
     await query.message.edit_text(
        "<b>✓ Destination removed.</b>",
        reply_markup=InlineKeyboardMarkup(
            [[InlineKeyboardButton("⬅️ Back to destination channels", callback_data="settings#destinations")]]
        ))

  elif type=="caption":
     buttons = []
     data = await get_configs(user_id)
     caption = data['caption']
     if caption is None:
        buttons.append([InlineKeyboardButton('➕ Add caption',
                      callback_data="settings#addcaption")])
     else:
        buttons.append([InlineKeyboardButton('👁️ View caption',
                      callback_data="settings#seecaption")])
        buttons[-1].append(InlineKeyboardButton('🗑️ Remove caption',
                      callback_data="settings#deletecaption"))
     buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#main")])
     await query.message.edit_text(
        "<b>📝 Custom caption</b>\n\nSet a caption template for forwarded media. Available fields: <code>{filename}</code>, <code>{size}</code>, and <code>{caption}</code>.",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="seecaption":
     data = await get_configs(user_id)
     buttons = [[InlineKeyboardButton('✏️ Edit caption',
                  callback_data="settings#addcaption")
               ],[
               InlineKeyboardButton('⬅️ Back',
                 callback_data="settings#caption")]]
     await query.message.edit_text(
        f"<b>Saved caption</b>\n\n<code>{escape(str(data['caption']))}</code>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="deletecaption":
     await update_configs(user_id, 'caption', None)
     await query.message.edit_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addcaption":
     caption = await prompt_for_input(bot, query.message.chat.id, "<b>Send your caption template.</b>\nUse <code>{filename}</code>, <code>{size}</code>, or <code>{caption}</code> as needed.\nSend <code>/cancel</code> to stop.")
     template = getattr(caption, "text", None)
     if not template:
        return await caption.reply_text(
            "<b>Please send a text caption template.</b>",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
     if template.strip().lower() == "/cancel":
        return await caption.reply_text(
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
     try:
         validate_caption_template(template)
     except (KeyError, IndexError, ValueError) as error:
         return await caption.reply_text(
            f"<b>Invalid caption template:</b> <code>{escape(str(error))}</code>\nUse only the named fields shown above.",
            reply_markup=InlineKeyboardMarkup(buttons))
     await update_configs(user_id, 'caption', template)
     await caption.reply_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type in {"button", "addbutton", "seebutton", "deletebutton"}:
     return await query.answer("Custom message buttons have been removed.", show_alert=True)

  elif type=="database":
     buttons = []
     db_uri = (await get_configs(user_id))['db_uri']
     if db_uri is None:
        buttons.append([InlineKeyboardButton('➕ Add database URI',
                      callback_data="settings#addurl")])
     else:
        buttons.append([InlineKeyboardButton('👁️ View database URI',
                      callback_data="settings#seeurl")])
        buttons[-1].append(InlineKeyboardButton('🗑️ Remove database URI',
                      callback_data="settings#deleteurl"))
     buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#main")])
     await query.message.edit_text(
        "<b>🗄 Custom duplicate database</b>\n\nConnect a MongoDB database to keep duplicate-file records across bot restarts. This is optional.",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addurl":
     uri = await prompt_for_input(
         bot,
         user_id,
         "<b>Send your MongoDB connection URI.</b>\n\nThe URI is stored encrypted in your bot settings. Send <code>/cancel</code> to stop.",
         link_preview_options=LinkPreviewOptions(is_disabled=True),
         delete_prompt_and_reply=True,
     )
     uri_text = getattr(uri, "text", None)
     if not uri_text:
        return await bot.send_message(user_id, "<b>Please send a MongoDB URI as text.</b>", reply_markup=InlineKeyboardMarkup(buttons))
     if uri_text.strip().lower() == "/cancel":
        return await bot.send_message(
                  user_id,
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
     try:
        parsed_uri = urlsplit(uri_text.strip())
        valid_uri = (
            parsed_uri.scheme in {"mongodb", "mongodb+srv"}
            and bool(parsed_uri.hostname)
            and (parsed_uri.port is None or 1 <= parsed_uri.port <= 65535)
        )
     except ValueError:
        valid_uri = False
     if not valid_uri:
        return await bot.send_message(
            user_id,
            "<b>Invalid MongoDB URI.</b> Use a valid <code>mongodb://</code> or <code>mongodb+srv://</code> URI.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
     connect, udb = await connect_user_db(user_id, uri_text.strip(), "test")
     if connect:
        await udb.close()
     else:
        return await bot.send_message(
            user_id,
            "<b>Could not connect to MongoDB.</b> Check the URI and network permissions.",
            reply_markup=InlineKeyboardMarkup(buttons),
        )
     await update_configs(user_id, 'db_uri', uri_text.strip())
     await bot.send_message(
         user_id,
         "<b>✓ Database connected.</b>",
         reply_markup=InlineKeyboardMarkup(buttons),
     )

  elif type=="seeurl":
     db_uri = (await get_configs(user_id))['db_uri']
     await query.answer(
         f"MongoDB URI configured for: {mongo_uri_summary(db_uri)}",
         show_alert=True,
     )

  elif type=="deleteurl":
     await update_configs(user_id, 'db_uri', None)
     await query.message.edit_text(
        "<b>✓ Database URI removed.</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type.startswith("filterpreset:"):
     preset = type.split(":", 1)[1]
     try:
        updated_filters = filters_for_preset(preset)
     except ValueError:
        return await query.answer("Unknown message-type preset.", show_alert=True)
     configs = await get_configs(user_id)
     configs["filters"].update(updated_filters)
     for disabled_type in ("voice", "animation", "sticker", "poll"):
        configs["filters"][disabled_type] = False
     await db.update_configs(user_id, configs)
     text, markup = quick_settings_dashboard(configs, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("updatefilter"):
     _, key, value = type.split('-')
     if key in {"voice", "animation", "sticker", "poll", "button"}:
        return await query.answer("This option has been removed.", show_alert=True)
     await update_configs(user_id, key, value != "True")
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("update_size:"):
    size = int(type.split(":", 1)[1])
    if not 0 <= size <= 4000:
      return await query.answer("Choose a size from 0 to 4000 MB.", show_alert=True)
    config = await get_configs(user_id)
    if not valid_size_range(size, int(config.get("max_size") or 0)):
      return await query.answer("Minimum size cannot exceed the current maximum size.", show_alert=True)
    await update_configs(user_id, "min_size", size)
    config = await get_configs(user_id)
    text, markup = size_filter_dashboard(config, PENDING_REVIEW.get(user_id))
    return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("maxupdate_size:"):
    size = int(type.split(":", 1)[1])
    if not 0 <= size <= 4000:
      return await query.answer("Choose a size from 0 to 4000 MB.", show_alert=True)
    config = await get_configs(user_id)
    if not valid_size_range(int(config.get("min_size") or 0), size):
      return await query.answer("Maximum size cannot be below the current minimum size.", show_alert=True)
    await update_configs(user_id, "max_size", size)
    config = await get_configs(user_id)
    text, markup = size_filter_dashboard(config, PENDING_REVIEW.get(user_id))
    return await query.message.edit_text(text, reply_markup=markup)

  elif type == "add_extension":
    ext = await prompt_for_input(bot, user_id, text="<b>Enter file extensions separated by spaces.</b>\nExample: <code>mkv zip pdf</code>\nSend <code>/cancel</code> to stop.")
    if ext.text == '/cancel':
       return await ext.reply_text(
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
    extensions = ext.text.split(" ")
    extension = (await get_configs(user_id))['extension']
    if extension:
        for extn in extensions:
            extension.append(extn)
    else:
        extension = extensions
    await update_configs(user_id, 'extension', extension)
    buttons = []
    buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#get_extension")])
    await ext.reply_text(
        "<b>✓ Changes saved.</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type == "get_extension":
    extensions = (await get_configs(user_id))['extension']
    btn = []
    text = ""
    if extensions:
       text += "<b>Saved extensions</b>"
       for ext in extensions:
          text += f"\n• <code>{escape(str(ext))}</code>"
    else:
       text += "<i>No extensions are excluded.</i>"
    btn.append([InlineKeyboardButton('➕ Add', callback_data='settings#add_extension')])
    btn.append([InlineKeyboardButton('🧹 Clear all', callback_data='settings#rmve_all_extension')])
    btn.append([InlineKeyboardButton('⬅️ Back', callback_data='settings#main')])
    await query.message.edit_text(
        text=f"<b>📎 Excluded extensions</b>\n\nFiles matching these extensions will be skipped.\n\n{text}",
        reply_markup=InlineKeyboardMarkup(btn))

  elif type == "rmve_all_extension":
    await update_configs(user_id, 'extension', None)
    buttons = []
    buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#get_extension")])
    await query.message.edit_text(text="<b>✓ List cleared.</b>",
                                   reply_markup=InlineKeyboardMarkup(buttons))
  elif type == "add_keyword":
    ask = await prompt_for_input(bot, user_id, text="<b>Enter keywords separated by spaces.</b>\nFiles whose names contain these words will be skipped.\nSend <code>/cancel</code> to stop.")
    if ask.text == '/cancel':
       return await ask.reply_text(
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
    keywords = ask.text.split(" ")
    keyword = (await get_configs(user_id))['keywords']
    if keyword:
        for word in keywords:
            keyword.append(word)
    else:
        keyword = keywords
    await update_configs(user_id, 'keywords', keyword)
    buttons = []
    buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#get_keyword")])
    await ask.reply_text(
        "<b>✓ Changes saved.</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type == "get_keyword":
    keywords = (await get_configs(user_id))['keywords']
    btn = []
    text = ""
    if keywords:
       text += "<b>Saved keywords</b>"
       for key in keywords:
          text += f"\n• <code>{escape(str(key))}</code>"
    else:
       text += "<i>No keywords are excluded.</i>"
    btn.append([InlineKeyboardButton('➕ Add', callback_data='settings#add_keyword')])
    btn.append([InlineKeyboardButton('🧹 Clear all', callback_data='settings#rmve_all_keyword')])
    btn.append([InlineKeyboardButton('⬅️ Back', callback_data='settings#main')])
    await query.message.edit_text(
        text=f"<b>🔑 Excluded keywords</b>\n\nFiles with these words in their names will be skipped.\n\n{text}",
        reply_markup=InlineKeyboardMarkup(btn))

  elif type == "rmve_all_keyword":
    await update_configs(user_id, 'keywords', None)
    buttons = []
    buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#get_keyword")])
    await query.message.edit_text(text="<b>✓ Keywords cleared.</b>",
                                   reply_markup=InlineKeyboardMarkup(buttons))


async def settings_dashboard(user_id, continue_task_id=None):
    config = await get_configs(user_id)
    connected_bot = await db.get_bot(user_id)
    connected_user = await db.get_userbot(user_id)
    destinations = await db.get_user_channels(user_id)
    account = connected_bot or connected_user
    if account:
        account_name = escape(str(account.get("name") or "Connected"))
        account_kind = "Bot" if connected_bot else "User account"
        account_summary = f"{account_kind}: {account_name}"
    else:
        account_summary = "Not connected"
    destination_names = [escape(str(item.get("title") or item.get("chat_id"))) for item in destinations]
    destination_summary = ", ".join(destination_names[:3]) or "None"
    if len(destination_names) > 3:
        destination_summary += f" and {len(destination_names) - 3} more"
    sources = config.get("sources") or []
    source_names = [escape(str(item.get("title") or item.get("chat_id"))) for item in sources]
    source_summary = ", ".join(source_names[:3]) or "None"
    if len(source_names) > 3:
        source_summary += f" and {len(source_names) - 3} more"

    text = (
        "<b>⚙️ All forwarding settings</b>\n\n"
        f"<b>Account:</b> {account_summary}\n"
        f"<b>Destination channels ({len(destinations)}):</b> {destination_summary}\n"
        f"<b>Source channels ({len(sources)}):</b> {source_summary}\n\n"
        f"{format_forwarding_settings(config)}\n\n"
        "Tap a setting below to change it. Changes save immediately."
    )

    selected_filters = config.get("filters") or {}
    keyboard = [
        [
            InlineKeyboardButton("🤖 Accounts", callback_data="settings#bots"),
            InlineKeyboardButton("📣 Channels", callback_data="settings#channels"),
        ],
        [
            message_type_toggle("📝 Text", selected_filters.get("text", True), "text"),
            message_type_toggle("📁 Documents", selected_filters.get("document", True), "document"),
        ],
        [
            message_type_toggle("🎞️ Videos", selected_filters.get("video", True), "video"),
            message_type_toggle("📷 Photos", selected_filters.get("photo", True), "photo"),
        ],
        [
            message_type_toggle("🎧 Audio", selected_filters.get("audio", True), "audio"),
            message_type_toggle("🔘 Video notes", selected_filters.get("video_note", True), "video_note"),
        ],
        [InlineKeyboardButton("⚡ Quick settings", callback_data="settings#quick_settings")],
        [
            message_type_toggle("↪️ Forward original", config.get("forward_tag", False), "forward_tag"),
            message_type_toggle("🧹 Skip duplicates", config.get("duplicate", True), "duplicate"),
        ],
        [message_type_toggle("🔒 Protect content", config.get("protect", False), "protect")],
        [InlineKeyboardButton("📝 Caption", callback_data="settings#caption")],
        [
            InlineKeyboardButton("📦 Size filter", callback_data="settings#size_filter"),
            InlineKeyboardButton("⏱️ Time gap", callback_data="settings#time_gap"),
        ],
        [
            InlineKeyboardButton("🔑 Keywords", callback_data="settings#get_keyword"),
            InlineKeyboardButton("📎 Extensions", callback_data="settings#get_extension"),
        ],
        [InlineKeyboardButton("🗄 Duplicate database", callback_data="settings#database")],
    ]
    if continue_task_id:
        append_task_controls(keyboard, continue_task_id)
    else:
        keyboard.append([InlineKeyboardButton("🏠 Main menu", callback_data="home")])
    return text, InlineKeyboardMarkup(keyboard)


def quick_settings_dashboard(config, continue_task_id=None):
    current_filters = config.get("filters") or {}
    preset_options = (
        ("all", "🌐 All supported", filters_for_preset("all")),
        ("media", "🖼️ Media only", filters_for_preset("media")),
        ("video_photo_audio", "🎞️📷🎧 Video, photo & audio", filters_for_preset("video_photo_audio")),
    )
    selected_preset = next(
        (
            name
            for name, _, preset_filters in preset_options
            if all(current_filters.get(message_type, True) == preset_filters[message_type]
                   for message_type in MESSAGE_TYPES)
        ),
        None,
    )
    type_labels = {
        "text": "Text",
        "document": "Documents",
        "video": "Videos",
        "photo": "Photos",
        "audio": "Audio",
        "video_note": "Video notes",
    }
    selected_types = [
        type_labels[message_type]
        for message_type in MESSAGE_TYPES
        if current_filters.get(message_type, True)
    ]
    keyboard = [
        [
            InlineKeyboardButton(
                f"✅ {label}" if selected_preset == name else label,
                callback_data=f"settings#filterpreset:{name}",
            )
        ]
        for name, label, _ in preset_options
    ]
    keyboard.append([InlineKeyboardButton("⬅️ Back to all settings", callback_data="settings#main")])
    if not continue_task_id:
        keyboard.append([InlineKeyboardButton("🏠 Main menu", callback_data="home")])
    text = (
        "<b>⚡ Quick settings</b>\n\n"
        "Choose a preset or adjust message types in Settings.\n\n"
        f"<b>Currently included:</b> {', '.join(selected_types) or 'None'}"
    )
    return text, InlineKeyboardMarkup(keyboard)


def size_filter_dashboard(config, continue_task_id=None):
    minimum = max(0, int(config.get("min_size") or 0))
    maximum = max(0, int(config.get("max_size") or 0))
    keyboard = [
        [
            InlineKeyboardButton("Min −5 MB", callback_data=f"settings#update_size:{max(0, minimum - 5)}"),
            InlineKeyboardButton("Min +5 MB", callback_data=f"settings#update_size:{min(4000, minimum + 5)}"),
            InlineKeyboardButton("Clear min", callback_data="settings#update_size:0"),
        ],
        [
            InlineKeyboardButton("Max −5 MB", callback_data=f"settings#maxupdate_size:{max(0, maximum - 5)}"),
            InlineKeyboardButton("Max +5 MB", callback_data=f"settings#maxupdate_size:{min(4000, maximum + 5)}"),
            InlineKeyboardButton("Clear max", callback_data="settings#maxupdate_size:0"),
        ],
        [InlineKeyboardButton("⬅️ Back to all settings", callback_data="settings#main")],
    ]
    if not continue_task_id:
        keyboard.append([InlineKeyboardButton("🏠 Main menu", callback_data="home")])
    text = (
        "<b>📦 Size filter</b>\n\n"
        f"<b>Minimum:</b> {minimum} MB\n"
        f"<b>Maximum:</b> {maximum} MB\n\n"
        "Files smaller than the minimum or larger than the maximum are skipped. "
        "Set either value to 0 for no limit. Each tap changes the limit by 5 MB."
    )
    return text, InlineKeyboardMarkup(keyboard)


def time_gap_dashboard(config, continue_task_id=None):
    gap_min, gap_max = normalize_random_gap(config.get("random_gap"))
    presets = ((0, 0, "⏸️ Off"), (1, 3, "⏱️ 1–3 sec"), (3, 7, "⏱️ 3–7 sec"), (5, 15, "⏱️ 5–15 sec"))
    keyboard = [
        [
            InlineKeyboardButton(
                f"✅ {label}" if (gap_min, gap_max) == (minimum, maximum) else label,
                callback_data=f"settings#gap:{minimum}:{maximum}",
            )
            for minimum, maximum, label in presets[:2]
        ],
        [
            InlineKeyboardButton(
                f"✅ {label}" if (gap_min, gap_max) == (minimum, maximum) else label,
                callback_data=f"settings#gap:{minimum}:{maximum}",
            )
            for minimum, maximum, label in presets[2:]
        ],
        [InlineKeyboardButton("✎ Custom delay", callback_data="settings#custom_gap")],
        [InlineKeyboardButton("⬅️ Back to all settings", callback_data="settings#main")],
    ]
    if not continue_task_id:
        keyboard.append([InlineKeyboardButton("🏠 Main menu", callback_data="home")])
    if gap_min == gap_max == 0:
        current = "Off"
    elif gap_min == gap_max:
        current = f"{gap_min} seconds (fixed)"
    else:
        current = f"{gap_min}–{gap_max} seconds (random)"
    text = (
        "<b>⏱️ Time gap</b>\n\n"
        f"Current delay: <b>{current}</b>\n"
        "Choose a preset or enter a custom delay between forwarded messages."
    )
    return text, InlineKeyboardMarkup(keyboard)


def append_task_controls(keyboard, task_id):
    """Keep one exit to task review on the main settings screen only."""
    keyboard.append(
        [InlineKeyboardButton("↩️ Back to task review", callback_data=f"review_public_{task_id}")]
    )


def message_type_toggle(label, enabled, key):
  state = "✅" if enabled else "🚫"
  return InlineKeyboardButton(
      f"{state} {label}",
      callback_data=f"settings#updatefilter-{key}-{enabled}",
  )
