import os, sys, json, base64, subprocess, threading, time, sqlite3, zipfile, tempfile, shutil, uuid, secrets
from http.server import HTTPServer, BaseHTTPRequestHandler

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', 'localhost')
PORT = int(os.environ.get('PORT', 8080))
VLESS_PORT = 443

def generate_keys():
    try:
        r = subprocess.run(['./xray', 'x25519'], capture_output=True, text=True, timeout=10)
        pk, pub = None, None
        for line in r.stdout.split('\n'):
            if 'Private key:' in line: pk = line.split(':')[1].strip()
            if 'Public key:' in line: pub = line.split(':')[1].strip()
        return pk or 'aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd', pub or ''
    except:
        return 'aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd', ''

def download_xray():
    if os.path.exists('./xray'): return True
    try:
        import requests as req
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        return True
    except:
        return False

def build_xray_config(uid, pk, sid):
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "vless-in", "listen": "0.0.0.0", "port": VLESS_PORT, "protocol": "vless",
            "settings": {"clients": [{"id": uid, "flow": "xtls-rprx-vision", "encryption": "none"}], "decryption": "none"},
            "streamSettings": {
                "network": "tcp", "security": "reality",
                "realitySettings": {
                    "dest": "www.google.com:443",
                    "serverNames": ["www.google.com", "google.com", "www.apple.com", "apple.com"],
                    "privateKey": pk, "shortIds": ["", sid]
                }
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}, {"protocol": "blackhole", "tag": "blocked"}]
    }

def make_url(uid, pk, pub, sid):
    params = f"security=reality&encryption=none&flow=xtls-rprx-vision&sni={DOMAIN}&fp=chrome&alpn=h2,http/1.1&pbk={pub}&sid={sid}"
    return f"vless://{uid}@{DOMAIN}:{VLESS_PORT}?{params}#VLESS-{DOMAIN[:10]}"

download_xray()
private_key, public_key = generate_keys()
uid = str(uuid.uuid4())
short_id = secrets.token_hex(8)
url = make_url(uid, private_key, public_key, short_id)

config = build_xray_config(uid, private_key, short_id)
with open('xray_config.json', 'w') as f: json.dump(config, f, indent=2)

xray_proc = None
try:
    xray_proc = subprocess.Popen(['./xray', 'run', '-config', 'xray_config.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
except: pass

HTML = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0"><title>VLESS Panel</title>
<style>:root{{--bg:#0d1117;--card:#161b22;--border:#30363d;--blue:#58a6ff;--green:#3fb950;--red:#f85149;--text:#c9d1d9;--dim:#8b949e}}
*{{margin:0;padding:0;box-sizing:border-box}}body{{font-family:system-ui,sans-serif;background:var(--bg);color:var(--text);min-height:100vh}}
.nav{{background:var(--card);border-bottom:1px solid var(--border);padding:15px;text-align:center}}
.nav h1{{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent;font-size:1.2em}}
.container{{max-width:600px;margin:0 auto;padding:15px}}
.card{{background:var(--card);border:1px solid var(--border);border-radius:12px;padding:20px;margin:15px 0}}
.card h2{{color:var(--blue);font-size:1em;margin-bottom:12px}}
.config-box{{background:rgba(0,0,0,.3);padding:12px;border-radius:8px;word-break:break-all;font-family:monospace;font-size:.75em;color:var(--green);margin:10px 0;line-height:1.8}}
.btn{{padding:12px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.85em;margin:5px 0;width:100%}}
.btn-g{{background:#238636;color:#fff}}.btn-b{{background:#1f6feb;color:#fff}}.btn-r{{background:#da3633;color:#fff}}
.info{{color:var(--dim);font-size:.75em;margin:5px 0}}.footer{{text-align:center;padding:20px;color:var(--dim);font-size:.7em}}</style></head><body>
<div class="nav"><h1>🚀 VLESS Panel</h1><p style="color:var(--dim);font-size:.8em">{DOMAIN}</p></div>
<div class="container">
<div class="card"><h2>📋 VLESS Config</h2>
<div class="config-box" id="config">{url}</div>
<p class="info">Port: {VLESS_PORT} | Security: Reality | Network: TCP</p>
<p class="info">UUID: {uid}</p>
<button class="btn btn-g" onclick="copy()">📋 Copy Config</button>
<button class="btn btn-b" onclick="gen()">🔄 New Config</button>
</div>
<div class="card"><h2>📱 Usage</h2>
<p style="color:var(--dim);line-height:2">1. Copy VLESS link<br>2. Open V2Ray/Xray<br>3. Import from clipboard<br>4. Connect ✅</p>
</div></div>
<div class="footer">VLESS Panel | {DOMAIN}</div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('config').textContent);alert('✅ Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url;alert('✅ New config!')}}
</script></body></html>'''

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(HTML.encode())
        elif self.path == '/new':
            global xray_proc
            uid = str(uuid.uuid4()); pk, pub = generate_keys(); sid = secrets.token_hex(8)
            url = make_url(uid, pk, pub, sid)
            config['inbounds'][0]['settings']['clients'].append({"id":uid,"flow":"xtls-rprx-vision","encryption":"none"})
            config['inbounds'][0]['streamSettings']['realitySettings']['shortIds'].append(sid)
            with open('xray_config.json','w') as f: json.dump(config,f,indent=2)
            if xray_proc:
                try: xray_proc.terminate()
                except: pass
            xray_proc = subprocess.Popen(['./xray','run','-config','xray_config.json'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':url,'uuid':uid}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else:
            self.send_response(404); self.end_headers()
    def log_message(self, format, *args): pass

print(f"""
╔══════════════════════════════════════╗
║   🚀 VLESS PANEL READY              ║
║   http://{DOMAIN}:{PORT}             ║
║   Config: {url[:60]}...  ║
╚══════════════════════════════════════╝
""")

HTTPServer(('0.0.0.0', PORT), Handler).serve_forever()