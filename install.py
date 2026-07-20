import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket, threading, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
XRAY_PORT = int(os.environ.get('PORT', 8080))
PANEL_PORT = 12880

current_uid = str(uuid_lib.uuid4())
current_path = f"/ws/{current_uid}"

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
        "inbounds": [{
            "listen": "0.0.0.0", "port": XRAY_PORT, "protocol": "vless",
            "settings": {"clients": [{"id": uid, "encryption": "none"}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": path}}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }

def make_url(uid, path):
    p = f"security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome"
    return f"vless://{uid}@{DOMAIN}:443?{p}#Spinel"

download_xray()
with open('xray.json', 'w') as f: json.dump(build_config(current_uid, current_path), f)
subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)
current_url = make_url(current_uid, current_path)

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/':
            h = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;max-width:600px;margin:20px auto}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:8px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:1em;margin:5px}}</style></head><body>
<h1>🌀 Spinel VLESS</h1><p>{DOMAIN}</p>
<div class="box"><h3>📡 Config</h3><code id="c">{current_url}</code>
<p>Port: 443 | Path: {current_path}</p>
<button class="btn" onclick="copy()">📋 Copy</button>
<button class="btn" onclick="gen()">🔄 New</button></div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('c').textContent);alert('Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('c').textContent=d.url}}
</script></body></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(h.encode())
        elif self.path == '/new':
            global current_uid, current_path, current_url
            current_uid = str(uuid_lib.uuid4()); current_path = f"/ws/{current_uid}"
            with open('xray.json','w') as f: json.dump(build_config(current_uid, current_path),f)
            subprocess.run(['pkill','-f','./xray'],capture_output=True); time.sleep(1)
            subprocess.Popen(['./xray','run','-config','xray.json'],stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
            current_url = make_url(current_uid, current_path)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':current_url}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else: self.send_response(404); self.end_headers()
    def log_message(self,f,*a): pass

def run():
    try: HTTPServer(('0.0.0.0', PANEL_PORT), H).serve_forever()
    except: pass

threading.Thread(target=run, daemon=True).start()
print(f"VLESS: {DOMAIN}:443 | Panel: {DOMAIN}:{PANEL_PORT}")

try:
    while True: time.sleep(3600)
except KeyboardInterrupt: pass
