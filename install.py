import os, sys, json, base64, subprocess, time, uuid, secrets, zipfile, socket, threading, select, struct, random
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
if not DOMAIN:
    DOMAIN = os.environ.get('RAILWAY_STATIC_URL', '')
if not DOMAIN:
    try: DOMAIN = socket.gethostname()
    except: DOMAIN = 'localhost'

PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = random.randint(10000, 60000)
WS_PATH = f"/ws/{uuid.uuid4().hex[:16]}"
FINGERPRINT = "chrome"
ALPN = "h2,http/1.1"
PUBLIC_PORT = 443

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
        return True
    except: return False

def build_xray_config(uid):
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "tag": "vless-ws",
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
        "security=tls", "encryption=none", "type=ws",
        f"path={WS_PATH}", f"host={DOMAIN}", f"sni={DOMAIN}",
        f"fp={FINGERPRINT}", f"alpn={ALPN}"
    ]
    return f"vless://{uid}@{DOMAIN}:{PUBLIC_PORT}?{'&'.join(params)}#Spinel-{DOMAIN[:8]}"

download_xray()
uid = str(uuid.uuid4())
config = build_xray_config(uid)
with open('xray_config.json', 'w') as f: json.dump(config, f, indent=2)

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
url = make_url(uid)

# ========== WebSocket Frame Utils ==========
def ws_read_frame(sock):
    """Read a single WebSocket frame, return (opcode, payload) or None"""
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
    """Send a WebSocket frame (unmasked, server to client)"""
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
    sock.send(bytes(header) + payload)

def ws_relay(client, backend):
    """Bidirectional WebSocket relay between client and backend (Xray)"""
    try:
        while True:
            r, _, _ = select.select([client, backend], [], [], 300)
            for s in r:
                frame = ws_read_frame(s)
                if frame is None:
                    return
                opcode, data = frame
                if opcode == 0x8:  # Close
                    return
                if s == client:
                    # Client -> Xray (send unmasked)
                    ws_send_frame(backend, data, opcode)
                else:
                    # Xray -> Client (send unmasked)
                    ws_send_frame(client, data, opcode)
    except: pass

def handle_ws_upgrade(client_sock):
    try:
        # Connect to Xray via WebSocket
        backend = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        backend.connect(('127.0.0.1', XRAY_PORT))
        key = base64.b64encode(os.urandom(16)).decode()
        req = f"GET {WS_PATH} HTTP/1.1\r\nHost: 127.0.0.1:{XRAY_PORT}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n"
        backend.send(req.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += backend.recv(4096)
        if b"101" not in resp:
            return
        ws_relay(client_sock, backend)
    except: pass
    finally:
        try: client_sock.close()
        except: pass
        try: backend.close()
        except: pass

class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', '')  # optional
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
.info{{color:var(--dim);font-size:.7em;margin:3px 0}}.badge{{display:inline-block;padding:2px 8px;border-radius:10px;font-size:.65em;font-weight:bold;margin:2px}}
.badge-g{{background:rgba(63,185,80,.2);color:#3fb950}}
.btn{{padding:10px;border:none;border-radius:8px;font-weight:bold;cursor:pointer;font-size:.8em;margin:4px 0;width:100%}}
.btn-g{{background:#238636;color:#fff}}.btn-b{{background:#1f6feb;color:#fff}}
.row{{display:flex;gap:8px}}.row .btn{{flex:1}}
</style></head><body>
<div class="nav"><h1>🌀 Spinel VLESS</h1><p style="color:var(--dim);font-size:.75em">{DOMAIN}</p></div>
<div class="container">
<div class="card"><h2>📡 VLESS Config <span class="badge badge-g">WS+TLS</span></h2>
<div class="config-box" id="config">{url}</div>
<p class="info">Address: {DOMAIN} | Port: 443</p>
<p class="info">Path: {WS_PATH} | Host: {DOMAIN}</p>
<p class="info">SNI: {DOMAIN} | Fingerprint: {FINGERPRINT}</p>
<p class="info">UUID: {uid[:16]}...</p>
<div class="row">
<button class="btn btn-g" onclick="copy()">📋 Copy</button>
<button class="btn btn-b" onclick="gen()">🔄 New</button>
</div></div></div>
<script>
function copy(){{navigator.clipboard.writeText(document.getElementById('config').textContent);alert('✅ Copied!')}}
async function gen(){{let r=await fetch('/new');let d=await r.json();document.getElementById('config').textContent=d.url;alert('✅ New config!')}}
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

print(f"✅ Spinel Panel ready | VLESS URL: {url}")
ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
