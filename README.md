# Forword Bot

Telegram message forwarding with per-admin settings, filters, duplicate cleanup, and group moderation. Runs as a worker with an optional HTTP health check.

## Features

- Forward from public or private chats with a connected bot or user account
- Save sources and destinations; configure captions, delays, and filters
- Resume pending forwarding tasks after restart
- Remove duplicate files and download public Instagram media (up to 45 MB)
- Manage shared group link and word rules from an admin private chat
- Health endpoint at `/healthz`

Only configured admins can use the bot. Connect only accounts you control and have permission to use.

## Requirements

- Python 3.11+
- Telegram API credentials from [my.telegram.org](https://my.telegram.org)
- A bot token from [@BotFather](https://t.me/BotFather)
- MongoDB connection URI

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

Set these environment variables. Keep secrets out of Git:

| Variable | Required | Description |
|---|---:|---|
| `API_ID` | Yes | Telegram API ID |
| `API_HASH` | Yes | Telegram API hash |
| `BOT_TOKEN` | Yes | Bot token |
| `BOT_OWNER` | Yes | One or more admin IDs, separated by spaces or commas; `BOT_OWNER_ID` is also accepted |
| `DATABASE_URI` | Yes | MongoDB URI |
| `CREDENTIAL_ENCRYPTION_KEY` | Yes | Fernet key for stored tokens, sessions, and custom database URIs |
| `DATABASE_NAME` | No | Database name; defaults to `forword-bot` |
| `BOT_SESSION` | No | Session name; defaults to `forwordbot` |
| `LOG_LEVEL` | No | Log level; defaults to `INFO` |
| `PORT` | No | Health server port; defaults to `8000` |

Generate a key once and store it as a deployment secret:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

Keep `CREDENTIAL_ENCRYPTION_KEY` unchanged and backed up. Losing it makes encrypted credentials unreadable. On startup, legacy plaintext credentials are encrypted. Keep your existing `DATABASE_NAME` when upgrading; changing `BOT_SESSION` may require reauthorization.

Example:

```bash
export API_ID=123456
export API_HASH='...'
export BOT_TOKEN='...'
export BOT_OWNER='123456789 987654321'
export DATABASE_URI='mongodb+srv://...'
export CREDENTIAL_ENCRYPTION_KEY='...'
python -m main
```

The bot validates configuration, connects to MongoDB, and resumes pending tasks at startup.

## Docker

```bash
docker build -t forword-bot .
docker run --env-file .env -p 8000:8000 forword-bot
```

`GET /healthz` is the liveness check; `GET /` returns service status. For worker-only hosting, use `worker: python3 main.py` from the `Procfile`.

## Forwarding delay

In `/settings`, open **Advanced rules → Random forwarding gap**. Choose a preset or enter a range such as `5-15` seconds. A single value sets a fixed delay; maximum is 3600 seconds.

## Commands

| Command | Purpose |
|---|---|
| `/start` | Open the main menu |
| `/forward` | Start a forwarding task |
| `/settings` | Manage accounts, chats, and filters |
| `/status` | View setup and task status |
| `/stop` | Stop forwarding |
| `/reset` | Reset your settings |
| `/unequify` | Find and remove duplicate files |
| `/insta on\|off\|status` | Admin Instagram controls |
| `/ghelp` | View group moderation commands (admin PM only) |
| `/restart` | View host restart guidance |

## Security

- Store tokens and database URIs in environment secrets; never post them in logs or issues.
- Restrict MongoDB access and use regular backups.
- Restart the process through Docker, systemd, or your hosting platform; `/restart` does not run shell commands.
- Use `LOG_LEVEL=DEBUG` only when troubleshooting.

## Tests

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

## License

Mozilla Public License 2.0. See `LICENCE` for the terms.
