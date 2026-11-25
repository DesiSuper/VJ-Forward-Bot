
import asyncio
import datetime
import logging
import time

from pyrogram import Client, filters
from pyrogram.errors import (
    FloodWait,
    InputUserDeactivated,
    PeerIdInvalid,
    UserIsBlocked,
)

from config import Config
from database import db

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


async def broadcast_messages(user_id, message):
    while True:
        try:
            await message.copy(chat_id=user_id)
            return True, "Success"
        except FloodWait as error:
            await asyncio.sleep(error.value)
        except InputUserDeactivated:
            await db.delete_user(int(user_id))
            logger.info("Removed %s from the database because the account is inactive", user_id)
            return False, "Deleted"
        except UserIsBlocked:
            logger.info("User %s has blocked the bot", user_id)
            return False, "Blocked"
        except PeerIdInvalid:
            # Invalid peer resolution can be transient or caused by stale
            # access hashes; it does not prove that the user account is gone.
            logger.info("Broadcast peer resolution failed for %s", user_id)
            return False, "Error"
        except Exception:
            logger.exception("Broadcast delivery failed for %s", user_id)
            return False, "Error"



@Client.on_message(filters.command("broadcast") & filters.user(Config.BOT_OWNER) & filters.reply)
async def verupikkals(bot, message):
    users = await db.get_all_users()
    b_msg = message.reply_to_message
    sts = await message.reply_text(
        text='<b>Broadcast started…</b>'
    )
    start_time = time.time()
    total_users = await db.total_users_count()
    done = 0
    blocked = 0
    deleted = 0
    failed =0


    success = 0
    async for user in users:
        if 'id' in user:
            pti, sh = await broadcast_messages(int(user['id']), b_msg)
            if pti:
                success += 1
            elif pti == False:
                if sh == "Blocked":
                    blocked += 1
                elif sh == "Deleted":
                    deleted += 1
                elif sh == "Error":
                    failed += 1
            done += 1
            if not done % 20:
                await sts.edit(f"<b>Broadcast in progress</b>\n\nCompleted: <code>{done}/{total_users}</code>\nDelivered: <code>{success}</code>\nBlocked: <code>{blocked}</code>\nInactive: <code>{deleted}</code>\nFailed: <code>{failed}</code>")
        else:
            # Handle the case where 'id' key is missing in the user dictionary
            done += 1
            failed += 1
            if not done % 20:
                try:
                    await sts.edit(f"<b>Broadcast in progress</b>\n\nCompleted: <code>{done}/{total_users}</code>\nDelivered: <code>{success}</code>\nBlocked: <code>{blocked}</code>\nInactive: <code>{deleted}</code>\nFailed: <code>{failed}</code>")
                except Exception:
                    logger.debug("Could not update broadcast progress for owner", exc_info=True)

    time_taken = datetime.timedelta(seconds=int(time.time()-start_time))
    await sts.edit(f"<b>Broadcast complete</b>\n\nDuration: <code>{time_taken}</code>\nCompleted: <code>{done}/{total_users}</code>\nDelivered: <code>{success}</code>\nBlocked: <code>{blocked}</code>\nInactive: <code>{deleted}</code>\nFailed: <code>{failed}</code>")
