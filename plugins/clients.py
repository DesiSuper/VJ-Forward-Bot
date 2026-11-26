
import asyncio
import logging
import re
from copy import deepcopy
from html import escape
from collections.abc import AsyncGenerator

from pyrogram import Client, filters
from pyrogram.errors import (
  PasswordHashInvalid,
  PhoneCodeExpired,
  PhoneCodeInvalid,
  PhoneNumberInvalid,
  SessionPasswordNeeded,
)
from pyrogram.types import Message

from config import Config
from database import DEFAULT_CONFIG, db
from .prompts import ask as prompt_for_input

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)

BOT_TOKEN_TEXT = "<b>Connect a Telegram bot</b>\n\nCreate one with @BotFather, then forward its token here. It is stored securely for your account. Send <code>/cancel</code> to stop."
class CLIENT:
  def __init__(self):
     self.api_id = Config.API_ID
     self.api_hash = Config.API_HASH

  async def add_bot(self, bot, message):
     user_id = int(message.from_user.id)
     try:
        prompt = await prompt_for_input(bot, chat_id=user_id, text=BOT_TOKEN_TEXT, filters=filters.text, timeout=600, delete_prompt_and_reply=True)
     except asyncio.TimeoutError:
        await bot.send_message(user_id, "<b>Bot setup timed out. Start again from Settings when ready.</b>")
        return
     if not prompt.text or prompt.text.strip().lower() == "/cancel":
        return await bot.send_message(user_id, "<b>Bot setup cancelled.</b>")
     origin = getattr(prompt, "forward_origin", None)
     if not origin or not getattr(origin, "date", None):
        return await bot.send_message(user_id, "<b>That message was not forwarded.</b> Forward the token message directly from @BotFather.")
     sender = getattr(origin, "sender_user", None)
     if not sender or str(sender.id) != "93372553":
        return await bot.send_message(user_id, "<b>Token source could not be verified.</b> Please forward the token message directly from @BotFather.")
     matches = re.findall(r"\d{8,10}:[0-9A-Za-z_-]{35}", prompt.text)
     bot_token = matches[0] if matches else None
     if not bot_token:
        return await bot.send_message(user_id, "<b>No bot token was found.</b> Please try again or send <code>/cancel</code>.")

     client = Client("BOT", Config.API_ID, Config.API_HASH, bot_token=bot_token, in_memory=True)
     try:
        await client.start()
        account = await client.get_me()
     except Exception:
        logger.warning("Bot account validation failed for user %s", user_id)
        return await bot.send_message(user_id, "<b>Could not connect that bot.</b> Check that the token is valid and try again.")
     finally:
        try:
           await client.stop()
        except Exception:
           logger.debug("Temporary bot client cleanup failed", exc_info=True)

     details = {
       "id": account.id,
       "is_bot": True,
       "user_id": user_id,
       "name": account.first_name,
       "token": bot_token,
       "username": account.username,
     }
     await db.add_bot(details)
     return True

  async def add_session(self, bot, message):
     user_id = int(message.from_user.id)
     await bot.send_message(
         user_id,
         "<b>⚠️ Connect a personal account</b>\n\n"
         "Automation may lead to account restrictions. Connect only your own account. "
         "Sign-in details create an encrypted session stored by the bot.",
     )
     try:
        phone_prompt = await prompt_for_input(bot,
            chat_id=user_id,
            text="<b>Enter your phone number with country code.</b>\nExample: <code>+12025550123</code>\nSend <code>/cancel</code> to stop.",
            filters=filters.text,
            timeout=600,
            delete_prompt_and_reply=True,
        )
     except asyncio.TimeoutError:
        await bot.send_message(user_id, "<b>Account setup timed out. Start again from Settings when ready.</b>")
        return
     if not phone_prompt.text or phone_prompt.text.strip().lower() == "/cancel":
        return await bot.send_message(user_id, "<b>User account setup cancelled.</b>")
     phone_number = phone_prompt.text.strip()

     login_client = Client("login", Config.API_ID, Config.API_HASH, in_memory=True)
     connected = False
     try:
        await login_client.connect()
        connected = True
        await bot.send_message(user_id, "<b>Sending a sign-in code…</b>")
        code = await login_client.send_code(phone_number)
        code_prompt = await prompt_for_input(bot,
            user_id,
            "<b>Enter the Telegram sign-in code.</b>\n"
            "For a code <code>12345</code>, send <code>1 2 3 4 5</code>.\n"
            "Send <code>/cancel</code> to stop.",
            filters=filters.text,
            timeout=600,
            delete_prompt_and_reply=True,
        )
        if not code_prompt.text or code_prompt.text.strip().lower() == "/cancel":
            return await bot.send_message(user_id, "<b>User account setup cancelled.</b>")
        phone_code = "".join(code_prompt.text.split())
        try:
            await login_client.sign_in(phone_number, code.phone_code_hash, phone_code)
        except SessionPasswordNeeded:
            password_prompt = await prompt_for_input(bot,
                user_id,
                "<b>Two-step verification is enabled.</b> Enter your password to continue, or send <code>/cancel</code>.",
                filters=filters.text,
                timeout=600,
                delete_prompt_and_reply=True,
            )
            if not password_prompt.text or password_prompt.text.strip().lower() == "/cancel":
                return await bot.send_message(user_id, "<b>User account setup cancelled.</b>")
            await login_client.check_password(password=password_prompt.text)
        string_session = await login_client.export_session_string()
     except PhoneNumberInvalid:
        await bot.send_message(user_id, "<b>That phone number is not valid.</b> Include the country code and try again.")
        return
     except PhoneCodeInvalid:
        await bot.send_message(user_id, "<b>That sign-in code is invalid.</b> Please restart setup and try again.")
        return
     except PhoneCodeExpired:
        await bot.send_message(user_id, "<b>That sign-in code has expired.</b> Restart setup to request another.")
        return
     except PasswordHashInvalid:
        await bot.send_message(user_id, "<b>Password not accepted.</b> Please restart setup and try again.")
        return
     except asyncio.TimeoutError:
        await bot.send_message(user_id, "<b>Account setup timed out. Start again from Settings when ready.</b>")
        return
     except Exception:
        logger.warning("User account sign-in failed for user %s", user_id)
        await bot.send_message(user_id, "<b>Sign-in could not be completed.</b> Check the number/code and try again later.")
        return
     finally:
        if connected:
            try:
                await login_client.disconnect()
            except Exception:
                logger.debug("Temporary login session cleanup failed", exc_info=True)

     validation_client = Client(
         "USERBOT", self.api_id, self.api_hash, session_string=string_session, in_memory=True
     )
     try:
        await validation_client.start()
        account = await validation_client.get_me()
     except Exception:
        logger.warning("New user session validation failed for user %s", user_id)
        await bot.send_message(user_id, "<b>Account connection failed.</b> Please try signing in again.")
        return
     finally:
        try:
           await validation_client.stop()
        except Exception:
           logger.debug("Temporary user client cleanup failed", exc_info=True)

     details = {
       "id": account.id,
       "is_bot": False,
       "user_id": user_id,
       "name": account.first_name,
       "session": string_session,
       "username": account.username,
     }
     await db.add_userbot(details)
     return True


@Client.on_message(filters.private & filters.command('reset'))
async def reset_settings(bot, m):
   await db.update_configs(m.from_user.id, deepcopy(DEFAULT_CONFIG))
   await m.reply("<b>✓ Your settings have been reset.</b>")


@Client.on_message(
    filters.command('resetall') & filters.user(list(Config.bot_owner_ids()))
)
async def resetall(bot, message):
  users = await db.get_all_users()
  sts = await message.reply("<b>Resetting user settings…</b>")
  TEXT = "<b>Reset progress</b>\n\nProcessed: <code>{}</code>\nUpdated: <code>{}</code>\nFailed: <code>{}</code>"
  total = success = failed = 0
  errors = []
  async for user in users:
      user_id = user.get('id')
      total += 1
      if user_id is None:
         failed += 1
      else:
         try:
            await db.update_configs(user_id, deepcopy(DEFAULT_CONFIG))
            success += 1
         except Exception as error:
            errors.append(f"{user_id}: {escape(str(error))}")
            failed += 1
      if total % 10 == 0:
         await sts.edit(TEXT.format(total, success, failed))
  if errors:
     await message.reply("<b>Some settings could not be reset:</b>\n" + "\n".join(f"<code>{error}</code>" for error in errors[:20]))
  await sts.edit("<b>Settings reset complete.</b>\n\n" + TEXT.format(total, success, failed))


async def get_configs(user_id):
  configs = await db.get_configs(user_id)
  return configs


async def update_configs(user_id, key, value):
  if key in {"voice", "animation", "sticker", "poll", "button"}:
      return
  current = await db.get_configs(user_id)
  if key in ['caption', 'duplicate', 'db_uri', 'forward_tag', 'protect', 'min_size', 'max_size', 'extension', 'keywords', 'sources', 'random_gap']:
     current[key] = value
  else:
     current['filters'][key] = value
  await db.update_configs(user_id, current)


async def iter_messages(
    self,
    chat_id: int | str,
    limit: int,
    offset: int = 0,
    filters: list[str] | None = None,
) -> AsyncGenerator[Message | str, None]:
        # ``limit`` is the latest source message ID and ``offset`` is the
        # number of messages already skipped/fetched. Telegram message IDs are
        # one-based, so the first ID to inspect is offset + 1.
        current = max(1, int(offset) + 1)
        limit = int(limit)
        while current <= limit:
            new_diff = min(200, limit - current + 1)
            message_ids = list(range(current, current + new_diff))
            messages = await self.get_messages(chat_id, message_ids)
            for message in messages:
                if message is None:
                    yield "DELETED"
                elif any(getattr(message, media_type, False) for media_type in (filters or {})):
                    yield "FILTERED"
                else:
                    yield message
                current += 1


async def get_client(bot_token, is_bot=True):
  if is_bot:
    return Client("BOT", Config.API_ID, Config.API_HASH, bot_token=bot_token, in_memory=True)
  else:
    return Client("USERBOT", Config.API_ID, Config.API_HASH, session_string=bot_token)
