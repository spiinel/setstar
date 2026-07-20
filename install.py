import os, sys, json, base64, subprocess, time, uuid, secrets, zipfile, socket, threading, select, struct, random
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = random.randint(10000, 60000)
WS_PATH = f"/ws/{uuid.uuid4().hex[:16]}"

print(f"[*] Domain: {DOMAIN}")
print(f"[*] Panel Port: {PANEL_PORT}")
print(f"[*] Xray Port: {XRAY_PORT}")
print(f"[*] WS Path: {WS_PATH}")

def download_xray():
    if os.path.exists('./xray'): return True
    try:
        print("[*] Downloading Xray...")
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("[+] Xray downloaded")
        return True
    except Exception as e:
        print(f"[-] Xray download failed: {e}")
        return False

def build_xray_config(uid):
    return {
        "log": {"loglevel": "debug", "access": "/dev/stdout", "error": "/dev/stdout"},
        "inbounds": [{
            "tag": "vless-ws",
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": uid, "encryption": "none"}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": WS_PATH}
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct", "settings": {}},
            {"protocol": "blackhole", "tag": "blocked", "settings": {}}
        ]
    }

def make_url(uid):
    params = [
        "security=none",
        "encryption=none", 
        "type=ws",
        f"path={WS_PATH}",
        f"host={DOMAIN}"
    ]
    return f"vless://{uid}@{DOMAIN}:{PANEL_PORT}?{'&'.join(params)}#Spinel-{DOMAIN[:8]}"

if not download_xray():
    sys.exit(1)

uid = str(uuid.uuid4())
config = build_xray_config(uid)
with open('xray_config.json', 'w') as f: json.dump(config, f, indent=2)
print(f"[+] Xray config written")

xray_proc = None
def start_xray():
    global xray_proc
    if xray_proc:
        try: xray_proc.terminate()
        except: pass
        time.sleep(1)
    try:
        xray_proc = subprocess.Popen(
            ['./xray', 'run', '-config', 'xray_config.json'],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT
        )
        time.sleep(2)
        if xray_proc.poll() is not None:
            out = xray_proc.stdout.read().decode()
            print(f"[-] Xray failed: {out}")
            return False
        print(f"[+] Xray started on {XRAY_PORT}")
        return True
    except Exception as e:
        print(f"[-] Xray error: {e}")
        return False

if not start_xray():
    sys.exit(1)

url = make_url(uid)

def ws_read_frame(sock):
    try:
        header = sock.recv(2)
        if len(header) < 2: return None
        b1, b2 = header
        opcode = b1 & 0x0F
        masked = (b2 & 0x80) != 0
        length = b2 & 0x7F
        if length == 126:
            data = sock.recv(2)
            length = struct.unpack('!H', data)[0]
        elif length == 127:
            data = sock.recv(8)
            length = struct.unpack('!Q', data)[0]
        mask_key = b''
        if masked:
            mask_key = sock.recv(4)
        payload = bytearray()
        while len(payload) < length:
            chunk = sock.recv(min(4096, length - len(payload)))
            if not chunk: break
            payload.extend(chunk)
        if masked:
            payload = bytearray(b ^ mask_key[i % 4] for i, b in enumerate(payload))
        return opcode, bytes(payload)
    except: return None

def ws_send_frame(sock, payload, opcode=0x2):
    header = bytearray()
    header.append(0x80 | opcode)
    length = len(payload)
    if length <= 125:
        header.append(length)
    elif length <= 65535:
        header.append(126)
        header.extend(struct.pack('!H', length))
    else:
        header.append(127)
        header.extend(struct.pack('!Q', length))
    try:
        sock.send(bytes(header) + payload)
    except: pass

def ws_relay(client, backend):
    try:
        while True:
            r, _, _ = select.select([client, backend], [], [], 300)
            for s in r:
                frame = ws_read_frame(s)
                if frame is None: return
                opcode, data = frame
                if opcode == 0x8: return
                if s == client:
                    ws_send_frame(backend, data, opcode)
                else:
                    ws_send_frame(client, data, opcode)
    except Exception as e:
        print(f"[!] Relay error: {e}")

def handle_ws_upgrade(client_sock):
    backend = None
    try:
        print(f"[*] WS upgrade from {client_sock.getpeername()}")
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.settimeout(5)
        backend.connect(('127.0.0.1', XRAY_PORT))
        
        key = base64.b64encode(os.urandom(16)).decode()
        req = f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{XRAY_PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        backend.send(req.encode())
        
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk: break
            resp += chunk
        
        print(f"[*] Xray response: {resp[:200]}")
        
        if b"101" not in resp:
            print(f"[-] Xray didn't upgrade: {resp}")
            return
        
        print(f"[+] WebSocket established, relaying...")
        ws_relay(client_sock, backend)
    except Exception as e:
        print(f"[-] WS error: {e}")
    finally:
        try: client_sock.close()
        except: pass
        if backend:
            try: backend.close()
            except: pass

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        print(f"[*] Request: {self.path}")
        
        if self.path.startswith('/ws/'):
            print(f"[+] WebSocket request: {self.path}")
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', base64.b64encode(hashlib.sha1(
                self.headers.get('Sec-WebSocket-Key', '').encode() + b'258EAFA5-E914-47DA-95CA-C5AB0DC85B11'
            ).digest()).decode())
            self.end_headers()
            client = self.request
            self.request = None
            threading.Thread(target=handle_ws_upgrade, args=(client,), daemon=True).start()
            
        elif self.path == '/':
            self.serve_html()
        elif self.path == '/new':
            global uid, url, xray_proc
            uid = str(uuid.uuid4())
            config = build_xray_config(uid)
            with open('xray_config.json','w') as f: json.dump(config,f,indent=2)
            url = make_url(uid)
            start_xray()
            self.send_response(200); self.send_header('Content-Type','application/json'); self.end_headers()
            self.wfile.write(json.dumps({'url':url,'uuid':uid}).encode())
        elif self.path == '/health':
            self.send_response(200); self.end_headers(); self.wfile.write(b'OK')
        elif self.path == '/test':
            # Test Xray directly
            try:
                s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                s.connect(('127.0.0.1', XRAY_PORT))
                s.send(f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{XRAY_PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
                resp = s.recv(1024)
                s.close()
                self.send_response(200); self.end_headers()
                self.wfile.write(f"Xray on {XRAY_PORT}: {resp.decode()}".encode())
            except Exception as e:
                self.send_response(500); self.end_headers()
                self.wfile.write(str(e).encode())
        else:
            self.send_response(404); self.end_headers()

    def serve_html(self):
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
<div class="config-box" id="config">{url}</div>
<p class="info">Address: {DOMAIN} | Port: {PANEL_PORT}</p>
<p class="info">Path: {WS_PATH} | UUID: {uid[:16]}...</p>
<button class="btn btn-g" onclick="copy()">📋 Copy</button>
<button class="btn btn-b" onclick="gen()">🔄 New</button>
</div></div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('config').textContent);alert('Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url;alert('New config!')}}
</script></body></html>'''
        self.send_response(200); self.send_header('Content-Type','text/html; charset=utf-8'); self.end_headers()
        self.wfile.write(html.encode())
    def log_message(self, f, *a): pass

class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request, client_address):
        threading.Thread(target=self.process_request_thread, args=(request, client_address), daemon=True).start()
    def process_request_thread(self, request, client_address):
        try: self.finish_request(request, client_address)
        except: self.handle_error(request, client_address)
        finally: self.shutdown_request(request)

print(f"\n{'='*50}")
print(f"✅ Panel: http://{DOMAIN}:{PANEL_PORT}")
print(f"✅ Test: http://{DOMAIN}:{PANEL_PORT}/test")
print(f"✅ VLESS: {url}")
print(f"{'='*50}\n")
ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
