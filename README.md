# ESP32 LED control: web + Telegram + USSD

One online app (`app.py`) handles everything. No computer needs to stay on.

## 1. Put the code on GitHub
Create a new repository and upload `app.py` and `requirements.txt`.
(Do not upload `iot.db` or any passwords/tokens.)

## 2. Deploy on a Python host (example: Render)
- New > Web Service > connect your GitHub repo
- Build command: `pip install -r requirements.txt`
- Start command: `gunicorn app:app --workers 1 --threads 4`
- Add these Environment Variables:

| Name | Value |
|---|---|
| DEVICE_KEY | a long random text (also goes in the ESP32 sketch) |
| WEB_PASSWORD | password for the website |
| USSD_PIN | PIN typed on USSD, e.g. 4821 |
| TELEGRAM_TOKEN | token from @BotFather |
| TELEGRAM_SECRET | random letters/numbers, e.g. k39dj28xq |
| ALLOWED_IDS | your Telegram ID(s), comma separated |

After deploy you get a URL like `https://your-app.onrender.com`.

## 3. Test the website
Open the URL, enter WEB_PASSWORD, press ON/OFF.

## 4. ESP32
In `esp32_led.ino` set Wi-Fi name/password, `SERVER` (your URL) and `DEVICE_KEY`,
then upload. The page should show "Device: online" and the LED follows your buttons.

## 5. Telegram
Open this in a browser (replace the 3 parts):

https://api.telegram.org/bot<TELEGRAM_TOKEN>/setWebhook?url=https://your-app.onrender.com/telegram/<TELEGRAM_SECRET>

You should see `"ok":true`. Send /start to your bot. If it says "Not authorized",
copy the ID it shows into ALLOWED_IDS on the host and redeploy.

## 6. USSD (Africa's Talking)
Channel callback URL: `https://your-app.onrender.com/ussd`
Test in their simulator first.

## Notes
- Free hosts may restart or "sleep" the app, and local files like `iot.db` can reset.
  The LED then goes back to OFF. Check your host's current free-tier rules.
- `client.setInsecure()` in the sketch does not verify the server certificate.
  Fine for learning; for a real product add the server's root certificate.
- Never share your tokens, passwords or DEVICE_KEY.
