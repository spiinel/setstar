import os, sys, json, base64, subprocess, time, uuid, secrets, zipfile, socket, threading, select, struct, random, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086
WS_PATH = f"/ws/{uuid.uuid4().hex[:8]}"

print(f"Domain: {DOMAIN} | Panel: {PANEL_PORT} | Xray: {XRAY_PORT} | Path: {WS_PATH}")

def download_xray():
    if os.path.exists('./xray'): return True
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("[+] Xray ready")
        return True
    except:
        print("[-] Xray download failed")
        return False

def build_config(uid):
    return {
        "log": {"loglevel": "error"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {"clients": [{"id": uid}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": WS_PATH}}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }

def make_url(uid):
    params = f"security=none&encryption=none&type=ws&path={WS_PATH}&host={DOMAIN}"
    return f"vless://{uid}@{DOMAIN}:{PANEL_PORT}?{params}#Spinel"

download_xray()
uid = str(uuid.uuid4())
with open('xray.json', 'w') as f: json.dump(build_config(uid), f)

try:
    subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], 
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print("[+] Xray started")
except Exception as e:
    print(f"[-] Xray error: {e}")

url = make_url(uid)

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            key = self.headers.get('Sec-WebSocket-Key', '')
            if key:
                accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            
            client = self.request
            self.request = None
            
            try:
                backend = socket.socket()
                backend.connect(('127.0.0.1', XRAY_PORT))
                backend.send(f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
                backend.recv(4096)
                
                def relay(a, b):
                    try:
                        while True:
                            data = a.recv(4096)
                            if not data: break
                            b.send(data)
                    except: pass
                    finally:
                        try: a.close()
                        except: pass
                        try: b.close()
                        except: pass
                
                threading.Thread(target=relay, args=(client, backend), daemon=True).start()
                threading.Thread(target=relay, args=(backend, client), daemon=True).start()
            except: pass
            
        elif self.path == '/':
            html = f'''<html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;max-width:600px;margin:20px auto}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:8px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:1em;margin:5px}}</style></head><body>
<h1>🌀 Spinel</h1><p>{DOMAIN}</p>
<div class="box"><h3>Config</h3><code id="c">{url}</code>
<p>Port: {PANEL_PORT} | Path: {WS_PATH}</p>
<button class="btn" onclick="copy()">Copy</button>
<button class="btn" onclick="gen()">New</button></div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('c').textContent);alert('Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('c').textContent=d.url}}
</script></body></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(html.encode())
            
        elif self.path == '/new':
            global uid, url
            uid = str(uuid.uuid4())
            with open('xray.json', 'w') as f: json.dump(build_config(uid), f)
            url = make_url(uid)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':url}).encode())
            
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else:
            self.send_response(404); self.end_headers()
    
    def log_message(self, f, *a): pass

print(f"✅ Ready: {url}")
HTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
