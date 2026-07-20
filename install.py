import os, sys, json, base64, subprocess, time, uuid as uuid_lib, secrets, zipfile, socket, threading, hashlib, struct
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN: DOMAIN = os.environ.get('RAILWAY_STATIC_URL', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

# Railway به ما PORT میده، Xray روی همون PORT گوش میده
XRAY_PORT = int(os.environ.get('PORT', 8080))
PANEL_PORT = XRAY_PORT + 1  # پنل روی پورت بعدی

# اگه پورت 443 داریم
if XRAY_PORT == 443:
    PANEL_PORT = 8443

print(f"Domain: {DOMAIN} | Xray: {XRAY_PORT} | Panel: {PANEL_PORT}")

current_uid = str(uuid_lib.uuid4())
current_path = f"/ws/{current_uid}"
current_url = ""

def download_xray():
    if os.path.exists('./xray'): return True
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        return True
    except: return False

def build_config(uid, path):
    return {
        "log": {"loglevel": "error"},
        "inbounds": [
            {
                "listen": "0.0.0.0",
                "port": XRAY_PORT,
                "protocol": "vless",
                "settings": {"clients": [{"id": uid}], "decryption": "none"},
                "streamSettings": {
                    "network": "ws",
                    "security": "none",
                    "wsSettings": {"path": path}
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "listen": "127.0.0.1",
                "port": PANEL_PORT,
                "protocol": "dokodemo-door",
                "settings": {"address": "127.0.0.1", "port": PANEL_PORT, "network": "tcp"},
                "tag": "panel"
            }
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct"}
        ]
    }

def make_url(uid, path):
    params = f"security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome"
    return f"vless://{uid}@{DOMAIN}:443?{params}#Spinel"

download_xray()
with open('xray.json', 'w') as f: json.dump(build_config(current_uid, current_path), f)

try:
    subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print(f"[+] Xray started on {XRAY_PORT}")
except: pass

current_url = make_url(current_uid, current_path)

class PanelHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '':
            html = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Spinel VLESS</title>
<style>:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--blue:#58a6ff;--green:#3fb950;--text:#c9d1d9;--dim:#8b949e}}
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.nav{{background:var(--card);border-bottom:1px solid var(--border);padding:15px;text-align:center}}
.nav h1{{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.container{{max-width:650px;margin:0 auto;padding:12px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin:12px 0}}
.card h2{{color:var(--blue);font-size:.95em;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:8px}}
.config-box{{background:rgba(0,0,0,.4);padding:10px;border-radius:8px;word-break:break-all;font-family:monospace;font-size:.7em;color:var(--green);margin:8px 0;line-height:1.6;max-height:150px;overflow-y:auto}}
.info{{color:var(--dim);font-size:.7em;margin:3px 0}}
.btn{{padding:10px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.8em;margin:4px 0;width:100%}}
.btn-g{{background:#238636;color:#fff}}.btn-b{{background:#1f6feb;color:#fff}}
</style></head><body>
<div class="nav"><h1>🌀 Spinel VLESS</h1><p style="color:var(--dim);font-size:.75em">{DOMAIN}</p></div>
<div class="container">
<div class="card"><h2>📡 VLESS Config</h2>
<div class="config-box" id="config">{current_url}</div>
<p class="info">Address: {DOMAIN} | Port: 443</p>
<p class="info">Path: {current_path} | Security: TLS</p>
<p class="info">UUID: {current_uid[:16]}...</p>
<button class="btn btn-g" onclick="copy()">📋 Copy</button>
<button class="btn btn-b" onclick="gen()">🔄 New</button>
</div></div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('config').textContent);alert('Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url}}
</script></body></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == '/new':
            new_uid = str(uuid_lib.uuid4())
            new_path = f"/ws/{new_uid}"
            with open('xray.json', 'w') as f: json.dump(build_config(new_uid, new_path), f)
            subprocess.run(['pkill', 'xray'], capture_output=True)
            time.sleep(1)
            subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            new_url = make_url(new_uid, new_path)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':new_url}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, f, *a): pass

print(f"✅ Panel: http://{DOMAIN}:{PANEL_PORT}")
print(f"✅ VLESS: {current_url}")

# پنل روی پورت داخلی
panel = HTTPServer(('127.0.0.1', PANEL_PORT), PanelHandler)
threading.Thread(target=panel.serve_forever, daemon=True).start()

# Xray مستقیم روی PORT اصلی
print(f"✅ Xray listening on 0.0.0.0:{XRAY_PORT}")
# Xray already started above, keep alive
while True:
    time.sleep(60)
