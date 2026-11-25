
import base64
import re
import struct

from pyrogram import Client, enums, filters
from pyrogram.file_id import FileId
from pyrogram.types import InlineKeyboardMarkup

from .ui import InlineKeyboardButton

from config import temp
from database import db
from messages import Script

from .clients import CLIENT, get_client

CLIENT = CLIENT()
COMPLETED_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("✅ Done · Close", callback_data="close_btn")]]
)
CANCEL_BTN = InlineKeyboardMarkup(
    [[InlineKeyboardButton("❌ Cancel cleanup", callback_data="cancel_unequify")]]
)


def encode_file_id(s: bytes) -> str:
    r = b""
    n = 0

    for i in s + bytes([22]) + bytes([4]):
        if i == 0:
            n += 1
        else:
            if n:
                r += b"\x00" + bytes([n])
                n = 0

            r += bytes([i])

    return base64.urlsafe_b64encode(r).decode().rstrip("=")


def unpack_new_file_id(new_file_id):
    """Return file_id"""
    decoded = FileId.decode(new_file_id)
    file_id = encode_file_id(
        struct.pack(
            "<iiqq",
            int(decoded.file_type),
            decoded.dc_id,
            decoded.media_id,
            decoded.access_hash
        )
    )
    return file_id


@Client.on_callback_query(filters.regex(r"^cancel_unequify$"))
async def cancel_unequify(client, query):
   temp.CANCEL[query.from_user.id] = True
   await query.answer("Cleanup will stop after the current batch.")


@Client.on_message(filters.command("unequify") & filters.private)
async def unequify(client, message):
   user_id = message.from_user.id
   temp.CANCEL[user_id] = False
   if temp.lock.get(user_id) and str(temp.lock.get(user_id))=="True":
      return await message.reply("<b>A task is already running.</b> Wait for it to finish before starting duplicate cleanup.")
   _bot = await db.get_userbot(user_id)
   if not _bot:
      return await message.reply("<b>A user account is required for duplicate cleanup.</b> Connect one in <code>/settings → Accounts</code>.")
   target = await client.ask(user_id, text="<b>Choose a chat to scan</b>\nForward its latest message or send a link to that message.\nSend <code>/cancel</code> to stop.")
   if target.text and target.text.startswith("/"):
      return await message.reply("<b>Cleanup cancelled.</b>")
   elif target.text:
      regex = re.compile(r"(https://)?(t\.me/|telegram\.me/|telegram\.dog/)(c/)?(\d+|[a-zA-Z_0-9]+)/(\d+)$")
      match = regex.match(target.text.replace("?single", ""))
      if not match:
         return await message.reply('<b>That message link is invalid.</b> Please try again.')
      chat_id = match.group(4)
      if chat_id.isnumeric():
         chat_id  = int("-100" + chat_id)
   elif target.forward_from_chat.type in [enums.ChatType.CHANNEL, 'supergroup']:
        chat_id = target.forward_from_chat.username or target.forward_from_chat.id
   else:
        return await message.reply_text("<b>Could not identify the chat.</b> Forward a message from it or send a message link.")
   confirm = await client.ask(user_id, text="<b>Confirm duplicate cleanup</b>\nThis will delete duplicate documents from the selected chat. Send <code>/yes</code> to continue or <code>/no</code> to cancel.")
   if confirm.text.lower() == '/no':
      return await confirm.reply("<b>Cleanup cancelled.</b>")
   sts = await confirm.reply("<b>Scanning for duplicate documents…</b>")
   il = False
   data = _bot['session']
   try:
      bot = await get_client(data, is_bot=il)
      await bot.start()
   except Exception as e:
      return await sts.edit(e)
   try:
       k = await bot.send_message(chat_id, text="testing")
       await k.delete()
   except:
       await sts.edit("<b>Can't post to this chat.</b> Give the connected account permission to send and delete messages.")
       return await bot.stop()
   MESSAGES = []
   DUPLICATE = []
   total=deleted=0
   temp.lock[user_id] = True
   temp.CANCEL[user_id] = False
   try:
     await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Working"), reply_markup=CANCEL_BTN)
     async for message in bot.search_messages(chat_id=chat_id, filter=enums.MessagesFilter.DOCUMENT):
        if temp.CANCEL.get(user_id) == True:
           temp.lock[user_id] = False
           await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Cancelled"), reply_markup=COMPLETED_BTN)
           await bot.stop()
           return
        file = message.document
        file_id = unpack_new_file_id(file.file_id)
        if file_id in MESSAGES:
           DUPLICATE.append(message.id)
        else:
           MESSAGES.append(file_id)
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
       await sts.edit(f"<b>Cleanup failed:</b>\n<code>{e}</code>")
       return await bot.stop()
   temp.lock[user_id] = False
   await sts.edit(Script.DUPLICATE_TEXT.format(total, deleted, "Complete"), reply_markup=COMPLETED_BTN)
   await bot.stop()
