import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket, threading, hashlib
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086

print(f"Domain: {DOMAIN} | Panel: {PANEL_PORT} | Xray: {XRAY_PORT}")

uid = str(uuid_lib.uuid4())
path = f"/ws/{uid}"

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

def build_xray_config():
    return {
        "log": {"loglevel": "warning"},
        "dns": {
            "servers": ["8.8.8.8", "1.1.1.1", "localhost"]
        },
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {"clients": [{"id": uid, "encryption": "none"}], "decryption": "none"},
            "streamSettings": {"network": "ws", "security": "none", "wsSettings": {"path": path}}
        }],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct", "settings": {"domainStrategy": "UseIP"}},
            {"protocol": "blackhole", "tag": "blocked"}
        ],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "ip": ["geoip:private"], "outboundTag": "blocked"}]
        }
    }

def make_url():
    params = f"security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome"
    return f"vless://{uid}@{DOMAIN}:443?{params}#Spinel"

download_xray()
with open('xray.json', 'w') as f: json.dump(build_xray_config(), f)
subprocess.Popen(['./xray', 'run', '-config', 'xray.json'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

def relay(a, b):
    try:
        while True:
            d = a.recv(4096)
            if not d: break
            b.send(d)
    except: pass
    finally:
        try: a.close()
        except: pass
        try: b.close()
        except: pass

def handle_ws(client):
    backend = None
    try:
        backend = socket.socket()
        backend.connect(('127.0.0.1', XRAY_PORT))
        backend.send(f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += backend.recv(4096)
        if b"101" not in resp: return
        t1 = threading.Thread(target=relay, args=(client, backend), daemon=True)
        t2 = threading.Thread(target=relay, args=(backend, client), daemon=True)
        t1.start(); t2.start()
        t1.join(); t2.join()
    except: pass
    finally:
        try: client.close()
        except: pass
        if backend:
            try: backend.close()
            except: pass

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            key = self.headers.get('Sec-WebSocket-Key', '')
            acc = base64.b64encode(hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', acc)
            self.end_headers()
            c = self.request
            self.request = None
            threading.Thread(target=handle_ws, args=(c,), daemon=True).start()
        elif self.path == '/':
            url = make_url()
            h = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:20px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:20px;max-width:600px;margin:20px auto}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:8px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:1em}}</style></head><body>
<h1>🌀 Spinel VLESS</h1><p>{DOMAIN}</p>
<div class="box"><h3>📡 Config</h3><code id="c">{url}</code>
<p>Port: 443 | TLS | WebSocket</p>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('c').textContent);alert('Copied!')">📋 Copy</button></div></body></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(h.encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        else: self.send_response(404); self.end_headers()
    def log_message(self,f,*a): pass

class T(HTTPServer):
    def process_request(self, r, a):
        threading.Thread(target=self.process_request_thread, args=(r,a), daemon=True).start()
    def process_request_thread(self, r, a):
        try: self.finish_request(r, a)
        except: self.handle_error(r, a)
        finally: self.shutdown_request(r)

url = make_url()
print(f"\nPanel: http://{DOMAIN}:{PANEL_PORT}")
print(f"VLESS: {url}\n")
T(('0.0.0.0', PANEL_PORT), H).serve_forever()
