import os, sys, json, base64, subprocess, time, uuid as uuid_lib, secrets, zipfile, socket, threading, hashlib, re
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    DOMAIN = os.environ.get('RAILWAY_STATIC_URL', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086

print(f"Domain: {DOMAIN} | Panel: {PANEL_PORT} | Xray: {XRAY_PORT}")

users = {}  # {uid: path}
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
        print("[+] Xray downloaded")
        return True
    except: return False

def build_config():
    """ساخت کانفیگ Xray با تمام user ها"""
    inbounds = []
    for uid, path in users.items():
        inbounds.append({
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {"clients": [{"id": uid}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": path}}
        })
    
    return {
        "log": {"loglevel": "error"},
        "inbounds": inbounds if inbounds else [{
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {"clients": [{"id": current_uid}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": current_path}}
        }],
        "outbounds": [{"protocol": "freedom", "tag": "direct"}]
    }

def make_url(uid, path):
    params = [
        "security=tls",
        "encryption=none",
        "type=ws",
        f"path={path}",
        f"host={DOMAIN}",
        f"sni={DOMAIN}",
        "alpn=http/1.1",
        "fp=chrome"
    ]
    return f"vless://{uid}@{DOMAIN}:443?{'&'.join(params)}#Spinel"

users[current_uid] = current_path
download_xray()
with open('xray.json', 'w') as f: json.dump(build_config(), f)

try:
    subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(2)
    print("[+] Xray started")
except: pass

current_url = make_url(current_uid, current_path)

def relay(src, dst):
    try:
        while True:
            data = src.recv(4096)
            if not data: break
            dst.send(data)
    except: pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle_ws(client_sock, path):
    backend = None
    try:
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.settimeout(5)
        backend.connect(('127.0.0.1', XRAY_PORT))
        
        req = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        backend.send(req.encode())
        
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk: break
            resp += chunk
        
        if b"101" not in resp:
            try: client_sock.close()
            except: pass
            try: backend.close()
            except: pass
            return
        
        t1 = threading.Thread(target=relay, args=(client_sock, backend), daemon=True)
        t2 = threading.Thread(target=relay, args=(backend, client_sock), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
        
    except Exception as e:
        print(f"WS error: {e}")
    finally:
        try: client_sock.close()
        except: pass
        if backend:
            try: backend.close()
            except: pass

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            try:
                key = self.headers.get('Sec-WebSocket-Key', '')
                accept = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
                
                self.send_response(101)
                self.send_header('Upgrade', 'websocket')
                self.send_header('Connection', 'Upgrade')
                self.send_header('Sec-WebSocket-Accept', accept)
                self.end_headers()
                
                client = self.request
                self.request = None
                
                threading.Thread(target=handle_ws, args=(client, self.path), daemon=True).start()
                
            except Exception as e:
                print(f"Upgrade error: {e}")
                
        elif self.path == '/':
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
<p class="info">Security: TLS | Network: WebSocket</p>
<p class="info">Path: {current_path}</p>
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
            users[new_uid] = new_path
            with open('xray.json', 'w') as f: json.dump(build_config(), f)
            # Restart Xray
            try:
                subprocess.run(['pkill', 'xray'], capture_output=True)
                time.sleep(1)
                subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except: pass
            new_url = make_url(new_uid, new_path)
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':new_url}).encode())
            
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else:
            self.send_response(404); self.end_headers()
    
    def log_message(self, f, *a): pass

class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request, client_address):
        t = threading.Thread(target=self.process_request_thread, args=(request, client_address), daemon=True)
        t.start()
    def process_request_thread(self, request, client_address):
        try: self.finish_request(request, client_address)
        except: self.handle_error(request, client_address)
        finally: self.shutdown_request(request)

print(f"✅ Ready: {current_url}")
ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
