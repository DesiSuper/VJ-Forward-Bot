"""Telegram copy and message templates used by the bot handlers."""


class Script:
    START_TXT = """<b>Welcome, {}!</b>

I’m <b>Forword Bot</b>. Forward messages, manage chats, and filter content.

Choose an option below to get started."""

    HELP_TXT = """<b>Help &amp; commands</b>

• <code>/forward</code> — start forwarding
• <code>/settings</code> — manage accounts, chats, and filters
• <code>/status</code> — view setup and task status
• <code>/stop</code> — stop forwarding
• <code>/reset</code> — reset your settings
• <code>/unequify</code> — remove duplicate files
• <code>/insta on|off|status</code> — admin Instagram controls

Connect an account with source access and permission to post in the destination."""

    GROUP_HELP_TXT = """<b>Group moderation · admin PM only</b>

• <code>/dlink instagram.com/* 30s</code> — add/update a link rule
• <code>/dlink list</code> — view domain-link rules
• <code>/blacklist word add bad phrase</code> / <code>/blacklist word remove bad phrase</code>
• <code>/blacklist url add instagram.com</code> / <code>/blacklist url remove instagram.com</code>
• <code>/blacklistdelay word bad phrase 30s</code> / <code>/blacklistdelay url instagram.com 2m</code>
• <code>/blacklist list</code>, <code>/blacklist list word</code>, <code>/blacklist list url</code>
• <code>/ghelp</code> — show this guide

Rules are shared across groups. They delete matching messages from everyone after the configured delay. Use <code>0s</code> for immediate deletion."""

    HOW_USE_TXT = """<b>Quick start</b>

1. Connect an account in <code>/settings</code>.
2. Add a destination and make sure the account can post there.
3. Run <code>/forward</code> and choose a source.

Use <code>/cancel</code> to stop setup. Connect only accounts you control."""

    FROM_MSG = (
        "<b>Choose a source chat</b>\n\n"
        "Forward a message from the source or send a link to its latest message.\n"
        "Send <code>/cancel</code> to stop."
    )
    SKIP_MSG = (
        "<b>Messages to skip</b>\n\n"
        "Enter how many messages to skip from the beginning.\n"
        "Default: <code>0</code>\n"
        "Send <code>/cancel</code> to stop."
    )
    CANCEL = "<b>Setup cancelled.</b>"
    BOT_DETAILS = (
        "<b>Connected bot</b>\n\n"
        "<b>Name:</b> <code>{}</code>\n"
        "<b>ID:</b> <code>{}</code>\n"
        "<b>Username:</b> @{}"
    )
    USER_DETAILS = (
        "<b>Connected user account</b>\n\n"
        "<b>Name:</b> <code>{}</code>\n"
        "<b>ID:</b> <code>{}</code>\n"
        "<b>Username:</b> @{}"
    )

    TEXT = """🚀 <b>Forwarding progress</b>
━━━━━━━━━━━━━━━━━━
📥 <b>Fetched:</b> <code>{}</code>
📤 <b>Forwarded:</b> <code>{}</code>
🎥 <b>Videos:</b> <code>{}</code>
🖼️ <b>Images:</b> <code>{}</code>
♻️ <b>Duplicates:</b> <code>{}</code>
🗑 <b>Deleted:</b> <code>{}</code>
⏭ <b>Skipped:</b> <code>{}</code>
🔎 <b>Filtered:</b> <code>{}</code>
⚡ <b>Status:</b> <code>{}</code>
📊 <b>Progress:</b> <code>{}%</code>
<code>{}</code>
⏳ <b>ETA:</b> <code>{}</code>

📝 <code>{}</code>"""

    DUPLICATE_TEXT = """<b>Duplicate cleanup</b>

<b>Files scanned</b> <code>{}</code>
<b>Duplicates removed</b> <code>{}</code>
<b>Status</b> <code>{}</code>"""

    DOUBLE_CHECK = """<b>Review forwarding task</b>

<b>Account:</b> <code>{botname} (@{botuname})</code>
<b>Source:</b> <code>{from_chat}</code>
<b>Destination:</b> <code>{to_chat}</code>
<b>Skip:</b> <code>{skip}</code>

Make sure the account can access both chats."""

    SETTINGS_TXT = "<b>Settings</b>\n\nManage accounts, chats, and forwarding options."
