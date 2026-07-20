import os, sys, json, base64, subprocess, time, uuid, hashlib, threading, socket, traceback, logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s', stream=sys.stdout)
log = logging.getLogger('Spinel')

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086
XRAY_VERSION = "v1.8.21"
XRAY_URL = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/Xray-linux-64.zip"

current_uid = str(uuid.uuid4())
current_path = f"/ws/{current_uid}"

xray_process = None
process_lock = threading.Lock()

log.info(f"Domain: {DOMAIN} | Panel: {PANEL_PORT} | Xray: {XRAY_PORT}")

def download_xray():
    if os.path.exists('./xray') and os.path.getsize('./xray') > 10000000:
        return True
    log.info(f"Downloading Xray {XRAY_VERSION}...")
    try:
        r = req.get(XRAY_URL, timeout=120, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200:
            log.error(f"HTTP {r.status_code}")
            return False
        with open('xray.zip', 'wb') as f: f.write(r.content)
        import zipfile
        if not zipfile.is_zipfile('xray.zip'):
            log.error("Not a valid ZIP")
            os.remove('xray.zip')
            return False
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        log.info("Downloaded")
        return True
    except Exception as e:
        log.error(f"Download: {e}")
        return False

def build_config():
    return {
        "log": {"loglevel": "debug"},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": current_uid}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": current_path}
            }
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct"
        }]
    }

def start_xray():
    global xray_process
    with process_lock:
        if xray_process and xray_process.poll() is None:
            return True
        
        config = build_config()
        with open('xray_config.json', 'w') as f:
            json.dump(config, f, indent=2)
        
        log.info("Starting Xray (output to Railway logs)...")
        xray_process = subprocess.Popen(
            ['./xray', 'run', '-config', 'xray_config.json'],
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        time.sleep(3)
        
        if xray_process.poll() is not None:
            log.error(f"Xray exited with code {xray_process.returncode}")
            return False
        
        log.info(f"Xray running (PID: {xray_process.pid})")
        return True

def health_check():
    try:
        s = socket.socket(); s.settimeout(5)
        s.connect(('127.0.0.1', XRAY_PORT))
        s.send(f"GET {current_path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        resp = s.recv(1024); s.close()
        return b"101" in resp
    except:
        return False

def watchdog():
    while True:
        time.sleep(30)
        with process_lock:
            if xray_process is None or xray_process.poll() is not None:
                log.warning("Watchdog restarting...")
                start_xray()

def pipe_data(src, dst, name):
    try:
        while True:
            data = src.recv(32768)
            if not data: break
            dst.sendall(data)
    except: pass
    finally:
        try: src.close()
        except: pass
        try: dst.close()
        except: pass

def handle_ws_client(client_sock, client_addr):
    backend = None
    try:
        backend = socket.socket(); backend.settimeout(10)
        backend.connect(('127.0.0.1', XRAY_PORT))
        backend.sendall(f"GET {current_path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            c = backend.recv(4096)
            if not c: break
            resp += c
        if b"101" not in resp: return
        t1 = threading.Thread(target=pipe_data, args=(client_sock, backend, "C2X"), daemon=True)
        t2 = threading.Thread(target=pipe_data, args=(backend, client_sock, "X2C"), daemon=True)
        t1.start(); t2.start()
        t1.join(timeout=300); t2.join(timeout=300)
    except Exception as e:
        log.error(f"WS: {e}")
    finally:
        try: client_sock.close()
        except: pass
        if backend:
            try: backend.close()
            except: pass

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            key = self.headers.get('Sec-WebSocket-Key', '')
            if not key: self.send_response(400); self.end_headers(); return
            accept = base64.b64encode(hashlib.sha1((key+'258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()).decode()
            self.send_response(101); self.send_header('Upgrade','websocket'); self.send_header('Connection','Upgrade'); self.send_header('Sec-WebSocket-Accept',accept); self.end_headers()
            c = self.request; self.request = None
            threading.Thread(target=handle_ws_client, args=(c, self.client_address), daemon=True).start()
        elif self.path == '/':
            url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
            sub = base64.b64encode((url+"\n").encode()).decode()
            h = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:600px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:.9em;margin:4px}}</style></head><body>
<h1 style="background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent">🌀 Spinel VLESS</h1>
<p style="color:#8b949e">{DOMAIN}</p>
<div class="box"><h3 style="color:#58a6ff">📡 Config</h3><code id="c">{url}</code>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('c').textContent);alert('Copied!')">📋 Copy</button></div>
<div class="box"><h3 style="color:#58a6ff">🔗 Sub</h3><code id="s">{sub}</code>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('s').textContent);alert('Copied!')">📋 Copy Sub</button></div>
</body></html>'''
            self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
            self.wfile.write(h.encode())
        elif self.path == '/health':
            ok = health_check(); self.send_response(200 if ok else 503); self.end_headers()
            self.wfile.write(b'OK' if ok else b'FAIL')
        else: self.send_response(404); self.end_headers()
    def log_message(self,f,*a): pass

class T(HTTPServer):
    def process_request(self, r, a):
        threading.Thread(target=self._p, args=(r,a), daemon=True).start()
    def _p(self, r, a):
        try: self.finish_request(r, a)
        except: self.handle_error(r, a)
        finally: self.shutdown_request(r)

if __name__ == '__main__':
    if not download_xray(): sys.exit(1)
    if not start_xray(): sys.exit(1)
    threading.Thread(target=watchdog, daemon=True).start()
    url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
    log.info(f"Ready: {url}")
    T(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
