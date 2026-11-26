# Forword Bot

एक modular Telegram forwarding bot, जिसे long-running worker और HTTP health probe के रूप में deploy किया जा सकता है। Forwarding, settings और duplicate-cleanup सुविधाओं के साथ startup, configuration, persistence और deployment को व्यवस्थित किया गया है।

## मुख्य सुविधाएँ

- Public channels और configured bot/user session के ज़रिये forwarding
- Saved source channels: हर forwarding setup में source चुनें, नया जोड़ें, या पुराना हटाएँ
- Custom captions, duplicate handling और message filters
- Text, documents, videos, photos, audio और video notes में से types चुनकर forwarding; voice messages, animations, stickers और polls हमेशा skip होते हैं
- Custom message buttons उपलब्ध नहीं हैं
- Size, extension और keyword filters
- हर forwarded message के बीच user-configurable random delay (preset या custom range)
- Bot restart के बाद pending forwarding को resume करना
- Settings और per-admin status controls
- Duplicate documents खोजने और साफ़ करने का विकल्प
- सार्वजनिक Instagram post/reel URL भेजने पर media डाउनलोड करके Telegram में वापस भेजना (अधिकतम 45 MB; private posts/cookies समर्थित नहीं)
- `/healthz` पर lightweight container health check
- Inline menu से one-tap forwarding setup और व्यक्तिगत setup/task dashboard (`/status`)
- Kurigram inline-button color styles: navigation/neutral (blue), success (green), और destructive/cancel (red); रंग Telegram client support पर निर्भर करते हैं

> User session जोड़ने पर Telegram account की सुरक्षा और platform terms की जिम्मेदारी operator की है। केवल अपने या अधिकृत chats में forwarding करें।

## आवश्यकताएँ

- Python 3.11+
- Kurigram 2.2.27 (Pyrogram-compatible API)
- yt-dlp (public Instagram media extraction; installed via `requirements.txt`)
- Telegram API credentials: [my.telegram.org](https://my.telegram.org)
- Bot token: [@BotFather](https://t.me/BotFather)
- MongoDB connection URI

## स्थानीय रूप से चलाएँ

```bash
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\\Scripts\\activate
pip install -r requirements.txt
```

पर्यावरण में ये values सेट करें; secrets को Git में commit न करें:

| Variable | ज़रूरी | विवरण |
|---|---:|---|
| `API_ID` | हाँ | Telegram API ID |
| `API_HASH` | हाँ | Telegram API hash |
| `BOT_TOKEN` | हाँ | @BotFather से token |
| `BOT_OWNER` | हाँ | Owner का numeric Telegram user ID (`BOT_OWNER_ID` alias भी स्वीकार है) |
| `DATABASE_URI` | हाँ | MongoDB URI |
| `CREDENTIAL_ENCRYPTION_KEY` | हाँ | Bot tokens, user sessions और custom Mongo URI के लिए Fernet key |
| `DATABASE_NAME` | नहीं | Database नाम; default `forword-bot` |
| `BOT_SESSION` | नहीं | Kurigram session name; default `forwordbot` |
| `LOG_LEVEL` | नहीं | Python logging level; default `INFO` |
| `PORT` | नहीं | Health service port; default `8000` |

पहली बार key बनाने के लिए चलाएँ और परिणाम को deployment secret के रूप में सुरक्षित रखें:

```bash
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
```

`CREDENTIAL_ENCRYPTION_KEY` को हर restart/deployment पर वही रखें और सुरक्षित backup लें; key खोने पर encrypted credentials decrypt नहीं होंगे। Startup पर पुराना plaintext token/session/URI data encrypted रूप में migrate होगा। यदि पुराने deployment ने `DATABASE_NAME` explicitly set नहीं किया था, तो saved data बनाए रखने के लिए upgrade के बाद `DATABASE_NAME` में वही पुराना database name दें; नया default `forword-bot` है। `BOT_SESSION` बदलने पर session पुनः authorize हो सकता है।

फिर bot worker चलाएँ:

```bash
export API_ID=123456
export API_HASH='...'
export BOT_TOKEN='...'
export BOT_OWNER=123456789
export DATABASE_URI='mongodb+srv://...'
export CREDENTIAL_ENCRYPTION_KEY='...'
python -m main
```

Bot startup पर configuration validate होगी, MongoDB ping/index setup होगा और pending forwarding tasks resume होंगे। Missing configuration पर process स्पष्ट error के साथ रुकेगा।

## Docker

```bash
docker build -t forword-bot .
docker run --env-file .env -p 8000:8000 forword-bot
```

Container में Telegram worker और health endpoint दोनों चलेंगे। `GET /healthz` liveness check के लिए है; `GET /` service status JSON देता है। Worker deployment में `Procfile` का `worker: python3 main.py` इस्तेमाल किया जा सकता है।

## Random forwarding gap

Open `/settings` → **Advanced rules** → **Random forwarding gap** to turn the delay off, choose a preset, or enter a range such as `5-15` seconds. A single value such as `8` sets a fixed eight-second delay. The setting is saved per user and also applies when a pending task resumes after restart. The maximum accepted delay is 3600 seconds.

## Telegram commands

| Command | उपयोग |
|---|---|
| `/start` | Bot शुरू करें और menu देखें |
| `/forward` | Forwarding task बनाएँ |
| `/settings` | Bot/session, chats और forwarding settings configure करें |
| `/status` | अपना setup और active forwarding task देखें |
| `/stop` | चल रहा task रोकें |
| `/reset` | अपनी settings reset करें |
| `/unequify` | Duplicate media साफ़ करें |
| `/restart` | Hosting provider के restart निर्देश देखें |

## सुरक्षा और संचालन

- Tokens और MongoDB URI को secrets/environment variables में रखें; logs या issue में साझा न करें।
- MongoDB को network/IP allowlist से सीमित करें और least-privilege database user उपयोग करें।
- Bot/session credentials इस bot के database में रखे जाते हैं; database access को सीमित करें और नियमित backups लें।
- `/restart` अब chat handler से `git pull`/shell command नहीं चलाता। Process restart हमेशा Docker, systemd या hosting platform से करें।
- Container logs stdout पर जाते हैं। `LOG_LEVEL=DEBUG` केवल debugging के लिए उपयोग करें।

## विकास जाँच

```bash
python -m compileall -q .
python -m unittest discover -s tests -v
```

## License

This fork is distributed under the Mozilla Public License 2.0. See `LICENCE` for the full terms.
