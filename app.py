import hmac
import os
import sqlite3
from datetime import datetime, timezone

import requests
from flask import Flask, jsonify, render_template_string, request

app = Flask(__name__)

# ---------- Settings (set these as environment variables on the host) ----------
DEVICE_KEY = os.environ.get("DEVICE_KEY", "change-me-123")       # ESP32 uses this
WEB_PASSWORD = os.environ.get("WEB_PASSWORD", "change-me")       # website login
USSD_PIN = os.environ.get("USSD_PIN", "1234")                    # PIN typed on USSD
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN", "")            # from BotFather
TELEGRAM_SECRET = os.environ.get("TELEGRAM_SECRET", "")          # random text for webhook URL
ALLOWED_IDS = {int(x) for x in os.environ.get("ALLOWED_IDS", "").replace(" ", "").split(",") if x}
DB = os.environ.get("DB_PATH", "iot.db")
DEVICE_ID = "esp32-1"


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init():
    with db() as c:
        c.execute("""CREATE TABLE IF NOT EXISTS devices (
            id TEXT PRIMARY KEY, led TEXT DEFAULT 'OFF', last_seen TEXT)""")
        c.execute("""CREATE TABLE IF NOT EXISTS log (
            id INTEGER PRIMARY KEY AUTOINCREMENT, device TEXT,
            state TEXT, source TEXT, at TEXT)""")
        c.execute("INSERT OR IGNORE INTO devices (id) VALUES (?)", (DEVICE_ID,))


init()


def now():
    return datetime.now(timezone.utc)


def set_led(state, source):
    """One function used by website, Telegram and USSD."""
    with db() as c:
        c.execute("UPDATE devices SET led=? WHERE id=?", (state, DEVICE_ID))
        c.execute("INSERT INTO log (device,state,source,at) VALUES (?,?,?,?)",
                  (DEVICE_ID, state, source, now().isoformat()))


def get_status():
    with db() as c:
        row = c.execute("SELECT * FROM devices WHERE id=?", (DEVICE_ID,)).fetchone()
    online = False
    if row["last_seen"]:
        age = (now() - datetime.fromisoformat(row["last_seen"])).total_seconds()
        online = age < 15
    return row["led"], online


def web_ok():
    return hmac.compare_digest(request.headers.get("X-Password", ""), WEB_PASSWORD)


# ---------------- ESP32 asks for its command (plain text: ON or OFF) ----------------
@app.get("/api/esp/<dev>")
def esp_poll(dev):
    if not hmac.compare_digest(request.args.get("key", ""), DEVICE_KEY):
        return "unauthorized", 401
    with db() as c:
        c.execute("UPDATE devices SET last_seen=? WHERE id=?", (now().isoformat(), dev))
        row = c.execute("SELECT led FROM devices WHERE id=?", (dev,)).fetchone()
    return (row["led"] if row else "OFF"), 200, {"Content-Type": "text/plain"}


# ---------------- Website API ----------------
@app.post("/api/led")
def api_led():
    if not web_ok():
        return jsonify(error="wrong password"), 401
    state = (request.json or {}).get("state", "").upper()
    if state not in ("ON", "OFF"):
        return jsonify(error="state must be ON or OFF"), 400
    set_led(state, "web")
    return jsonify(ok=True, led=state)


@app.get("/api/status")
def api_status():
    if not web_ok():
        return jsonify(error="wrong password"), 401
    led, online = get_status()
    return jsonify(led=led, online=online)


# ---------------- USSD (Africa's Talking calls this) ----------------
@app.post("/ussd")
def ussd():
    text = request.form.get("text", "")
    parts = text.split("*") if text else []
    plain = {"Content-Type": "text/plain"}

    if not parts:
        return "CON Enter PIN:", 200, plain
    if not hmac.compare_digest(parts[0], USSD_PIN):
        return "END Wrong PIN.", 200, plain
    if len(parts) == 1:
        return "CON LED Control\n1. Turn ON\n2. Turn OFF\n3. Status", 200, plain

    choice = parts[1]
    if choice == "1":
        set_led("ON", "ussd")
        return "END LED is now ON.", 200, plain
    if choice == "2":
        set_led("OFF", "ussd")
        return "END LED is now OFF.", 200, plain
    if choice == "3":
        led, online = get_status()
        return f"END LED is {led}. Device {'online' if online else 'offline'}.", 200, plain
    return "END Invalid choice.", 200, plain


# ---------------- Telegram webhook ----------------
def tg_send(chat_id, text):
    try:
        requests.post(f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
                      json={"chat_id": chat_id, "text": text}, timeout=10)
    except Exception as e:
        print("Telegram send error:", e)


def tg_handle(msg):
    chat_id = msg["chat"]["id"]
    text = (msg.get("text") or "").strip().lower().split("@")[0]

    if chat_id not in ALLOWED_IDS:
        tg_send(chat_id, f"Not authorized. Your ID is {chat_id}.\n"
                         f"Add it to ALLOWED_IDS on the server.")
        return

    if text in ("/start", "/help"):
        tg_send(chat_id, "Commands:\n/on - LED on\n/off - LED off\n/status - show status")
    elif text in ("/on", "/off"):
        state = text[1:].upper()
        set_led(state, "telegram")
        tg_send(chat_id, f"LED {state}")
    elif text == "/status":
        led, online = get_status()
        tg_send(chat_id, f"LED: {led}\nDevice: {'online' if online else 'offline'}")
    else:
        tg_send(chat_id, "Unknown command. Send /help")


@app.post("/telegram/<secret>")
def telegram(secret):
    if not TELEGRAM_SECRET or not hmac.compare_digest(secret, TELEGRAM_SECRET):
        return "forbidden", 403
    upd = request.get_json(silent=True) or {}
    if "message" in upd:
        tg_handle(upd["message"])
    return "ok"


# ---------------- Website page ----------------
PAGE = """<!doctype html>
<html><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ESP32 LED</title>
<style>
body{font-family:sans-serif;max-width:360px;margin:40px auto;text-align:center}
button{font-size:20px;padding:16px 28px;margin:8px;border:0;border-radius:10px;cursor:pointer}
#on{background:#2e9e4f;color:#fff}#off{background:#c0392b;color:#fff}
input{font-size:18px;padding:10px;width:200px}
#bulb{font-size:64px}
</style></head><body>
<h2>ESP32 LED Control</h2>
<div id="login" style="display:none">
  <p>Enter password</p>
  <input id="pw" type="password"><br><br>
  <button onclick="login()" style="background:#444;color:#fff">Login</button>
  <p id="err" style="color:#c0392b"></p>
</div>
<div id="ctl" style="display:none">
  <div id="bulb">⚫</div>
  <p>LED: <b id="led">?</b> | Device: <b id="net">?</b></p>
  <button id="on" onclick="send('ON')">Turn ON</button>
  <button id="off" onclick="send('OFF')">Turn OFF</button>
</div>
<script>
let pw = sessionStorage.getItem('pw') || '';
function hdr(){return {'Content-Type':'application/json','X-Password':pw}}
function login(){pw=document.getElementById('pw').value;sessionStorage.setItem('pw',pw);refresh(true);}
async function send(s){
  await fetch('/api/led',{method:'POST',headers:hdr(),body:JSON.stringify({state:s})});
  refresh();
}
async function refresh(fromLogin){
  const res=await fetch('/api/status',{headers:hdr()});
  if(res.status===401){
    document.getElementById('ctl').style.display='none';
    document.getElementById('login').style.display='block';
    document.getElementById('err').textContent=fromLogin?'Wrong password':'';
    return;
  }
  document.getElementById('login').style.display='none';
  document.getElementById('ctl').style.display='block';
  const r=await res.json();
  document.getElementById('led').textContent=r.led;
  document.getElementById('net').textContent=r.online?'online':'offline';
  document.getElementById('bulb').textContent=r.led==='ON'?'💡':'⚫';
}
refresh();setInterval(refresh,2000);
</script></body></html>"""


@app.get("/")
def home():
    return render_template_string(PAGE)


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
