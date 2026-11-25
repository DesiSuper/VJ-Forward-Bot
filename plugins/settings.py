
import asyncio
import logging
from html import escape

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions

from .ui import InlineKeyboardButton

from database import db
from messages import Script
from message_filter_presets import filters_for_preset
from forwarding_delay import normalize_random_gap
from forward_review import PENDING_REVIEW, format_forwarding_settings

from .clients import CLIENT, get_configs, update_configs
from .db import connect_user_db
from .prompts import InputPromptAlreadyActive, ask as prompt_for_input
from .utils import get_forward_origin, get_forwarded_chat

CLIENT = CLIENT()
logger = logging.getLogger(__name__)


@Client.on_message(filters.private & filters.command('settings'))
async def settings(client, message):
   task_id = PENDING_REVIEW.get(message.from_user.id)
   text, markup = await settings_dashboard(message.from_user.id, task_id)
   await message.reply_text(text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r'^settings'))
async def settings_query(bot, query):
  user_id = query.from_user.id
  i, type = query.data.split("#")
  buttons = [[InlineKeyboardButton('⬅️ Back', callback_data="settings#main")]]
  if type in {"main", "extra", "filters", "nextfilters", "filter_presets", "random_gap"}:
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("gap:"):
     _, minimum, maximum = type.split(":")
     gap = {"min": int(minimum), "max": int(maximum)}
     await update_configs(user_id, "random_gap", gap)
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

  elif type == "custom_gap":
     await query.answer()
     await query.message.delete()
     answer = await prompt_for_input(
         bot,
         user_id,
         "<b>Enter a delay range in seconds.</b>\n"
         "Examples: <code>5-15</code> for a random delay, or <code>8</code> for a fixed delay.\n"
         "Use <code>0-0</code> to disable. Maximum allowed: 3600 seconds.\n"
         "Send <code>/cancel</code> to stop.",
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
     dashboard_text, dashboard_markup = await settings_dashboard(
         user_id, PENDING_REVIEW.get(user_id)
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
     await query.message.delete()
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

  elif type=="channels":
     buttons = []
     channels = await db.get_user_channels(user_id)
     for channel in channels:
        buttons.append([InlineKeyboardButton(f"📣 {channel['title']}",
                         callback_data=f"settings#editchannels_{channel['chat_id']}")])
     buttons.append([InlineKeyboardButton('➕ Add destination',
                      callback_data="settings#addchannel")])
     buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#main")])
     await query.message.edit_text(
       "<b>📣 Destinations</b>\n\n"
       "Choose a destination to manage it, or add another chat.",
       reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addchannel":
     await query.answer()
     await query.message.delete()
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
            reply_markup=InlineKeyboardMarkup(buttons),
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
             [[InlineKeyboardButton('⬅️ Back to destinations', callback_data="settings#channels")]]
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
     buttons = [[InlineKeyboardButton('🗑️ Remove destination', callback_data=f"settings#removechannel_{chat_id}")
               ],
               [InlineKeyboardButton('⬅️ Back', callback_data="settings#channels")]]
     await query.message.edit_text(
        f"<b>📣 Destination details</b>\n\n<b>Name:</b> <code>{chat['title']}</code>\n<b>Chat ID:</b> <code>{chat['chat_id']}</code>\n<b>Username:</b> {chat['username']}",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type.startswith("removechannel"):
     chat_id = type.split('_')[1]
     await db.remove_channel(user_id, chat_id)
     await query.message.edit_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

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
        f"<b>Saved caption</b>\n\n<code>{data['caption']}</code>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="deletecaption":
     await update_configs(user_id, 'caption', None)
     await query.message.edit_text(
        "<b>✓ Changes saved</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addcaption":
     await query.message.delete()
     caption = await prompt_for_input(bot, query.message.chat.id, "<b>Send your caption template.</b>\nUse <code>{filename}</code>, <code>{size}</code>, or <code>{caption}</code> as needed.\nSend <code>/cancel</code> to stop.")
     if caption.text=="/cancel":
        return await caption.reply_text(
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
     try:
         caption.text.format(filename='', size='', caption='')
     except KeyError as e:
         return await caption.reply_text(
            f"<b>Unknown caption field: {e}. Use only the fields shown above.</b>",
            reply_markup=InlineKeyboardMarkup(buttons))
     await update_configs(user_id, 'caption', caption.text)
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
     await query.message.delete()
     uri = await prompt_for_input(bot, user_id, "<b>Send your MongoDB connection URI.</b>\n\nThe URI is stored in your bot settings. Send <code>/cancel</code> to stop.", link_preview_options=LinkPreviewOptions(is_disabled=True))
     if uri.text=="/cancel":
        return await uri.reply_text(
                  "<b>Setup cancelled.</b>",
                  reply_markup=InlineKeyboardMarkup(buttons))
     if not uri.text.startswith("mongodb+srv://") and not uri.text.endswith("majority"):
        return await uri.reply("<b>Invalid MongoDB URI.</b> Please check the value and try again.",
                   reply_markup=InlineKeyboardMarkup(buttons))
     connect, udb = await connect_user_db(user_id, uri.text, "test")
     if connect:
        await udb.drop_all()
        await udb.close()
     else:
        return await uri.reply("<b>Could not connect to MongoDB.</b> Check the URI and network permissions.",
                  reply_markup=InlineKeyboardMarkup(buttons))
     await update_configs(user_id, 'db_uri', uri.text)
     await uri.reply("<b>✓ Database connected.</b>",
             reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="seeurl":
     db_uri = (await get_configs(user_id))['db_uri']
     await query.answer(f"DATABASE URL: {db_uri}", show_alert=True)

  elif type=="deleteurl":
     await update_configs(user_id, 'db_uri', None)
     await query.message.edit_text(
        "<b>✓ Database URI removed.</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type in {"filters", "filter_presets", "nextfilters", "file_size", "maxfile_size"}:
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
     return await query.message.edit_text(text, reply_markup=markup)

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
     text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
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
    await update_configs(user_id, "min_size", size)
    text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
    return await query.message.edit_text(text, reply_markup=markup)

  elif type.startswith("maxupdate_size:"):
    size = int(type.split(":", 1)[1])
    if not 0 <= size <= 4000:
      return await query.answer("Choose a size from 0 to 4000 MB.", show_alert=True)
    await update_configs(user_id, "max_size", size)
    text, markup = await settings_dashboard(user_id, PENDING_REVIEW.get(user_id))
    return await query.message.edit_text(text, reply_markup=markup)

  elif type == "add_extension":
    await query.message.delete()
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
          text += f"\n• <code>{ext}</code>"
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
    await query.message.delete()
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
          text += f"\n• <code>{key}</code>"
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
  elif type.startswith("alert"):
    alert = type.split('_')[1]
    await query.answer(alert, show_alert=True)


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

    text = (
        "<b>⚙️ All forwarding settings</b>\n\n"
        f"<b>Account:</b> {account_summary}\n"
        f"<b>Destinations ({len(destinations)}):</b> {destination_summary}\n\n"
        f"{format_forwarding_settings(config)}\n\n"
        "Tap a setting below to change it. Changes save immediately."
    )

    selected_filters = config.get("filters") or {}
    gap_min, gap_max = normalize_random_gap(config.get("random_gap"))
    minimum_size = max(0, int(config.get("min_size") or 0))
    maximum_size = max(0, int(config.get("max_size") or 0))
    keyboard = [
        [
            InlineKeyboardButton("🤖 Accounts", callback_data="settings#bots"),
            InlineKeyboardButton("📣 Destinations", callback_data="settings#channels"),
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
        [
            InlineKeyboardButton("🌐 All supported", callback_data="settings#filterpreset:all"),
            InlineKeyboardButton("🖼️ Media only", callback_data="settings#filterpreset:media"),
            InlineKeyboardButton("🎞️📷🎧 Video/photo/audio", callback_data="settings#filterpreset:video_photo_audio"),
        ],
        [
            message_type_toggle("↪️ Forward original", config.get("forward_tag", False), "forward_tag"),
            message_type_toggle("🧹 Skip duplicates", config.get("duplicate", True), "duplicate"),
        ],
        [message_type_toggle("🔒 Protect content", config.get("protect", False), "protect")],
        [InlineKeyboardButton("📝 Caption", callback_data="settings#caption")],
        [
            InlineKeyboardButton(
                f"Min size −5 MB ({minimum_size})",
                callback_data=f"settings#update_size:{max(0, minimum_size - 5)}",
            ),
            InlineKeyboardButton(
                f"Min size +5 MB ({minimum_size})",
                callback_data=f"settings#update_size:{min(4000, minimum_size + 5)}",
            ),
        ],
        [
            InlineKeyboardButton(
                f"Max size −5 MB ({maximum_size})",
                callback_data=f"settings#maxupdate_size:{max(0, maximum_size - 5)}",
            ),
            InlineKeyboardButton(
                f"Max size +5 MB ({maximum_size})",
                callback_data=f"settings#maxupdate_size:{min(4000, maximum_size + 5)}",
            ),
        ],
        [
            InlineKeyboardButton("🔑 Keywords", callback_data="settings#get_keyword"),
            InlineKeyboardButton("📎 Extensions", callback_data="settings#get_extension"),
        ],
        [
            InlineKeyboardButton(
                "⏸️ Delay off" if (gap_min, gap_max) == (0, 0) else "⏸️ Off",
                callback_data="settings#gap:0:0",
            ),
            InlineKeyboardButton(
                "✅ 1–3 sec" if (gap_min, gap_max) == (1, 3) else "⏱️ 1–3 sec",
                callback_data="settings#gap:1:3",
            ),
        ],
        [
            InlineKeyboardButton(
                "✅ 3–7 sec" if (gap_min, gap_max) == (3, 7) else "⏱️ 3–7 sec",
                callback_data="settings#gap:3:7",
            ),
            InlineKeyboardButton(
                "✅ 5–15 sec" if (gap_min, gap_max) == (5, 15) else "⏱️ 5–15 sec",
                callback_data="settings#gap:5:15",
            ),
        ],
        [
            InlineKeyboardButton("✎ Custom delay", callback_data="settings#custom_gap"),
            InlineKeyboardButton("🗄 Duplicate database", callback_data="settings#database"),
        ],
    ]
    if continue_task_id:
        keyboard.extend(
            [
                [
                    InlineKeyboardButton(
                        "✅ Continue & start forwarding",
                        callback_data=f"continue_public_{continue_task_id}",
                    )
                ],
                [
                    InlineKeyboardButton(
                        "❌ Cancel task setup",
                        callback_data=f"cancel_public_{continue_task_id}",
                    )
                ],
            ]
        )
    else:
        keyboard.append([InlineKeyboardButton("🏠 Main menu", callback_data="home")])
    return text, InlineKeyboardMarkup(keyboard)


def message_type_toggle(label, enabled, key):
  state = "✅" if enabled else "🚫"
  return InlineKeyboardButton(
      f"{state} {label}",
      callback_data=f"settings#updatefilter-{key}-{enabled}",
  )
