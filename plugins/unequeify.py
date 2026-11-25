
import logging
import re
from functools import wraps
from html import escape

from pyrogram import Client, enums, filters
from pyrogram.types import InlineKeyboardMarkup

from .ui import InlineKeyboardButton

from config import temp
from database import db
from messages import Script

from .clients import CLIENT, get_client
from .prompts import InputPromptAlreadyActive, ask as prompt_for_input
from .utils import get_forwarded_chat

CLIENT = CLIENT()
logger = logging.getLogger(__name__)
COMPLETED_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("✅ Done · Close", callback_data="close_btn")]]
)
CANCEL_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ Cancel cleanup", callback_data="cancel_unequify")]]
)


def handle_active_prompt(handler):
   @wraps(handler)
   async def wrapped(client, message, *args, **kwargs):
      try:
         return await handler(client, message, *args, **kwargs)
      except InputPromptAlreadyActive:
         return await message.reply(
             "<b>An input prompt is already active.</b> Reply to it or send <code>/cancel</code> before starting duplicate cleanup."
         )

   return wrapped


@Client.on_callback_query(filters.regex(r"^cancel_unequify$"))
async def cancel_unequify(client, query):
   temp.CANCEL[query.from_user.id] = True
   await query.answer("Cleanup will stop after the current batch.")


@Client.on_message(filters.command("unequify") & filters.private)
@handle_active_prompt
async def unequify(client, message):
   user_id = message.from_user.id
   temp.CANCEL[user_id] = False
   if temp.lock.get(user_id) and str(temp.lock.get(user_id))=="True":
      return await message.reply("<b>A task is already running.</b> Wait for it to finish before starting duplicate cleanup.")
   _bot = await db.get_userbot(user_id)
   if not _bot:
      return await message.reply("<b>A user account is required for duplicate cleanup.</b> Connect one in <code>/settings → Accounts</code>.")
   target = await prompt_for_input(client, user_id, text="<b>Choose a chat to scan</b>\nForward its latest message or send a link to that message.\nSend <code>/cancel</code> to stop.")
   forwarded_chat = get_forwarded_chat(target)
   if forwarded_chat and forwarded_chat.type in {
        enums.ChatType.CHANNEL,
        enums.ChatType.GROUP,
        enums.ChatType.SUPERGROUP,
        enums.ChatType.FORUM,
   }:
        chat_id = forwarded_chat.username or forwarded_chat.id
   elif getattr(target, "text", None):
      target_text = target.text.strip()
      if target_text.lower() in {"/cancel", "/no"}:
         return await message.reply("<b>Cleanup cancelled.</b>")
      regex = re.compile(r"(?:https://)?(?:t\.me/|telegram\.me/|telegram\.dog/)(?:c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)(?:\?single)?$")
      match = regex.fullmatch(target_text)
      if not match:
         return await message.reply('<b>That message link is invalid.</b> Please try again.')
      chat_id = match.group(1)
      if chat_id.isnumeric():
         chat_id = int("-100" + chat_id)
   else:
      return await message.reply_text("<b>Could not identify the chat.</b> Forward a message from it or send a message link.")
   confirm = await prompt_for_input(client, user_id, text="<b>Confirm duplicate cleanup</b>\nThis will delete duplicate documents from the selected chat. Send <code>/yes</code> to continue or <code>/no</code> to cancel.")
   confirmation = (getattr(confirm, "text", None) or "").strip().lower()
   if confirmation in {"/no", "/cancel"}:
      return await confirm.reply("<b>Cleanup cancelled.</b>")
   if confirmation != "/yes":
      return await confirm.reply("<b>Cleanup not started.</b> Send <code>/yes</code> to confirm or <code>/no</code> to cancel.")
   sts = await confirm.reply("<b>Scanning for duplicate documents…</b>")
   il = False
   data = _bot['session']
   bot = None
   try:
      bot = await get_client(data, is_bot=il)
      await bot.start()
   except Exception as e:
      if bot is not None:
         try:
            await bot.stop()
         except Exception:
            logger.debug("Failed to stop an incompletely started cleanup client", exc_info=True)
      return await sts.edit(
          f"<b>Could not start the connected account:</b> <code>{escape(str(e))}</code>"
      )
   MESSAGES = set()
   DUPLICATE = []
   total=deleted=0
   temp.lock[user_id] = True
   temp.CANCEL[user_id] = False
   try:
     await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Working"), reply_markup=CANCEL_BTN)
     async for message in bot.search_messages(chat_id=chat_id, filter=enums.MessagesFilter.DOCUMENT):
        if temp.CANCEL.get(user_id) == True:
           temp.lock[user_id] = False
           temp.CANCEL.pop(user_id, None)
           await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Cancelled"), reply_markup=COMPLETED_BTN)
           await bot.stop()
           return
        file = message.document
        file_id = file.file_unique_id
        if file_id in MESSAGES:
           DUPLICATE.append(message.id)
        else:
           MESSAGES.add(file_id)
        total += 1
        if total %1000 == 0:
           await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Working"), reply_markup=CANCEL_BTN)
        if len(DUPLICATE) >= 100:
           await bot.delete_messages(chat_id, DUPLICATE)
           deleted += 100
           await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Working"), reply_markup=CANCEL_BTN)
           DUPLICATE = []
     if DUPLICATE:
        await bot.delete_messages(chat_id, DUPLICATE)
        deleted += len(DUPLICATE)
   except Exception as e:
       temp.lock[user_id] = False
       temp.CANCEL.pop(user_id, None)
       await sts.edit(f"<b>Cleanup failed:</b>\n<code>{escape(str(e))}</code>")
       return await bot.stop()
   temp.lock[user_id] = False
   temp.CANCEL.pop(user_id, None)
   await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Complete"), reply_markup=COMPLETED_BTN)
   await bot.stop()
