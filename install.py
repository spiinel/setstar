import os, sys, json, base64, subprocess, threading, time, sqlite3, zipfile, tempfile, shutil, uuid, secrets, random, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    DOMAIN = os.environ.get('RAILWAY_STATIC_URL', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))
VLESS_PORT = int(os.environ.get('PORT', '443'))
WS_PORT = int(os.environ.get('PORT', '80'))

PORTS = [VLESS_PORT, WS_PORT]
for p in PORTS:
    if p < 1000 or p == PANEL_PORT:
        VLESS_PORT = random.randint(10000, 60000)
        WS_PORT = random.randint(10000, 60000)
        while WS_PORT == VLESS_PORT:
            WS_PORT = random.randint(10000, 60000)
        break

REALITY_DEST = "www.google.com:443"
REALITY_SNI = "www.google.com"
REALITY_SERVER_NAMES = ["www.google.com", "google.com", "www.apple.com", "apple.com", "www.microsoft.com", "microsoft.com", "www.cloudflare.com", "cloudflare.com"]
WS_PATH = "/" + secrets.token_hex(4)

print(f"""
╔══════════════════════════════════════╗
║   🚀 VLESS PANEL v2.0               ║
║   Domain: {DOMAIN}                   ║
║   Panel: {PANEL_PORT}                ║
║   VLESS: {VLESS_PORT}                ║
║   WS: {WS_PORT}                      ║
║   Path: {WS_PATH}                    ║
╚══════════════════════════════════════╝
""")

def generate_keys():
    try:
        r = subprocess.run(['./xray', 'x25519'], capture_output=True, text=True, timeout=10)
        pk, pub = None, None
        for line in r.stdout.split('\n'):
            if 'Private key:' in line: pk = line.split(':')[1].strip()
            if 'Public key:' in line: pub = line.split(':')[1].strip()
        if pk and pub: return pk, pub
    except: pass
    return 'aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd', 'Ag0kP6mSdY2xU4kP6mSdY2xU4kP6mSdY2xU4kP6mSd'

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

class ConfigManager:
    def __init__(self):
        self.users = []
        self.private_key, self.public_key = generate_keys()
        self.short_ids = ["", secrets.token_hex(8)]
    
    def add_user(self, uid=None, flow="xtls-rprx-vision"):
        if not uid:
            uid = str(uuid.uuid4())
        sid = secrets.token_hex(8)
        self.short_ids.append(sid)
        self.users.append({"id": uid, "flow": flow, "encryption": "none"})
        return uid, sid
    
    def build_xray_config(self):
        return {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "tag": "vless-reality",
                    "listen": "0.0.0.0",
                    "port": VLESS_PORT,
                    "protocol": "vless",
                    "settings": {"clients": self.users, "decryption": "none"},
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "show": False,
                            "dest": REALITY_DEST,
                            "xver": 0,
                            "serverNames": REALITY_SERVER_NAMES,
                            "privateKey": self.private_key,
                            "shortIds": self.short_ids,
                            "minClientVer": "",
                            "maxClientVer": "",
                            "maxTimeDiff": 0
                        }
                    },
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
                },
                {
                    "tag": "vless-ws",
                    "listen": "0.0.0.0",
                    "port": WS_PORT,
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": u["id"], "encryption": "none"} for u in self.users],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "none",
                        "wsSettings": {
                            "path": WS_PATH,
                            "headers": {"Host": DOMAIN}
                        }
                    },
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
                }
            ],
            "outbounds": [
                {"protocol": "freedom", "tag": "direct", "settings": {}},
                {"protocol": "blackhole", "tag": "blocked", "settings": {}}
            ]
        }
    
    def save_config(self):
        config = self.build_xray_config()
        with open('xray_config.json', 'w') as f:
            json.dump(config, f, indent=2)
        return config
    
    def make_reality_url(self, uid, sid):
        params = [
            "security=reality",
            "encryption=none",
            "flow=xtls-rprx-vision",
            f"sni={REALITY_SNI}",
            "fp=chrome",
            "alpn=h2,http/1.1",
            f"pbk={self.public_key}",
            f"sid={sid}"
        ]
        return f"vless://{uid}@{DOMAIN}:{VLESS_PORT}?{'&'.join(params)}#VLESS-R-{DOMAIN[:8]}"
    
    def make_ws_url(self, uid):
        params = [
            "security=none",
            "encryption=none",
            "type=ws",
            f"path={WS_PATH}",
            f"host={DOMAIN}"
        ]
        return f"vless://{uid}@{DOMAIN}:{WS_PORT}?{'&'.join(params)}#VLESS-WS-{DOMAIN[:8]}"

download_xray()
cfg = ConfigManager()
uid, sid = cfg.add_user()
cfg.save_config()

reality_url = cfg.make_reality_url(uid, sid)
ws_url = cfg.make_ws_url(uid)

xray_proc = None
def start_xray():
    global xray_proc
    if xray_proc:
        try: xray_proc.terminate()
        except: pass
        time.sleep(1)
    try:
        xray_proc = subprocess.Popen(['./xray', 'run', '-config', 'xray_config.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return True
    except: return False

start_xray()

HTML = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>VLESS Panel</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--blue:#58a6ff;--green:#3fb950;--red:#f85149;--text:#c9d1d9;--dim:#8b949e}}
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.nav{{background:var(--card);border-bottom:1px solid var(--border);padding:12px 15px;text-align:center}}
.nav h1{{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.1em}}
.container{{max-width:650px;margin:0 auto;padding:12px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin:12px 0}}
.card h2{{color:var(--blue);font-size:.95em;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:8px}}
.config-box{{background:rgba(0,0,0,.4);padding:10px;border-radius:8px;word-break:break-all;font-family:monospace;font-size:.7em;color:var(--green);margin:8px 0;line-height:1.6;max-height:120px;overflow-y:auto}}
.info{{color:var(--dim);font-size:.7em;margin:3px 0}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.65em;font-weight:bold;margin:2px}}
.badge-r{{background:rgba(188,140,255,.2);color:#bc8cff}}.badge-w{{background:rgba(63,185,80,.2);color:#3fb950}}
.btn{{padding:10px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.8em;margin:4px 0;width:100%}}
.btn-g{{background:#238636;color:#fff}}.btn-b{{background:#1f6feb;color:#fff}}.btn-o{{background:transparent;border:1px solid var(--border);color:var(--text)}}
.row{{display:flex;gap:8px}}
.row .btn{{flex:1}}
.footer{{text-align:center;padding:15px;color:var(--dim);font-size:.65em}}
</style></head><body>
<div class="nav"><h1>🚀 VLESS Panel</h1><p style="color:var(--dim);font-size:.75em">{DOMAIN}</p></div>
<div class="container">

<div class="card">
<h2>📡 Reality Config <span class="badge badge-r">Recommended</span></h2>
<div class="config-box" id="reality-config">{reality_url}</div>
<p class="info">Address: {DOMAIN} | Port: {VLESS_PORT}</p>
<p class="info">Security: Reality | SNI: {REALITY_SNI}</p>
<p class="info">Flow: xtls-rprx-vision | Fingerprint: chrome</p>
<p class="info">UUID: {uid}</p>
<div class="row">
<button class="btn btn-g" onclick="copy('reality-config')">📋 Copy</button>
<button class="btn btn-b" onclick="gen('reality')">🔄 New</button>
</div>
</div>

<div class="card">
<h2>🔌 WebSocket Config <span class="badge badge-w">Alternative</span></h2>
<div class="config-box" id="ws-config">{ws_url}</div>
<p class="info">Address: {DOMAIN} | Port: {WS_PORT}</p>
<p class="info">Network: WebSocket | Path: {WS_PATH}</p>
<p class="info">UUID: {uid}</p>
<div class="row">
<button class="btn btn-g" onclick="copy('ws-config')">📋 Copy</button>
<button class="btn btn-b" onclick="gen('ws')">🔄 New</button>
</div>
</div>

<div class="card">
<h2>📋 Connection Info</h2>
<p style="color:var(--dim);font-size:.8em;line-height:2">
<strong>Domain:</strong> {DOMAIN}<br>
<strong>Reality Port:</strong> {VLESS_PORT}<br>
<strong>WebSocket Port:</strong> {WS_PORT}<br>
<strong>WS Path:</strong> {WS_PATH}<br>
<strong>UUID:</strong> {uid}<br>
<strong>SNI:</strong> {REALITY_SNI}<br>
<strong>Security:</strong> Reality / None (WS)<br>
<strong>Fingerprint:</strong> chrome
</p>
</div>

<div class="card">
<h2>📱 How to Connect</h2>
<p style="color:var(--dim);font-size:.8em;line-height:2">
1. Download <strong>v2rayNG</strong> or <strong>Xray</strong> client<br>
2. Copy config from above<br>
3. Paste in app → Import from clipboard<br>
4. Connect ✅
</p>
</div>

</div>
<div class="footer">VLESS Panel v2.0 | {DOMAIN} | Ports: {VLESS_PORT}/{WS_PORT}</div>
<script>
function copy(id){{var t=document.getElementById(id).textContent;navigator.clipboard.writeText(t);alert('✅ Copied!')}}
async function gen(type){{let r=await fetch('/new?type='+type);let d=await r.json();if(type==='ws'){{document.getElementById('ws-config').textContent=d.url}}else{{document.getElementById('reality-config').textContent=d.url}};alert('✅ New config generated!')}}
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '':
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path.startswith('/new'):
            global cfg, xray_proc
            qs = self.path.split('?')[-1] if '?' in self.path else ''
            ctype = 'reality'
            if 'type=ws' in qs: ctype = 'ws'
            
            uid, sid = cfg.add_user()
            cfg.save_config()
            start_xray()
            
            url = cfg.make_ws_url(uid) if ctype == 'ws' else cfg.make_reality_url(uid, sid)
            
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':url,'uuid':uid,'type':ctype}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        elif self.path == '/sub':
            urls = []
            for u in cfg.users:
                urls.append(cfg.make_reality_url(u['id'], cfg.short_ids[-1]))
                urls.append(cfg.make_ws_url(u['id']))
            self.send_response(200); self.send_header('Content-Type','text/plain'); self.end_headers()
            self.wfile.write(base64.b64encode('\n'.join(urls).encode()))
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass

print(f"✅ Panel: http://{DOMAIN}:{PANEL_PORT}")
print(f"✅ Reality: {DOMAIN}:{VLESS_PORT}")
print(f"✅ WebSocket: {DOMAIN}:{WS_PORT}{WS_PATH}")
HTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
