
import asyncio
import logging
import time

from pyrogram import Client, filters
from pyrogram.errors import FloodWait, MessageNotModified
from pyrogram.types import InlineKeyboardMarkup

from .ui import InlineKeyboardButton

from config import temp
from database import db
from forwarding_delay import choose_random_gap, normalize_random_gap
from forward_review import PENDING_REVIEW
from messages import Script

from .clients import CLIENT, get_client, iter_messages
from .db import connect_user_db
from .media_filters import extension_filter, keyword_filter, size_filter
from .utils import STS

CLIENT = CLIENT()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
TEXT = Script.TEXT
_PROGRESS_EDIT_INTERVAL = 5.0
_LAST_PROGRESS_EDIT: dict[tuple[int, int], float] = {}
PROGRESS = (
    "<b>Forwarding task</b>\n\n"
    "<b>Progress:</b> <code>{}%</code>\n"
    "<b>Scanned:</b> <code>{}</code>\n"
    "<b>Forwarded:</b> <code>{}</code>\n"
    "<b>Videos:</b> <code>{}</code>\n"
    "<b>Images:</b> <code>{}</code>\n"
    "<b>Remaining:</b> <code>{}</code>\n"
    "<b>Status:</b> <code>{}</code>\n"
    "<b>Estimated remaining:</b> <code>{}</code>\n"
    "<b>Elapsed:</b> <code>{}</code>"
)


async def pause_between_messages(gap, default_delay):
    delay = choose_random_gap(gap, default_delay)
    if delay > 0:
        await asyncio.sleep(delay)


def media_counter_key(message):
    """Return the progress counter for successfully sent video/image media."""
    if getattr(message, "video", None) or getattr(message, "video_note", None):
        return "videos"
    if getattr(message, "photo", None):
        return "photos"
    document = getattr(message, "document", None)
    mime_type = (getattr(document, "mime_type", "") or "").lower()
    file_name = (getattr(document, "file_name", "") or "").lower()
    if mime_type.startswith("video/") or file_name.endswith(
        (".mp4", ".m4v", ".mov", ".mkv", ".avi", ".webm", ".mpeg", ".mpg", ".ts")
    ):
        return "videos"
    if mime_type.startswith("image/") or file_name.endswith(
        (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tif", ".tiff", ".heic")
    ):
        return "photos"
    return None


async def forward_source_messages(
    user_id,
    client,
    progress_message,
    task,
    start_offset,
    options,
    caption,
    forward_tag,
    protect,
    button,
    user_db,
    known_duplicates,
    random_gap,
    default_delay,
):
    """Shared forwarding loop for new and resumed jobs."""
    pending_message_ids = []
    pending_file_ids = []
    pending_media_counts = []
    scanned_since_update = 0
    batch_size = 1 if random_gap[1] > 0 else 100
    keywords = options.get("keywords") or ()
    extensions = options.get("extensions") or ()

    async for source_message in iter_messages(
        client,
        chat_id=task.get("FROM"),
        limit=task.get("limit"),
        offset=start_offset,
        filters=options["filters"],
        max_size=options["max_size"],
    ):
        if await is_cancelled(client, user_id, progress_message, task):
            return False

        if scanned_since_update % 20 == 0:
            await edit(user_id, progress_message, "Working", 5, task)
        scanned_since_update += 1
        task.add("fetched")

        if source_message == "DUPLICATE":
            task.add("duplicate")
            continue
        if source_message == "FILTERED":
            task.add("filtered")
            continue
        if source_message.empty or source_message.service:
            task.add("deleted")
            continue

        document = source_message.document
        media_object = (
            getattr(source_message, source_message.media.value, None)
            if source_message.media
            else None
        )
        media_kind = media_counter_key(source_message)
        if media_object and (
            extension_filter(extensions, getattr(media_object, "file_name", None))
            or keyword_filter(keywords, getattr(media_object, "file_name", None))
            or size_filter(
                options["max_size"],
                options["min_size"],
                getattr(media_object, "file_size", None),
            )
        ):
            task.add("filtered")
            continue
        if document and document.file_id in known_duplicates:
            task.add("duplicate")
            continue
        if document and options["skip_duplicate"]:
            # Keep same-task duplicate detection in memory; persist only after send succeeds.
            known_duplicates.append(document.file_id)

        if forward_tag:
            pending_message_ids.append(source_message.id)
            pending_media_counts.append(media_kind)
            if document and options["skip_duplicate"]:
                pending_file_ids.append(document.file_id)
            remaining = task.get("total") - task.get("fetched")
            if len(pending_message_ids) >= batch_size or remaining <= batch_size:
                batch_count = len(pending_message_ids)
                forwarded = await forward(
                    user_id, client, pending_message_ids, progress_message, task, protect
                )
                if forwarded:
                    task.add("total_files", batch_count)
                    for media_type in pending_media_counts:
                        if media_type:
                            task.add(media_type)
                    if user_db:
                        for file_id in pending_file_ids:
                            await user_db.add_file(file_id)
                    await pause_between_messages(random_gap, default_delay)
                else:
                    task.add("deleted", batch_count)
                pending_message_ids.clear()
                pending_file_ids.clear()
                pending_media_counts.clear()
            continue

        details = {
            "msg_id": source_message.id,
            "media": media(source_message),
            "caption": custom_caption(source_message, caption),
            "button": button,
            "protect": protect,
        }
        copied = await copy(user_id, client, details, progress_message, task)
        if copied:
            task.add("total_files")
            if media_kind:
                task.add(media_kind)
            if document and options["skip_duplicate"] and user_db:
                await user_db.add_file(document.file_id)
            await pause_between_messages(random_gap, default_delay)

    return True


@Client.on_callback_query(filters.regex(r"^start_public_"))
async def review_forwarding_task(bot, query):
    user = query.from_user.id
    if query.message.chat.id != user:
        return await query.answer(
            "Open this task in your private chat to review it.", show_alert=True
        )

    forward_id = query.data.split("_", 2)[2]
    task = STS(forward_id)
    if not task.verify():
        return await query.answer("This setup expired. Start again with /forward.", show_alert=True)
    task_data = task.get(full=True)
    if temp.lock.get(user) or task_data.TO in temp.IS_FRWD_CHAT:
        return await query.answer("A forwarding task is already active.", show_alert=True)

    await query.answer()
    from .settings import settings_dashboard

    PENDING_REVIEW[user] = forward_id
    dashboard_text, markup = await settings_dashboard(user, forward_id)
    review_text = (
        f"<b>Review forwarding task</b>\n\n{dashboard_text}\n\n"
        "Changes save immediately. Press <b>Continue & start forwarding</b> when ready."
    )
    await query.message.edit_text(review_text, reply_markup=markup)


@Client.on_callback_query(filters.regex(r"^cancel_public_"))
async def cancel_forwarding_review(bot, query):
    user = query.from_user.id
    if query.message.chat.id != user:
        return await query.answer("Open this setup in your private chat to cancel it.", show_alert=True)
    forward_id = query.data.split("_", 2)[2]
    if PENDING_REVIEW.get(user) == forward_id:
        PENDING_REVIEW.pop(user, None)
    await query.answer("Forward setup cancelled.")
    await query.message.delete()


@Client.on_callback_query(filters.regex(r"^continue_public_"))
async def pub_(bot, message):
    user = message.from_user.id
    temp.CANCEL[user] = False
    frwd_id = message.data.split("_")[2]
    if temp.lock.get(user) and str(temp.lock.get(user))=="True":
      return await message.answer("A forwarding task is already active. Please wait for it to finish.", show_alert=True)
    sts = STS(frwd_id)
    if not sts.verify():
      await message.answer("your are clicking on my old button", show_alert=True)
      return await message.message.delete()
    i = sts.get(full=True)
    if i.TO in temp.IS_FRWD_CHAT:
      return await message.answer("A task is already running in this destination. Please try again when it finishes.", show_alert=True)
    # Reserve immediately so rapid repeated taps cannot start overlapping tasks.
    temp.lock[user] = True
    temp.IS_FRWD_CHAT.append(i.TO)
    PENDING_REVIEW.pop(user, None)
    m = await msg_edit(message.message, "<b>Preparing your forwarding task…</b>")
    _bot, caption, forward_tag, datas, protect, button = await sts.get_data(user)
    random_gap = normalize_random_gap(datas.get("random_gap"))
    if not _bot:
      temp.lock[user] = False
      if i.TO in temp.IS_FRWD_CHAT:
          temp.IS_FRWD_CHAT.remove(i.TO)
      return await msg_edit(m, "<b>No forwarding account is connected.</b> Add one in <code>/settings</code> to continue.", wait=True)
    if _bot['is_bot'] == True:
        data = _bot['token']
    else:
        data = _bot['session']
    client = None
    try:
      il = bool(_bot['is_bot'])
      client = await get_client(data, is_bot=il)
      await client.start()
    except Exception:
      if client is not None:
          try:
              await client.stop()
          except Exception:
              logger.debug("Failed to clean up a failed forwarding client for %s", user)
      temp.lock[user] = False
      if i.TO in temp.IS_FRWD_CHAT:
          temp.IS_FRWD_CHAT.remove(i.TO)
      return await msg_edit(m, "<b>Could not start the saved forwarding account.</b> Check its token/session in Settings.", wait=True)
    await msg_edit(m, "<b>Checking chat access…</b>")
    try:
       await client.get_messages(sts.get("FROM"), sts.get("limit"))
    except:
       await msg_edit(m, "<b>Can't access the source chat.</b> Make sure the connected account is a member, or has the required admin permission.", retry_btn(frwd_id), True)
       return await stop(client, user, counted=False, destination=i.TO)
    try:
       k = await client.send_message(i.TO, "Testing")
       await k.delete()
    except:
       await msg_edit(m, "<b>Can't post to the destination.</b> Give the connected account permission to send messages there.", retry_btn(frwd_id), True)
       return await stop(client, user, counted=False, destination=i.TO)
    user_have_db = False
    dburi = datas['db_uri']
    if dburi is not None:
        connected, user_db = await connect_user_db(user, dburi, i.TO)
        if not connected:
            await msg_edit(m, "<b>Optional duplicate database unavailable.</b> Duplicate records may not survive a restart.")
        else:
            user_have_db = True
    temp.forwardings += 1
    await db.add_frwd(user)
    await send(client, user, "<b>Forwarding started.</b>")
    sts.add(time=True)
    sleep = 1 if _bot['is_bot'] else 10
    await msg_edit(m, "<b>Forwarding messages…</b>")
    dup_files = []
    if user_have_db and datas["skip_duplicate"]:
        async for old_file in user_db.get_all_files():
            dup_files.append(old_file["file_id"])
    try:
        await edit(user, m, "Working", 5, sts)
        completed = await forward_source_messages(
            user,
            client,
            m,
            sts,
            sts.get("skip"),
            datas,
            caption,
            forward_tag,
            protect,
            button,
            user_db if user_have_db else None,
            dup_files,
            random_gap,
            sleep,
        )
        if not completed:
            if user_have_db:
                await user_db.close()
            return
    except Exception as error:
        logger.exception("Forwarding task failed for user %s", user)
        await msg_edit(m, f"<b>Forwarding failed:</b>\n<code>{error}</code>", wait=True)
        if user_have_db:
            await user_db.close()
        return await stop(client, user, destination=sts.TO)

    await send(client, user, "<b>✓ Forwarding complete.</b>")
    await edit(user, m, "Complete", "completed", sts)
    if user_have_db:
        await user_db.close()
    await stop(client, user, destination=sts.TO)



async def copy(user, bot, msg, m, sts):
   try:
     if msg.get("media") and msg.get("caption"):
        await bot.send_cached_media(
              chat_id=sts.get('TO'),
              file_id=msg.get("media"),
              caption=msg.get("caption"),
              reply_markup=msg.get('button'),
              protect_content=msg.get("protect"))
     else:
        await bot.copy_message(
              chat_id=sts.get('TO'),
              from_chat_id=sts.get('FROM'),
              caption=msg.get("caption"),
              message_id=msg.get("msg_id"),
              reply_markup=msg.get('button'),
              protect_content=msg.get("protect"))
   except FloodWait as e:
     await edit(user, m, 'Working', e.value, sts)
     await asyncio.sleep(e.value)
     await edit(user, m, 'Working', 5, sts)
     return await copy(user, bot, msg, m, sts)
   except Exception:
     logger.warning("Could not copy a source message for user %s", user)
     sts.add('deleted')
     return False
   return True


async def forward(user, bot, msg, m, sts, protect):
   try:
     await bot.forward_messages(
           chat_id=sts.get('TO'),
           from_chat_id=sts.get('FROM'),
           protect_content=protect,
           message_ids=msg)
   except FloodWait as e:
     await edit(user, m, 'Working', e.value, sts)
     await asyncio.sleep(e.value)
     await edit(user, m, 'Working', 5, sts)
     return await forward(user, bot, msg, m, sts, protect)
   except Exception:
     logger.warning("Could not forward a batch of source messages for user %s", user)
     return False
   return True


async def msg_edit(msg, text, button=None, wait=None):
    try:
        return await msg.edit(text, reply_markup=button)
    except MessageNotModified:
        pass
    except FloodWait as e:
        if wait:
           await asyncio.sleep(e.value)
           return await msg_edit(msg, text, button, wait)


def render_progress_bar(percentage, width=20):
   value = max(0.0, min(100.0, float(percentage)))
   filled = min(width, int(value * width / 100))
   return f"[{('█' * filled)}{('░' * (width - filled))}]"


async def edit(user, msg, title, status, sts):
   key = (user, msg.id)
   now_monotonic = time.monotonic()
   terminal = status in {"cancelled", "completed"}
   last_edit = _LAST_PROGRESS_EDIT.get(key)
   if not terminal and last_edit is not None and now_monotonic - last_edit < _PROGRESS_EDIT_INTERVAL:
       return
   _LAST_PROGRESS_EDIT[key] = now_monotonic
   i = sts.get(full=True)
   status = 'Forwarding' if status == 5 else f"sleeping {status} s" if str(status).isnumeric() else status
   percentage_value = max(0.0, min(100.0, float(i.fetched) * 100 / float(i.total or 1)))
   percentage = f"{percentage_value:.0f}"
   progress_bar = render_progress_bar(percentage_value)
   await update_forward(
       user_id=user,
       last_id=None,
       start_time=i.start,
       limit=i.limit,
       chat_id=i.FROM,
       toid=i.TO,
       forward_id=None,
       msg_id=msg.id,
       fetched=i.fetched,
       deleted=i.deleted,
       total=i.total_files,
       videos=i.videos,
       photos=i.photos,
       duplicate=i.duplicate,
       skip=i.skip,
       filterd=i.filtered,
   )
   elapsed_seconds = max(0, int(time.time() - i.start))
   speed = sts.divide(i.fetched, elapsed_seconds)
   remaining_messages = max(0, i.total - i.fetched)
   eta_seconds = round(remaining_messages / speed) if speed > 0 else 0
   eta = TimeFormatter(milliseconds=eta_seconds * 1000) or "0s"
   text = TEXT.format(
       i.fetched,
       i.total_files,
       i.videos,
       i.photos,
       i.duplicate,
       i.deleted,
       i.skip,
       i.filtered,
       status,
       percentage,
       progress_bar,
       eta,
       title,
   )
   if terminal:
      buttons = [[InlineKeyboardButton('✅ Done · Close', callback_data='close_btn')]]
   else:
      buttons = [[InlineKeyboardButton('🛑 Cancel task', callback_data='terminate_frwd')]]
   await msg_edit(msg, text, InlineKeyboardMarkup(buttons))
   if terminal:
      _LAST_PROGRESS_EDIT.pop(key, None)


async def is_cancelled(client, user, msg, sts):
   if temp.CANCEL.get(user)==True:
      if sts.TO in temp.IS_FRWD_CHAT:
         temp.IS_FRWD_CHAT.remove(sts.TO)
      await edit(user, msg, 'Cancelled', "cancelled", sts)
      await send(client, user, "<b>Forwarding cancelled.</b>")
      await stop(client, user)
      return True
   return False


async def stop(client, user, counted=True, destination=None):
   try:
     await client.stop()
   except Exception:
     logger.debug("Forwarding client cleanup failed for user %s", user, exc_info=True)
   await db.rmve_frwd(user)
   if counted:
       temp.forwardings = max(0, temp.forwardings - 1)
   if destination in temp.IS_FRWD_CHAT:
       temp.IS_FRWD_CHAT.remove(destination)
   temp.lock[user] = False


async def send(bot, user, text):
   try:
      await bot.send_message(user, text=text)
   except:
      pass


def custom_caption(msg, caption):
  if msg.media:
    if (msg.video or msg.document or msg.audio or msg.photo):
      media = getattr(msg, msg.media.value, None)
      if media:
        file_name = getattr(media, 'file_name', '')
        file_size = getattr(media, 'file_size', '')
        fcaption = getattr(msg, 'caption', '')
        if fcaption:
          fcaption = fcaption.html
        if caption:
          return caption.format(filename=file_name, size=get_size(file_size), caption=fcaption)
        return fcaption
  return None


def get_size(size):
  units = ["Bytes", "KB", "MB", "GB", "TB", "PB", "EB"]
  size = float(size)
  i = 0
  while size >= 1024.0 and i < len(units):
     i += 1
     size /= 1024.0
  return "%.2f %s" % (size, units[i])



def media(msg):
  if msg.media:
     media = getattr(msg, msg.media.value, None)
     if media:
        return getattr(media, 'file_id', None)
  return None


def TimeFormatter(milliseconds: int) -> str:
    seconds, milliseconds = divmod(int(milliseconds), 1000)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    tmp = ((str(days) + "d, ") if days else "") + \
        ((str(hours) + "h, ") if hours else "") + \
        ((str(minutes) + "m, ") if minutes else "") + \
        ((str(seconds) + "s, ") if seconds else "") + \
        ((str(milliseconds) + "ms, ") if milliseconds else "")
    return tmp[:-2]


def retry_btn(id):
    return InlineKeyboardMarkup([[InlineKeyboardButton('🔄 Retry task', callback_data=f"start_public_{id}")]])


@Client.on_callback_query(filters.regex(r'^terminate_frwd$'))
async def terminate_frwding(bot, m):
    user_id = m.from_user.id
    temp.CANCEL[user_id] = True
    await m.answer("Cancellation requested. The current message will finish first.", show_alert=True)


@Client.on_callback_query(filters.regex(r'^fwrdstatus'))
async def status_msg(bot, msg):
    _, status, est_time, percentage, frwd_id = msg.data.split("#")
    sts = STS(frwd_id)
    if not sts.verify():
        return await msg.answer("This task status has expired.", show_alert=True)
    fetched = sts.get("fetched")
    limit = sts.get("limit")
    forwarded = sts.get("total_files")
    remaining = max(0, limit - fetched)
    estimated_remaining = TimeFormatter(milliseconds=int(est_time)) or "0s"
    if status in {"completed", "cancelled"}:
        estimated_remaining = "0s"
    elapsed = await get_bot_uptime(sts.get("start"))
    return await msg.answer(
        PROGRESS.format(
            percentage,
            fetched,
            forwarded,
            sts.get("videos"),
            sts.get("photos"),
            remaining,
            status,
            estimated_remaining,
            elapsed,
        ),
        show_alert=True,
    )


@Client.on_callback_query(filters.regex(r'^close_btn$'))
async def close(bot, update):
    await update.answer()
    await update.message.delete()


@Client.on_message(filters.private & filters.command(['stop']))
async def stop_forward(client, message):
    user_id = message.from_user.id
    sts = await message.reply('<b>Stopping forwarding…</b>')
    await asyncio.sleep(0.5)
    if not await db.is_forwad_exit(message.from_user.id):
        return await sts.edit('<b>No active forwarding task was found.</b>')
    temp.CANCEL[user_id] = True
    await sts.edit("<b>Forwarding stop requested.</b>")


async def restart_pending_forwads(bot, user):
    user = user['user_id']
    settings = await db.get_forward_details(user)
    counted = False
    try:
       skiping = settings['offset']
       fetch = settings['fetched'] - settings['skip']
       temp.forwardings += 1
       counted = True
       forward_id = await store_vars(user)
       sts = STS(forward_id)
       if settings['chat_id'] is None or not sts.verify():
          temp.forwardings = max(0, temp.forwardings - 1)
          counted = False
          await db.rmve_frwd(user)
          return
       sts.add('fetched', value=fetch)
       sts.add('duplicate', value=settings['duplicate'])
       sts.add('filtered', value=settings['filtered'])
       sts.add('deleted', value=settings['deleted'])
       sts.add('total_files', value=settings['total'])
       sts.add('videos', value=settings.get('videos', 0))
       sts.add('photos', value=settings.get('photos', 0))
       m = await bot.get_messages(user, settings['msg_id'])
       _bot, caption, forward_tag, datas, protect, button = await sts.get_data(user)
       i = sts.get(full=True)
       random_gap = normalize_random_gap(datas.get("random_gap"))
       if not _bot:
          temp.forwardings = max(0, temp.forwardings - 1)
          counted = False
          return await msg_edit(m, "<b>No forwarding account is connected.</b> Add one in <code>/settings</code> to continue.", wait=True)
       if _bot['is_bot'] == True:
          data = _bot['token']
       else:
          data = _bot['session']
       client = None
       try:
          il = bool(_bot['is_bot'])
          client = await get_client(data, is_bot=il)
          await client.start()
       except Exception:
          temp.forwardings = max(0, temp.forwardings - 1)
          counted = False
          if client is not None:
              try:
                  await client.stop()
              except Exception:
                  logger.debug("Failed to clean up a failed resumed client for %s", user)
          return await msg_edit(m, "<b>Could not start the saved forwarding account.</b> Check its token/session in Settings.", wait=True)
       try:
          await msg_edit(m, "<b>Checking chat access…</b>")
       except Exception:
          temp.forwardings = max(0, temp.forwardings - 1)
          counted = False
          try:
              await client.stop()
          except Exception:
              logger.debug("Failed to stop an inactive resumed client for %s", user)
          return await db.rmve_frwd(user)
       try:
          await client.get_messages(sts.get("FROM"), sts.get("limit"))
       except:
          await msg_edit(m, "<b>Can't access the source chat.</b> Make sure the connected account is a member, or has the required admin permission.", retry_btn(forward_id), True)
          return await stop(client, user, destination=i.TO)
       try:
          k = await client.send_message(i.TO, "Testing")
          await k.delete()
       except:
          await msg_edit(m, "<b>Can't post to the destination.</b> Give the connected account permission to send messages there.", retry_btn(forward_id), True)
          return await stop(client, user, destination=i.TO)
    except Exception:
       if counted:
           temp.forwardings = max(0, temp.forwardings - 1)
       await db.rmve_frwd(user)
       return
    user_have_db = False
    dburi = datas['db_uri']
    if dburi is not None:
        connected, user_db = await connect_user_db(user, dburi, i.TO)
        if not connected:
            await msg_edit(m, "<b>Optional duplicate database unavailable.</b> Duplicate records may not survive a restart.")
        else:
            user_have_db = True
    try:
        start = settings['start_time']
    except KeyError:
        start = None
    sts.add(time=True, start_time=start)
    sleep = 1 if _bot['is_bot'] else 10
    #await msg_edit(m, "<b>Forwarding messages…</b>")
    temp.IS_FRWD_CHAT.append(i.TO)
    temp.lock[user] = True
    dup_files = []
    if user_have_db and datas["skip_duplicate"]:
        old_files = user_db.get_all_files()
        async for old_file in old_files:
            dup_files.append(old_file["file_id"])
    try:
        await edit(user, m, "Working", 5, sts)
        completed = await forward_source_messages(
            user,
            client,
            m,
            sts,
            skiping,
            datas,
            caption,
            forward_tag,
            protect,
            button,
            user_db if user_have_db else None,
            dup_files,
            random_gap,
            sleep,
        )
        if not completed:
            if user_have_db:
                await user_db.close()
            return
    except Exception as error:
        logger.exception("Resumed forwarding task failed for user %s", user)
        await msg_edit(m, f"<b>Forwarding failed:</b>\n<code>{error}</code>", wait=True)
        if user_have_db:
            await user_db.close()
        return await stop(client, user, destination=sts.TO)

    await send(client, user, "<b>✓ Forwarding complete.</b>")
    if user_have_db:
        await user_db.close()
    await edit(user, m, "Complete", "completed", sts)
    await stop(client, user, destination=sts.TO)



async def store_vars(user_id):
    settings = await db.get_forward_details(user_id)
    fetch = settings['fetched']
    forward_id = f'{user_id}-{fetch}'
    STS(id=forward_id).store(settings['chat_id'], settings['toid'], settings['skip'], settings['limit'])
    return forward_id


async def restart_forwards(client):
    users = await db.get_all_frwd()
    tasks = [restart_pending_forwads(client, user) async for user in users]
    await asyncio.gather(*tasks)
    logger.info("Pending forwarding tasks restored")


async def update_forward(
    user_id,
    chat_id,
    start_time,
    toid,
    last_id,
    limit,
    forward_id,
    msg_id,
    fetched,
    total,
    duplicate,
    deleted,
    skip,
    filterd,
    videos=0,
    photos=0,
):
    details = {
        'chat_id': chat_id,
        'toid': toid,
        'forward_id': forward_id,
        'last_id': last_id,
        'limit': limit,
        'msg_id': msg_id,
        'start_time': start_time,
        'fetched': fetched,
        'offset': fetched,
        'deleted': deleted,
        'total': total,
        'videos': videos,
        'photos': photos,
        'duplicate': duplicate,
        'skip': skip,
        'filtered':filterd
    }
    await db.update_forward(user_id, details)


async def get_bot_uptime(start_time):
    # Calculate the uptime in seconds
    uptime_seconds = int(time.time() - start_time)
    uptime_minutes = uptime_seconds // 60
    uptime_hours = uptime_minutes // 60
    uptime_days = uptime_hours // 24
    uptime_weeks = uptime_days // 7
    uptime_string = ""
    if uptime_weeks != 0:
        uptime_string += f"{uptime_weeks % 7}w, "
    if uptime_days != 0:
        uptime_string += f"{uptime_days % 24}d, "
    if uptime_hours != 0:
        uptime_string += f"{uptime_hours % 24}h, "
    if uptime_minutes != 0:
        uptime_string += f"{uptime_minutes % 60}m, "
    uptime_string += f"{uptime_seconds % 60}s"
    return uptime_string
