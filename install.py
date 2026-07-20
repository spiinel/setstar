import os, sys, json, base64, subprocess, time, uuid, secrets, zipfile, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    DOMAIN = os.environ.get('RAILWAY_STATIC_URL', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))

def get_available_port():
    for port in [443, 8443, 2053, 2083, 2087, 2096, 8443]:
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.bind(('0.0.0.0', port))
            s.close()
            return port
        except:
            continue
    return 443

VLESS_PORT = get_available_port()

WS_PATH = f"/ws/{str(uuid.uuid4())}"
FINGERPRINT = "chrome"
ALPN = "h2,http/1.1"

print(f"""
╔══════════════════════════════════════╗
║   🚀 X4G VLESS PANEL               ║
║   Domain: {DOMAIN}                   ║
║   Panel: {PANEL_PORT}                ║
║   VLESS: {VLESS_PORT}                ║
║   Path: {WS_PATH}                    ║
╚══════════════════════════════════════╝
""")

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

def build_xray_config(uid):
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "vless-ws-tls",
                "listen": "0.0.0.0",
                "port": VLESS_PORT,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": uid, "encryption": "none"}],
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "tls",
                    "tlsSettings": {
                        "allowInsecure": False,
                        "alpn": [ALPN],
                        "fingerprint": FINGERPRINT,
                        "serverName": DOMAIN
                    },
                    "wsSettings": {
                        "host": DOMAIN,
                        "path": WS_PATH
                    }
                },
                "sniffing": {
                    "enabled": True,
                    "destOverride": ["http", "tls", "quic"]
                }
            }
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct", "settings": {}},
            {"protocol": "blackhole", "tag": "blocked", "settings": {}}
        ]
    }

def make_url(uid):
    params = [
        "security=tls",
        "encryption=none",
        "type=ws",
        f"path={WS_PATH}",
        f"host={DOMAIN}",
        f"sni={DOMAIN}",
        f"fp={FINGERPRINT}",
        f"alpn={ALPN}"
    ]
    return f"vless://{uid}@{DOMAIN}:{VLESS_PORT}?{'&'.join(params)}#Spinel-{DOMAIN[:8]}"

download_xray()

uid = str(uuid.uuid4())
config = build_xray_config(uid)
with open('xray_config.json', 'w') as f:
    json.dump(config, f, indent=2)

url = make_url(uid)

xray_proc = None
try:
    xray_proc = subprocess.Popen(
        ['./xray', 'run', '-config', 'xray_config.json'],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL
    )
    print(f"✅ Xray started on port {VLESS_PORT}")
except Exception as e:
    print(f"❌ Xray error: {e}")

HTML = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>Spinel VLESS</title>
<style>
:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--blue:#58a6ff;--green:#3fb950;--red:#f85149;--text:#c9d1d9;--dim:#8b949e}}
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.nav{{background:var(--card);border-bottom:1px solid var(--border);padding:15px;text-align:center}}
.nav h1{{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.container{{max-width:650px;margin:0 auto;padding:12px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:18px;margin:12px 0}}
.card h2{{color:var(--blue);font-size:.95em;margin-bottom:10px;border-bottom:1px solid var(--border);padding-bottom:8px}}
.config-box{{background:rgba(0,0,0,.4);padding:10px;border-radius:8px;word-break:break-all;font-family:monospace;font-size:.7em;color:var(--green);margin:8px 0;line-height:1.6;max-height:150px;overflow-y:auto}}
.info{{color:var(--dim);font-size:.7em;margin:3px 0}}
.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.65em;font-weight:bold;margin:2px}}
.badge-g{{background:rgba(63,185,80,.2);color:#3fb950}}
.btn{{padding:10px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.8em;margin:4px 0;width:100%}}
.btn-g{{background:#238636;color:#fff}}.btn-b{{background:#1f6feb;color:#fff}}
.row{{display:flex;gap:8px}}.row .btn{{flex:1}}
.footer{{text-align:center;padding:15px;color:var(--dim);font-size:.65em}}
</style></head><body>
<div class="nav"><h1>🌀 Spinel VLESS</h1><p style="color:var(--dim);font-size:.75em">{DOMAIN}</p></div>
<div class="container">

<div class="card">
<h2>📡 VLESS Config <span class="badge badge-g">WebSocket + TLS</span></h2>
<div class="config-box" id="config">{url}</div>
<p class="info">Address: {DOMAIN} | Port: {VLESS_PORT}</p>
<p class="info">Network: WebSocket | Security: TLS</p>
<p class="info">Path: {WS_PATH} | Host: {DOMAIN}</p>
<p class="info">SNI: {DOMAIN} | Fingerprint: {FINGERPRINT}</p>
<p class="info">UUID: {uid}</p>
<div class="row">
<button class="btn btn-g" onclick="copy()">📋 Copy Config</button>
<button class="btn btn-b" onclick="gen()">🔄 New Config</button>
</div>
</div>

<div class="card">
<h2>📱 How to Connect</h2>
<p style="color:var(--dim);font-size:.8em;line-height:2">
1. Download <strong>v2rayNG</strong> or <strong>Nekobox</strong><br>
2. Copy config from above<br>
3. Paste in app → Import<br>
4. Connect ✅
</p>
</div>

</div>
<div class="footer">Spinel Panel | {DOMAIN} | Port: {VLESS_PORT}</div>
<script>
function copy(){{var t=document.getElementById('config').textContent;navigator.clipboard.writeText(t);alert('✅ Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url;location.reload()}}
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '':
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/new':
            global xray_proc
            uid = str(uuid.uuid4())
            config = build_xray_config(uid)
            with open('xray_config.json','w') as f: json.dump(config,f,indent=2)
            url = make_url(uid)
            if xray_proc:
                try: xray_proc.terminate()
                except: pass
                time.sleep(1)
            xray_proc = subprocess.Popen(['./xray','run','-config','xray_config.json'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':url,'uuid':uid}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass

print(f"✅ Spinel Panel: http://{DOMAIN}:{PANEL_PORT}")
print(f"✅ VLESS Config: {url}")
HTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
