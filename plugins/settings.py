
import asyncio
import logging

from pyrogram import Client, filters
from pyrogram.types import InlineKeyboardMarkup, LinkPreviewOptions

from .ui import InlineKeyboardButton

from database import db
from messages import Script
from message_filter_presets import filters_for_preset

from .clients import CLIENT, get_configs, parse_buttons, update_configs
from .db import connect_user_db

CLIENT = CLIENT()
logger = logging.getLogger(__name__)


@Client.on_message(filters.command('settings'))
async def settings(client, message):
   await message.reply_text(
     "<b>⚙️ Forwarding settings</b>\n\n"
     "Manage your connected accounts, destinations, and message rules below.",
     reply_markup=main_buttons()
     )


@Client.on_callback_query(filters.regex(r'^settings'))
async def settings_query(bot, query):
  user_id = query.from_user.id
  i, type = query.data.split("#")
  buttons = [[InlineKeyboardButton('⬅️ Back', callback_data="settings#main")]]
  if type=="main":
     await query.message.edit_text(
       "<b>⚙️ Forwarding settings</b>\n\n"
       "Manage your connected accounts, destinations, and message rules below.",
       reply_markup=main_buttons())
  elif type=="extra":
       await query.message.edit_text(
         "<b>⚙️ Advanced forwarding rules</b>",
         reply_markup=extra_buttons())

  elif type=="random_gap":
     gap = (await get_configs(user_id)).get("random_gap") or {"min": 0, "max": 0}
     minimum = int(gap.get("min", 0))
     maximum = int(gap.get("max", 0))
     await query.message.edit_text(
         "<b>⏱ Random forwarding gap</b>\n\n"
         f"Current range: <code>{minimum}–{maximum} seconds</code>\n"
         "A new random delay is chosen between forwarded messages. Set it to Off to use the default pacing.",
         reply_markup=random_gap_buttons(),
     )

  elif type.startswith("gap:"):
     _, minimum, maximum = type.split(":")
     gap = {"min": int(minimum), "max": int(maximum)}
     await update_configs(user_id, "random_gap", gap)
     await query.message.edit_text(
         f"<b>✓ Random gap saved:</b> <code>{gap['min']}–{gap['max']} seconds</code>",
         reply_markup=random_gap_buttons(),
     )

  elif type == "custom_gap":
     await query.answer()
     await query.message.delete()
     answer = await bot.ask(
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
     await answer.reply_text(
         f"<b>✓ Random gap saved:</b> <code>{minimum}–{maximum} seconds</code>",
         reply_markup=random_gap_buttons(),
     )

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
         chat_ids = await bot.ask(
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
     if not chat_ids.forward_date:
        return await chat_ids.reply_text(
            "<b>That message was not forwarded.</b> Forward a message from the target group or channel."
        )
     destination = getattr(chat_ids, "forward_from_chat", None)
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
     caption = await bot.ask(query.message.chat.id, "<b>Send your caption template.</b>\nUse <code>{filename}</code>, <code>{size}</code>, or <code>{caption}</code> as needed.\nSend <code>/cancel</code> to stop.")
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

  elif type=="button":
     buttons = []
     button = (await get_configs(user_id))['button']
     if button is None:
        buttons.append([InlineKeyboardButton('➕ Add button',
                      callback_data="settings#addbutton")])
     else:
        buttons.append([InlineKeyboardButton('👁️ View button',
                      callback_data="settings#seebutton")])
        buttons[-1].append(InlineKeyboardButton('🗑️ Remove button',
                      callback_data="settings#deletebutton"))
     buttons.append([InlineKeyboardButton('⬅️ Back',
                      callback_data="settings#main")])
     await query.message.edit_text(
        "<b>🔘 Custom button</b>\n\nAdd a button to forwarded messages using this format: <code>[Button][buttonurl:https://example.com]</code>.",
        reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="addbutton":
     await query.message.delete()
     ask = await bot.ask(user_id, text="<b>Send a button in this format:</b>\n<code>[Button][buttonurl:https://example.com]</code>\n\nSend <code>/cancel</code> to stop.")
     button = parse_buttons(ask.text.html)
     if not button:
        return await ask.reply("<b>Invalid button format.</b> Please send a label and a valid URL.")
     await update_configs(user_id, 'button', ask.text.html)
     await ask.reply("<b>✓ Button saved.</b>",
             reply_markup=InlineKeyboardMarkup(buttons))

  elif type=="seebutton":
      button = (await get_configs(user_id))['button']
      button = parse_buttons(button, markup=False)
      button.append([InlineKeyboardButton("⬅️ Back", callback_data="settings#button")])
      await query.message.edit_text(
         "<b>Saved button preview</b>",
         reply_markup=InlineKeyboardMarkup(button))

  elif type=="deletebutton":
     await update_configs(user_id, 'button', None)
     await query.message.edit_text(
        "<b>✓ Button removed.</b>",
        reply_markup=InlineKeyboardMarkup(buttons))

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
     uri = await bot.ask(user_id, "<b>Send your MongoDB connection URI.</b>\n\nThe URI is stored in your bot settings. Send <code>/cancel</code> to stop.", link_preview_options=LinkPreviewOptions(is_disabled=True))
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

  elif type=="filters":
     await query.message.edit_text(
        "<b>🧰 Message types</b>\n\nChoose what to forward. ✅ means included; ❌ means skipped. Use Quick select for common combinations, or toggle individual types.",
        reply_markup=await filters_buttons(user_id))

  elif type=="filter_presets":
     await query.message.edit_text(
        "<b>⚡ Quick select message types</b>\n\nChoose a preset to replace the current message-type selection. You can fine-tune individual types afterwards.",
        reply_markup=filter_preset_buttons())

  elif type.startswith("filterpreset:"):
     preset = type.split(":", 1)[1]
     try:
        updated_filters = filters_for_preset(preset)
     except ValueError:
        return await query.answer("Unknown message-type preset.", show_alert=True)
     await query.answer("Preset applied")
     configs = await get_configs(user_id)
     configs["filters"] = updated_filters
     await db.update_configs(user_id, configs)
     await query.message.edit_text(
        "<b>✓ Message selection updated.</b> You can still toggle individual types below.",
        reply_markup=await filters_buttons(user_id))

  elif type=="nextfilters":
     await query.edit_message_reply_markup(
        reply_markup=await next_filters_buttons(user_id))

  elif type.startswith("updatefilter"):
     i, key, value = type.split('-')
     if value=="True":
        await update_configs(user_id, key, False)
     else:
        await update_configs(user_id, key, True)
     if key in ['poll', 'protect', 'voice', 'video_note', 'animation', 'sticker', 'duplicate']:
        return await query.edit_message_reply_markup(
           reply_markup=await next_filters_buttons(user_id))
     await query.edit_message_reply_markup(
        reply_markup=await filters_buttons(user_id))

  elif type.startswith("file_size"):
    settings = await get_configs(user_id)
    size = settings.get('min_size', 0)
    await query.message.edit_text(
       f"<b>⬇️ Minimum file size</b>\n\nCurrent limit: <code>{size} MB</code>\nFiles below this size will be skipped. Set to 0 to disable.",
       reply_markup=size_button(size))

  elif type.startswith("maxfile_size"):
    settings = await get_configs(user_id)
    size = settings.get('max_size', 0)
    await query.message.edit_text(
       f"<b>⬆️ Maximum file size</b>\n\nCurrent limit: <code>{size} MB</code>\nFiles above this size will be skipped. Set to 0 to disable.",
       reply_markup=maxsize_button(size))

  elif type.startswith("update_size:"):
    size = int(type.split(":", 1)[1])
    if not 0 <= size <= 4000:
      return await query.answer("Choose a size from 0 to 4000 MB.", show_alert=True)
    await update_configs(user_id, "min_size", size)
    await query.message.edit_text(
       f"<b>⬇️ Minimum file size</b>\n\nCurrent limit: <code>{size} MB</code>\nFiles below this size will be skipped. Set to 0 to disable.",
       reply_markup=size_button(size))

  elif type.startswith("maxupdate_size:"):
    size = int(type.split(":", 1)[1])
    if not 0 <= size <= 4000:
      return await query.answer("Choose a size from 0 to 4000 MB.", show_alert=True)
    await update_configs(user_id, "max_size", size)
    await query.message.edit_text(
       f"<b>⬆️ Maximum file size</b>\n\nCurrent limit: <code>{size} MB</code>\nFiles above this size will be skipped. Set to 0 to disable.",
       reply_markup=maxsize_button(size))

  elif type == "add_extension":
    await query.message.delete()
    ext = await bot.ask(user_id, text="<b>Enter file extensions separated by spaces.</b>\nExample: <code>mkv zip pdf</code>\nSend <code>/cancel</code> to stop.")
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
    btn.append([InlineKeyboardButton('⬅️ Back', callback_data='settings#extra')])
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
    ask = await bot.ask(user_id, text="<b>Enter keywords separated by spaces.</b>\nFiles whose names contain these words will be skipped.\nSend <code>/cancel</code> to stop.")
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
    btn.append([InlineKeyboardButton('⬅️ Back', callback_data='settings#extra')])
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


def random_gap_buttons():
   return InlineKeyboardMarkup(
       [
           [
               InlineKeyboardButton("⏸️ Off", callback_data="settings#gap:0:0"),
               InlineKeyboardButton("⏱️ 1–3 sec", callback_data="settings#gap:1:3"),
           ],
           [
               InlineKeyboardButton("⏱️ 3–7 sec", callback_data="settings#gap:3:7"),
               InlineKeyboardButton("⏱️ 5–15 sec", callback_data="settings#gap:5:15"),
           ],
           [InlineKeyboardButton("✎ Enter a range", callback_data="settings#custom_gap")],
           [InlineKeyboardButton("⬅️ Back", callback_data="settings#extra")],
       ]
   )


def extra_buttons():
   buttons = [
       [InlineKeyboardButton('⬇️ Minimum file size', callback_data='settings#file_size')],
       [InlineKeyboardButton('⬆️ Maximum file size', callback_data='settings#maxfile_size ')],
       [
           InlineKeyboardButton('🔑 Keywords', callback_data='settings#get_keyword'),
           InlineKeyboardButton('📎 Extensions', callback_data='settings#get_extension'),
       ],
       [InlineKeyboardButton('⏱ Random forwarding gap', callback_data='settings#random_gap')],
       [InlineKeyboardButton('🗄 Custom duplicate database', callback_data='settings#database')],
       [InlineKeyboardButton('⬅️ Back to settings', callback_data='settings#main')],
   ]
   return InlineKeyboardMarkup(buttons)


def main_buttons():
  buttons = [
       [
           InlineKeyboardButton('🤖 Accounts', callback_data='settings#bots'),
           InlineKeyboardButton('📣 Destinations', callback_data='settings#channels'),
       ],
       [
           InlineKeyboardButton('📝 Caption', callback_data='settings#caption'),
           InlineKeyboardButton('🔘 Buttons', callback_data='settings#button'),
       ],
       [InlineKeyboardButton('🧰 Message filters', callback_data='settings#filters')],
       [InlineKeyboardButton('⚙️ Advanced rules', callback_data='settings#extra')],
       [InlineKeyboardButton('🏠 Main menu', callback_data='home')],
  ]
  return InlineKeyboardMarkup(buttons)


def maxsize_button(size):
    size = int(size or 0)
    steps = (1, 5, 10, 50, 100)
    buttons = [
        [
            InlineKeyboardButton(
                f"➕ +{step} MB",
                callback_data=f"settings#maxupdate_size:{min(4000, size + step)}",
            ),
            InlineKeyboardButton(
                f"➖ −{step} MB",
                callback_data=f"settings#maxupdate_size:{max(0, size - step)}",
            ),
        ]
        for step in steps
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="settings#extra")])
    return InlineKeyboardMarkup(buttons)


def size_button(size):
    size = int(size or 0)
    steps = (1, 5, 10, 50, 100)
    buttons = [
        [
            InlineKeyboardButton(
                f"➕ +{step} MB",
                callback_data=f"settings#update_size:{min(4000, size + step)}",
            ),
            InlineKeyboardButton(
                f"➖ −{step} MB",
                callback_data=f"settings#update_size:{max(0, size - step)}",
            ),
        ]
        for step in steps
    ]
    buttons.append([InlineKeyboardButton("⬅️ Back", callback_data="settings#extra")])
    return InlineKeyboardMarkup(buttons)


def filter_preset_buttons():
  return InlineKeyboardMarkup(
      [
          [
              InlineKeyboardButton("🌐 All types", callback_data="settings#filterpreset:all"),
              InlineKeyboardButton("🖼️ Media only", callback_data="settings#filterpreset:media"),
          ],
          [InlineKeyboardButton("🎞️ + 📷 + 🎧 Videos, photos & audio", callback_data="settings#filterpreset:video_photo_audio")],
          [
              InlineKeyboardButton("🎞️ Videos only", callback_data="settings#filterpreset:video"),
              InlineKeyboardButton("📷 Photos only", callback_data="settings#filterpreset:photo"),
          ],
          [
              InlineKeyboardButton("🎧 Audio only", callback_data="settings#filterpreset:audio"),
              InlineKeyboardButton("📁 Documents only", callback_data="settings#filterpreset:document"),
          ],
          [InlineKeyboardButton("⬅️ Back to message types", callback_data="settings#filters")],
      ]
  )


def message_type_toggle(label, enabled, key):
  state = "✅" if enabled else "🚫"
  return InlineKeyboardButton(
      f"{state} {label}",
      callback_data=f"settings#updatefilter-{key}-{enabled}",
  )


async def filters_buttons(user_id):
  config = await get_configs(user_id)
  filters = config["filters"]
  return InlineKeyboardMarkup(
      [
          [
              message_type_toggle("📝 Text", filters["text"], "text"),
              message_type_toggle("📁 Documents", filters["document"], "document"),
          ],
          [
              message_type_toggle("🎞️ Videos", filters["video"], "video"),
              message_type_toggle("📷 Photos", filters["photo"], "photo"),
          ],
          [
              message_type_toggle("🎧 Audio", filters["audio"], "audio"),
              message_type_toggle("🏷️ Forward tag", config["forward_tag"], "forward_tag"),
          ],
          [InlineKeyboardButton("⚡ Quick select", callback_data="settings#filter_presets")],
          [
              InlineKeyboardButton("⬅️ Back", callback_data="settings#main"),
              InlineKeyboardButton("➡️ More types", callback_data="settings#nextfilters"),
          ],
      ]
  )


async def next_filters_buttons(user_id):
  config = await get_configs(user_id)
  filters = config["filters"]
  return InlineKeyboardMarkup(
      [
          [
              message_type_toggle("🎤 Voice", filters["voice"], "voice"),
              message_type_toggle("🔘 Video notes", filters["video_note"], "video_note"),
          ],
          [
              message_type_toggle("🎭 Animations", filters["animation"], "animation"),
              message_type_toggle("🃏 Stickers", filters["sticker"], "sticker"),
          ],
          [
              message_type_toggle("📊 Polls", filters["poll"], "poll"),
              message_type_toggle("🧹 Skip duplicates", config["duplicate"], "duplicate"),
          ],
          [message_type_toggle("🔒 Protect content", config["protect"], "protect")],
          [
              InlineKeyboardButton("⬅️ Back", callback_data="settings#filters"),
              InlineKeyboardButton("✅ Done", callback_data="settings#main"),
          ],
      ]
  )
