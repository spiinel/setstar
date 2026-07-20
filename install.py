import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket, threading, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

# ========== CONFIG ==========
DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
XRAY_PORT = int(os.environ.get('PORT', 8080))
PANEL_PORT = 12880

print(f"[*] Domain: {DOMAIN}")
print(f"[*] Xray Port: {XRAY_PORT}")
print(f"[*] Panel Port: {PANEL_PORT}")

# ========== STATE ==========
current_uid = str(uuid_lib.uuid4())
current_path = f"/ws/{current_uid}"

# ========== DOWNLOAD XRAY ==========
def download_xray():
    if os.path.exists('./xray'):
        return True
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        return True
    except Exception as e:
        print(f"[-] Xray download failed: {e}")
        return False

# ========== BUILD XRAY CONFIG ==========
def build_xray_config(uid, path):
    return {
        "log": {"loglevel": "error"},
        "inbounds": [{
            "listen": "0.0.0.0",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": uid, "encryption": "none"}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": path}
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }

# ========== MAKE VLESS URL ==========
def make_url(uid, path):
    params = (
        f"security=tls"
        f"&encryption=none"
        f"&type=ws"
        f"&path={path}"
        f"&host={DOMAIN}"
        f"&sni={DOMAIN}"
        f"&alpn=http/1.1"
        f"&fp=chrome"
    )
    return f"vless://{uid}@{DOMAIN}:443?{params}#Spinel"

# ========== STARTUP ==========
if not download_xray():
    sys.exit(1)

with open('xray.json', 'w') as f:
    json.dump(build_xray_config(current_uid, current_path), f, indent=2)

subprocess.Popen(
    ['./xray', 'run', '-config', 'xray.json'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
time.sleep(2)

current_url = make_url(current_uid, current_path)

# ========== PANEL SERVER ==========
HTML = '''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Spinel VLESS</title>
<style>:root{--bg:#0d1117;--card:#161b22;--border:#30363d;--blue:#58a6ff;--green:#3fb950;--text:#c9d1d9;--dim:#8b949e}
*{margin:0;padding:0;box-sizing:border-box}body{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}
.nav{background:var(--card);border-bottom:1px solid var(--border);padding:15px;text-align:center}
.nav h1{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}
.container{max-width:650px;margin:0 auto;padding:12px}
.card{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin:12px 0}
.card h2{color:var(--blue);font-size:.95em;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:8px}
.config-box{background:rgba(0,0,0,.4);padding:10px;border-radius:8px;word-break:break-all;font-family:monospace;font-size:.7em;color:var(--green);margin:8px 0;line-height:1.6;max-height:200px;overflow-y:auto}
.info{color:var(--dim);font-size:.7em;margin:3px 0}
.btn{padding:10px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.8em;margin:4px 0;width:100%}
.btn-g{background:#238636;color:#fff}.btn-b{background:#1f6feb;color:#fff}
</style></head><body>
<div class="nav"><h1>🌀 Spinel VLESS</h1><p style="color:var(--dim);font-size:.75em">{DOMAIN}</p></div>
<div class="container">
<div class="card"><h2>📡 VLESS Config</h2>
<div class="config-box" id="config">{URL}</div>
<p class="info">Address: {DOMAIN} | Port: 443 | TLS</p>
<p class="info">Network: WebSocket | Path: {PATH}</p>
<p class="info">UUID: {UID}</p>
<p class="info">Panel: {DOMAIN}:{PANEL_PORT}</p>
<button class="btn btn-g" onclick="copy()">📋 Copy Config</button>
<button class="btn btn-b" onclick="gen()">🔄 Generate New</button>
</div>
<div class="card"><h2>📱 How to Connect</h2>
<p style="color:var(--dim);font-size:.8em;line-height:2">
1. Copy config link<br>
2. Open <strong>v2rayNG</strong> or <strong>Nekobox</strong><br>
3. Import from clipboard<br>
4. Connect ✅
</p></div></div>
<script>
function copy(){navigator.clipboard.writeText(document.getElementById('config').textContent);alert('✅ Copied!')}
async function gen(){let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url;alert('✅ New config generated!')}
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '':
            html = HTML.format(DOMAIN=DOMAIN, URL=current_url, PATH=current_path, UID=current_uid, PANEL_PORT=PANEL_PORT)
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())

        elif self.path == '/new':
            global current_uid, current_path, current_url
            current_uid = str(uuid_lib.uuid4())
            current_path = f"/ws/{current_uid}"
            with open('xray.json', 'w') as f:
                json.dump(build_xray_config(current_uid, current_path), f, indent=2)
            subprocess.run(['pkill', '-f', './xray'], capture_output=True)
            time.sleep(1)
            subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            current_url = make_url(current_uid, current_path)
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.end_headers()
            self.wfile.write(json.dumps({'url': current_url, 'uuid': current_uid, 'path': current_path}).encode())

        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')

        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

# ========== START PANEL ==========
def run_panel():
    try:
        HTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
    except Exception as e:
        print(f"[-] Panel error: {e}")

threading.Thread(target=run_panel, daemon=True).start()

# ========== DONE ==========
print(f"""
╔══════════════════════════════════════════╗
║   🌀 Spinel VLESS Panel Ready           ║
║   VLESS: {DOMAIN}:443                   ║
║   Panel: {DOMAIN}:{PANEL_PORT}          ║
║   Path: {current_path}                  ║
║   UUID: {current_uid}                   ║
╚══════════════════════════════════════════╝

📋 VLESS Config:
{current_url}
""")

# ========== KEEP ALIVE ==========
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    print("\n[*] Shutting down...")
