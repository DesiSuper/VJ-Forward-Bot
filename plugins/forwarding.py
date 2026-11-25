
import asyncio
import logging
import time
from html import escape

from pyrogram import Client, filters
from pyrogram.errors import (
    ChatAdminRequired,
    ChatRestricted,
    ChatWriteForbidden,
    FloodWait,
    Forbidden,
    MessageIdInvalid,
    MessageNotModified,
    UserBannedInChannel,
)
from pyrogram.types import InlineKeyboardMarkup

from .ui import InlineKeyboardButton

from config import temp
from database import db
from forwarding_delay import choose_random_gap, normalize_random_gap
from forward_review import PENDING_REVIEW, format_task_setup_preview
from messages import Script

from .clients import CLIENT, get_client, iter_messages
from .db import connect_user_db
from .media_filters import extension_filter, keyword_filter, size_filter
from .utils import STATUS, STS

CLIENT = CLIENT()
logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)
TEXT = Script.TEXT
_PROGRESS_EDIT_INTERVAL = 5.0
_LAST_PROGRESS_EDIT: dict[tuple[int, int], float] = {}
_BACKGROUND_FORWARD_TASKS: set[asyncio.Task] = set()


class DestinationPermissionError(RuntimeError):
    """Raised when Telegram refuses a write to the selected destination."""


_DESTINATION_PERMISSION_ERRORS = (
    ChatAdminRequired,
    ChatRestricted,
    ChatWriteForbidden,
    Forbidden,
    UserBannedInChannel,
)


async def pause_between_messages(gap, default_delay):
    delay = choose_random_gap(gap, default_delay)
    if delay > 0:
        await asyncio.sleep(delay)


async def close_optional_db(user_db):
    if user_db is None:
        return
    try:
        await user_db.close()
    except Exception:
        logger.warning("Could not close optional duplicate database", exc_info=True)


async def persist_task_checkpoint(user_id, progress_message, task):
    state = task.get(full=True)
    await update_forward(
        user_id,
        state.FROM,
        state.start,
        state.TO,
        None,
        state.limit,
        task.id,
        progress_message.id,
        state.fetched,
        state.total_files,
        state.duplicate,
        state.deleted,
        state.skip,
        state.filtered,
        state.videos,
        state.photos,
    )


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

    async def checkpoint_when_safe():
        if not pending_message_ids:
            await persist_task_checkpoint(user_id, progress_message, task)

    async for source_message in iter_messages(
        client,
        chat_id=task.get("FROM"),
        limit=task.get("limit"),
        offset=start_offset,
        filters=options["filters"],
    ):
        if await is_cancelled(client, user_id, progress_message, task):
            return False

        if scanned_since_update % 20 == 0:
            await edit(user_id, progress_message, "Working", 5, task, persist=False)
        scanned_since_update += 1
        task.add("fetched")

        if source_message == "FILTERED":
            task.add("filtered")
            await checkpoint_when_safe()
            continue
        if source_message == "DELETED":
            task.add("deleted")
            await checkpoint_when_safe()
            continue
        if source_message.empty or source_message.service:
            task.add("deleted")
            await checkpoint_when_safe()
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
            await checkpoint_when_safe()
            continue
        unique_key = ("unique", document.file_unique_id) if document and document.file_unique_id else None
        legacy_key = ("legacy", document.file_id) if document else None
        if document and (
            (unique_key is not None and unique_key in known_duplicates)
            or legacy_key in known_duplicates
        ):
            task.add("duplicate")
            await checkpoint_when_safe()
            continue
        if document and options["skip_duplicate"] and unique_key is not None:
            # Keep same-task duplicate detection in memory; persist only after send succeeds.
            if isinstance(known_duplicates, set):
                known_duplicates.add(unique_key)
            else:
                known_duplicates.append(unique_key)

        if forward_tag:
            pending_message_ids.append(source_message.id)
            pending_media_counts.append(media_kind)
            if document and options["skip_duplicate"] and document.file_unique_id:
                pending_file_ids.append(document.file_unique_id)
            remaining = task.get("total") - task.get("fetched")
            if len(pending_message_ids) >= batch_size or remaining <= 0:
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
                        for file_unique_id in pending_file_ids:
                            await user_db.add_file(file_unique_id)
                    await pause_between_messages(random_gap, default_delay)
                else:
                    task.add("deleted", batch_count)
                    if isinstance(known_duplicates, set):
                        known_duplicates.difference_update(("unique", file_id) for file_id in pending_file_ids)
                    else:
                        pending_keys = {("unique", file_id) for file_id in pending_file_ids}
                        known_duplicates[:] = [
                            file_id for file_id in known_duplicates
                            if file_id not in pending_keys
                        ]
                pending_message_ids.clear()
                pending_file_ids.clear()
                pending_media_counts.clear()
                await checkpoint_when_safe()
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
            if document and options["skip_duplicate"] and user_db and document.file_unique_id:
                await user_db.add_file(document.file_unique_id)
            await pause_between_messages(random_gap, default_delay)
        elif document and options["skip_duplicate"] and document.file_unique_id:
            if isinstance(known_duplicates, set):
                known_duplicates.discard(unique_key)
            elif unique_key in known_duplicates:
                known_duplicates.remove(unique_key)
        await checkpoint_when_safe()

    # Flush a final partial forward-tag batch even if the source yielded fewer
    # messages than the saved task limit predicted.
    if pending_message_ids:
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
                for file_unique_id in pending_file_ids:
                    await user_db.add_file(file_unique_id)
            await pause_between_messages(random_gap, default_delay)
        else:
            task.add("deleted", batch_count)
            if isinstance(known_duplicates, set):
                known_duplicates.difference_update(("unique", file_id) for file_id in pending_file_ids)
            else:
                pending_keys = {("unique", file_id) for file_id in pending_file_ids}
                known_duplicates[:] = [
                    file_id for file_id in known_duplicates
                    if file_id not in pending_keys
                ]
        pending_message_ids.clear()
        pending_file_ids.clear()
        pending_media_counts.clear()
        await checkpoint_when_safe()

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


@Client.on_callback_query(filters.regex(r"^review_public_"))
async def return_to_task_review(bot, query):
    user = query.from_user.id
    if query.message.chat.id != user:
        return await query.answer("Open this task in your private chat to review it.", show_alert=True)

    forward_id = query.data.split("_", 2)[2]
    if not forward_id.startswith(f"{user}-"):
        return await query.answer("This task does not belong to your account.", show_alert=True)
    task = STS(forward_id)
    if not task.verify():
        return await query.answer("This setup expired. Start again with /forward.", show_alert=True)
    task_data = task.get(full=True)
    if temp.lock.get(user) or task_data.TO in temp.IS_FRWD_CHAT:
        return await query.answer("A forwarding task is already active.", show_alert=True)
    review = task.get("review") or {}
    if not review:
        return await query.answer("Task review is no longer available. Start again with /forward.", show_alert=True)

    config = await db.get_configs(user)
    review_text = format_task_setup_preview(review, config, task_data.skip)
    reply_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("🚀 Start forwarding", callback_data=f"continue_public_{forward_id}"),
                InlineKeyboardButton("⚙️ Settings", callback_data=f"start_public_{forward_id}"),
            ],
            [InlineKeyboardButton("❌ Cancel", callback_data=f"cancel_public_{forward_id}")],
        ]
    )
    await query.answer()
    PENDING_REVIEW.pop(user, None)
    return await query.message.edit_text(review_text, reply_markup=reply_markup)


@Client.on_callback_query(filters.regex(r"^cancel_public_"))
async def cancel_forwarding_review(bot, query):
    user = query.from_user.id
    if query.message.chat.id != user:
        return await query.answer("Open this setup in your private chat to cancel it.", show_alert=True)
    forward_id = query.data.split("_", 2)[2]
    if PENDING_REVIEW.get(user) == forward_id:
        PENDING_REVIEW.pop(user, None)
    STATUS.pop(forward_id, None)
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
    await message.answer("Starting forwarding…")
    m = await msg_edit(message.message, "<b>Preparing your forwarding task…</b>")
    _bot, caption, forward_tag, datas, protect, button = await sts.get_data(user)
    random_gap = normalize_random_gap(datas.get("random_gap"))
    if not _bot:
      temp.lock[user] = False
      if i.TO in temp.IS_FRWD_CHAT:
          temp.IS_FRWD_CHAT.remove(i.TO)
      STATUS.pop(frwd_id, None)
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
      STATUS.pop(frwd_id, None)
      return await msg_edit(m, "<b>Could not start the saved forwarding account.</b> Check its token/session in Settings.", wait=True)
    await msg_edit(m, "<b>Checking chat access…</b>")
    try:
       await client.get_messages(sts.get("FROM"), sts.get("limit"))
    except Exception:
       logger.info("Forwarding source access check failed for user %s", user, exc_info=True)
       await msg_edit(m, "<b>Can't access the source chat.</b> Make sure the connected account is a member, or has the required admin permission.", retry_btn(frwd_id), True)
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
    try:
        await db.add_frwd(user)
        await send(client, user, "<b>Forwarding started.</b>")
        sts.add(time=True)
        sleep = 1 if _bot['is_bot'] else 10
        await msg_edit(m, "<b>Forwarding messages…</b>")
    except Exception as error:
        logger.exception("Could not initialize forwarding task for user %s", user)
        STATUS.pop(sts.id, None)
        if user_have_db:
            await close_optional_db(user_db)
        await stop(client, user, destination=i.TO)
        return await msg_edit(m, f"<b>Could not initialize forwarding:</b> <code>{escape(str(error))}</code>", wait=True)
    try:
        dup_files = set()
        if user_have_db and datas["skip_duplicate"]:
            async for old_file in await user_db.get_all_files():
                if old_file.get("file_unique_id"):
                    dup_files.add(("unique", old_file["file_unique_id"]))
                elif old_file.get("file_id"):
                    dup_files.add(("legacy", old_file["file_id"]))
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
                await close_optional_db(user_db)
            return
    except Exception as error:
        logger.exception("Forwarding task failed for user %s", user)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        STATUS.pop(sts.id, None)
        if user_have_db:
            await close_optional_db(user_db)
        await stop(client, user, destination=sts.TO)
        return await msg_edit(m, f"<b>Forwarding failed:</b>\n<code>{escape(str(error))}</code>", wait=True)

    await send(client, user, "<b>✓ Forwarding complete.</b>")
    try:
        await edit(user, m, "Complete", "completed", sts)
    except Exception:
        logger.exception("Could not render completed forwarding state for user %s", user)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        STATUS.pop(sts.id, None)
    finally:
        if user_have_db:
            await close_optional_db(user_db)
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
     await edit(user, m, 'Working', e.value, sts, persist=False)
     await asyncio.sleep(e.value)
     await edit(user, m, 'Working', 5, sts, persist=False)
     return await copy(user, bot, msg, m, sts)
   except _DESTINATION_PERMISSION_ERRORS as error:
     raise DestinationPermissionError(
         "The connected account cannot post to the destination. Check its write permissions."
     ) from error
   except MessageIdInvalid:
     logger.info("Source message %s is no longer available", msg.get("msg_id"))
     sts.add('deleted')
     return False
   except Exception:
     logger.exception("Could not copy a source message for user %s", user)
     raise
   return True


async def forward(user, bot, msg, m, sts, protect):
   try:
     await bot.forward_messages(
           chat_id=sts.get('TO'),
           from_chat_id=sts.get('FROM'),
           protect_content=protect,
           message_ids=msg)
   except FloodWait as e:
     await edit(user, m, 'Working', e.value, sts, persist=False)
     await asyncio.sleep(e.value)
     await edit(user, m, 'Working', 5, sts, persist=False)
     return await forward(user, bot, msg, m, sts, protect)
   except _DESTINATION_PERMISSION_ERRORS as error:
     raise DestinationPermissionError(
         "The connected account cannot post to the destination. Check its write permissions."
     ) from error
   except MessageIdInvalid:
     logger.info("Source message batch contains an unavailable message for user %s", user)
     return False
   except Exception:
     logger.exception("Could not forward a batch of source messages for user %s", user)
     raise
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


async def edit(user, msg, title, status, sts, *, persist=True):
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
   if persist:
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
      STATUS.pop(sts.id, None)


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
   try:
       await db.rmve_frwd(user)
   except Exception:
       logger.exception("Could not remove forwarding state for user %s", user)
   finally:
       if counted:
           temp.forwardings = max(0, temp.forwardings - 1)
       if destination in temp.IS_FRWD_CHAT:
           temp.IS_FRWD_CHAT.remove(destination)
       for progress_key in tuple(_LAST_PROGRESS_EDIT):
           if progress_key[0] == user:
               _LAST_PROGRESS_EDIT.pop(progress_key, None)
       temp.lock[user] = False
       temp.CANCEL.pop(user, None)


async def send(bot, user, text):
   try:
      await bot.send_message(user, text=text)
   except Exception:
      logger.debug("Could not send a forwarding notification to user %s", user, exc_info=True)


def custom_caption(msg, caption):
  if msg.media:
    if (msg.video or msg.document or msg.audio or msg.photo):
      media = getattr(msg, msg.media.value, None)
      if media:
        file_name = getattr(media, 'file_name', '')
        file_size = getattr(media, 'file_size', '')
        original_caption = getattr(msg, 'caption', None)
        fcaption = original_caption.html if original_caption else ""
        if caption:
          return caption.format(filename=escape(str(file_name)), size=get_size(file_size), caption=fcaption)
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
    counted = False
    client = None
    m = None
    forward_id = None
    try:
       settings = await db.get_forward_details(user)
       skiping = settings['offset']
       fetch = settings['fetched'] - settings['skip']
       temp.forwardings += 1
       counted = True
       forward_id = await store_vars(user)
       sts = STS(forward_id)
       if settings['chat_id'] is None or not sts.verify():
          temp.forwardings = max(0, temp.forwardings - 1)
          counted = False
          STATUS.pop(forward_id, None)
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
          STATUS.pop(forward_id, None)
          await stop(client, user, destination=i.TO)
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
          logger.exception("Could not start the saved account while restoring user %s", user)
          STATUS.pop(forward_id, None)
          await stop(client, user, destination=i.TO)
          counted = False
          return await msg_edit(m, "<b>Could not start the saved forwarding account.</b> Check its token/session in Settings.", wait=True)
       try:
          await msg_edit(m, "<b>Checking chat access…</b>")
       except Exception:
          logger.exception("Could not update resumed task status for user %s", user)
          STATUS.pop(forward_id, None)
          await stop(client, user, destination=i.TO)
          counted = False
          return
       try:
          await client.get_messages(sts.get("FROM"), sts.get("limit"))
       except Exception:
          logger.info("Resumed forwarding source access check failed for user %s", user, exc_info=True)
          await msg_edit(m, "<b>Can't access the source chat.</b> Make sure the connected account is a member, or has the required admin permission.", retry_btn(forward_id), True)
          await stop(client, user, destination=i.TO)
          counted = False
          return
    except asyncio.CancelledError:
       if forward_id is not None:
           STATUS.pop(forward_id, None)
       if m is not None:
           _LAST_PROGRESS_EDIT.pop((user, m.id), None)
       await stop(client, user, counted=counted)
       raise
    except Exception as error:
       logger.exception("Could not restore pending forwarding task for user %s", user)
       if forward_id is not None:
           STATUS.pop(forward_id, None)
       if m is not None:
           _LAST_PROGRESS_EDIT.pop((user, m.id), None)
       await stop(client, user, counted=counted)
       if m is not None:
           try:
               await msg_edit(
                   m,
                   f"<b>Could not resume forwarding:</b>\\n<code>{escape(str(error))}</code>",
                   wait=True,
               )
           except Exception:
               logger.debug("Could not update failed resume status for user %s", user, exc_info=True)
       return
    user_have_db = False
    user_db = None
    try:
        dburi = datas['db_uri']
        if dburi is not None:
            connected, user_db = await connect_user_db(user, dburi, i.TO)
            if not connected:
                await msg_edit(m, "<b>Optional duplicate database unavailable.</b> Duplicate records may not survive a restart.")
            else:
                user_have_db = True
        start = settings.get('start_time')
        sts.add(time=True, start_time=start)
        sleep = 1 if _bot['is_bot'] else 10
        temp.IS_FRWD_CHAT.append(i.TO)
        temp.lock[user] = True
    except asyncio.CancelledError:
        if user_have_db:
            await close_optional_db(user_db)
        STATUS.pop(sts.id, None)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        await stop(client, user, destination=i.TO)
        raise
    except Exception as error:
        logger.exception("Could not prepare resumed forwarding task for user %s", user)
        if user_have_db:
            await close_optional_db(user_db)
        STATUS.pop(sts.id, None)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        await stop(client, user, destination=i.TO)
        try:
            await msg_edit(
                m,
                f"<b>Could not resume forwarding:</b>\\n<code>{escape(str(error))}</code>",
                wait=True,
            )
        except Exception:
            logger.debug("Could not update failed resume status for user %s", user, exc_info=True)
        return
    try:
        dup_files = set()
        if user_have_db and datas["skip_duplicate"]:
            async for old_file in await user_db.get_all_files():
                if old_file.get("file_unique_id"):
                    dup_files.add(("unique", old_file["file_unique_id"]))
                elif old_file.get("file_id"):
                    dup_files.add(("legacy", old_file["file_id"]))
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
                await close_optional_db(user_db)
            return
    except asyncio.CancelledError:
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        STATUS.pop(sts.id, None)
        if user_have_db:
            await close_optional_db(user_db)
        try:
            await client.stop()
        except Exception:
            logger.debug("Could not stop cancelled resumed client for %s", user, exc_info=True)
        temp.forwardings = max(0, temp.forwardings - 1)
        if sts.TO in temp.IS_FRWD_CHAT:
            temp.IS_FRWD_CHAT.remove(sts.TO)
        temp.lock[user] = False
        temp.CANCEL.pop(user, None)
        raise
    except Exception as error:
        logger.exception("Resumed forwarding task failed for user %s", user)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        STATUS.pop(sts.id, None)
        if user_have_db:
            await close_optional_db(user_db)
        await stop(client, user, destination=sts.TO)
        return await msg_edit(m, f"<b>Forwarding failed:</b>\n<code>{escape(str(error))}</code>", wait=True)

    await send(client, user, "<b>✓ Forwarding complete.</b>")
    try:
        await edit(user, m, "Complete", "completed", sts)
    except Exception:
        logger.exception("Could not render completed resumed task for user %s", user)
        _LAST_PROGRESS_EDIT.pop((user, m.id), None)
        STATUS.pop(sts.id, None)
    finally:
        if user_have_db:
            await close_optional_db(user_db)
        await stop(client, user, destination=sts.TO)



async def store_vars(user_id):
    settings = await db.get_forward_details(user_id)
    fetch = settings['fetched']
    forward_id = f'{user_id}-{fetch}'
    STS(forward_id).store(settings['chat_id'], settings['toid'], settings['skip'], settings['limit'])
    return forward_id


def _forget_background_forward_task(task: asyncio.Task, user_id: int) -> None:
    _BACKGROUND_FORWARD_TASKS.discard(task)
    temp.lock[user_id] = False
    if task.cancelled():
        return
    error = task.exception()
    if error is not None:
        logger.error(
            "A background resumed forwarding task crashed",
            exc_info=(type(error), error, error.__traceback__),
        )


async def _resume_forward_job(client, user):
    user_id = int(user["user_id"])
    temp.lock[user_id] = True
    try:
        await restart_pending_forwads(client, user)
    finally:
        temp.lock[user_id] = False


async def restart_forwards(client):
    """Schedule pending jobs without delaying command and callback handling."""
    users = await db.get_all_frwd()
    scheduled = 0
    async for user in users:
        user_id = int(user["user_id"])
        temp.lock[user_id] = True
        task = asyncio.create_task(
            _resume_forward_job(client, user),
            name=f"resume-forward-{user_id}",
        )
        _BACKGROUND_FORWARD_TASKS.add(task)
        task.add_done_callback(
            lambda completed, uid=user_id: _forget_background_forward_task(completed, uid)
        )
        scheduled += 1
    logger.info("Scheduled %s pending forwarding task(s)", scheduled)


async def cancel_pending_forwards() -> None:
    """Stop in-flight restoration workers cleanly during process shutdown."""
    tasks = tuple(_BACKGROUND_FORWARD_TASKS)
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


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
