"""Telegram copy and message templates used by the bot handlers."""


class Script:
    START_TXT = """<b>Welcome, {}!</b>

I’m <b>Forword Bot</b> — a practical toolkit for managing message forwarding between Telegram chats.

Use the buttons below to explore features, configure your destinations, or read the quick-start guide."""

    HELP_TXT = """<b>Help &amp; commands</b>

<b>Getting started</b>
• <code>/start</code> — open the main menu
• <code>/forward</code> — create a forwarding task
• <code>/settings</code> — configure bots, chats, and filters
• <code>/stop</code> — stop an active forwarding task
• <code>/reset</code> — restore your default settings
• <code>/unequify</code> — find and remove duplicate documents
• <code>/status</code> — check your setup and active task

<b>Forwarding options</b>
Saved source channels can be selected, added, or removed during each forwarding setup. Custom captions, random inter-message delays, duplicate handling, message-type filters, and size, extension, or keyword rules are available in settings.

For private chats, the connected account must have access to the source. The bot or user account needs the required permissions in the destination."""

    HOW_USE_TXT = """<b>Quick start</b>

1. Open <code>/settings</code> and connect a bot or user account.
2. Add at least one destination chat. The connected account must be able to post there.
3. Configure optional filters, captions, and forwarding rules.
4. Run <code>/forward</code> and follow the prompts to select a source and destination.

Use <code>/cancel</code> during setup to leave the current step. A connected user account carries its own security and account risk; only connect an account you control."""

    ABOUT_TXT = """<b>About this bot</b>

A Telegram assistant for configuring and managing message forwarding.

<b>Built with:</b> Python and Kurigram
<b>Version:</b> 1.0"""

    STATUS_TXT = """<b>Service status</b>

<b>Uptime</b>       <code>{}</code>
<b>Users</b>        <code>{}</code>
<b>Connected bots</b> <code>{}</code>
<b>Active tasks</b> <code>{}</code>"""

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

    TEXT = """<b>Forwarding progress</b>

<b>Fetched</b>       <code>{}</code>
<b>Forwarded</b>     <code>{}</code>
<b>Videos</b>        <code>{}</code>
<b>Images</b>        <code>{}</code>
<b>Duplicates</b>    <code>{}</code>
<b>Deleted</b>       <code>{}</code>
<b>Skipped</b>       <code>{}</code>
<b>Filtered</b>      <code>{}</code>
<b>Status</b>        <code>{}</code>
<b>Progress</b>      <code>{}%</code>

<code>{}</code>"""

    DUPLICATE_TEXT = """<b>Duplicate cleanup</b>

<b>Files scanned</b> <code>{}</code>
<b>Duplicates removed</b> <code>{}</code>
<b>Status</b> <code>{}</code>"""

    DOUBLE_CHECK = """<b>Review forwarding task</b>

<b>Account:</b> <code>{botname} (@{botuname})</code>
<b>Source:</b> <code>{from_chat}</code>
<b>Destination:</b> <code>{to_chat}</code>
<b>Messages to skip:</b> <code>{skip}</code>

Before continuing, confirm the connected account can read from the source and post to the destination. Private chats require membership or the appropriate admin permissions."""

    SETTINGS_TXT = (
        "<b>Settings</b>\n\n"
        "Choose an option below to configure your connected accounts, chats, "
        "and forwarding preferences."
    )
