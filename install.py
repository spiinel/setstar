import os, sys, json, base64, subprocess, time, uuid, hashlib, threading, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086
XRAY_VERSION = "v25.1.30"
XRAY_URL = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/Xray-linux-64.zip"
XRAY_SHA256 = None  # optional

current_uid = str(uuid.uuid4())
current_path = f"/ws/{current_uid}"

print(f"[*] Domain : {DOMAIN}")
print(f"[*] Panel  : {PANEL_PORT}")
print(f"[*] Xray   : {XRAY_PORT}")
print(f"[*] Path   : {current_path}")
print(f"[*] UUID   : {current_uid}")

def download_xray():
    if os.path.exists('./xray'):
        return True
    try:
        print("[*] Downloading Xray", XRAY_VERSION)
        r = req.get(XRAY_URL, timeout=120)
        if r.status_code != 200:
            print("[-] Download failed, status", r.status_code)
            return False
        with open('xray.zip', 'wb') as f:
            f.write(r.content)
        import zipfile
        with zipfile.ZipFile('xray.zip', 'r') as z:
            z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("[+] Xray downloaded")
        return True
    except Exception as e:
        print("[-]", e)
        return False

def build_xray_config():
    return {
        "log": {"loglevel": "warning"},
        "dns": {"servers": ["8.8.8.8", "1.1.1.1"]},
        "inbounds": [{
            "listen": "127.0.0.1",
            "port": XRAY_PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": current_uid, "encryption": "none"}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": current_path}
            },
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
            "tag": "vless-in"
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct",
            "settings": {"domainStrategy": "UseIP"}
        }],
        "routing": {
            "domainStrategy": "AsIs",
            "rules": [{"type": "field", "inboundTag": ["vless-in"], "outboundTag": "direct"}]
        }
    }

def make_url():
    params = f"security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}"
    return f"vless://{current_uid}@{DOMAIN}:443?{params}#Spinel"

def make_subscription():
    urls = [make_url()]
    return base64.b64encode("\n".join(urls).encode()).decode()

def health_check():
    try:
        s = socket.socket()
        s.settimeout(3)
        s.connect(('127.0.0.1', XRAY_PORT))
        s.send(f"GET {current_path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n".encode())
        resp = s.recv(1024)
        s.close()
        return b"101" in resp
    except:
        return False

def start_xray():
    config = build_xray_config()
    with open('xray_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    
    log_file = open('xray.log', 'a')
    proc = subprocess.Popen(
        ['./xray', 'run', '-config', 'xray_config.json'],
        stdout=log_file,
        stderr=subprocess.STDOUT
    )
    time.sleep(3)
    
    if proc.poll() is not None:
        print("[-] Xray exited immediately, check xray.log")
        return None
    
    if health_check():
        print("[+] Xray started & healthy")
    else:
        print("[!] Xray started but health check failed, check xray.log")
    
    return proc

# ----- WebSocket relay with correct framing -----
def ws_send(sock, payload, opcode=0x2):
    frame = bytearray()
    frame.append(0x80 | opcode)
    length = len(payload)
    if length <= 125:
        frame.append(length)
    elif length <= 65535:
        frame.append(126)
        import struct
        frame.extend(struct.pack('!H', length))
    else:
        frame.append(127)
        import struct
        frame.extend(struct.pack('!Q', length))
    frame.extend(payload)
    try:
        sock.sendall(bytes(frame))
    except:
        pass

def ws_recv(sock):
    try:
        import struct
        header = sock.recv(2)
        if len(header) < 2:
            return None, None
        opcode = header[0] & 0x0F
        masked = (header[1] & 0x80) != 0
        length = header[1] & 0x7F
        if length == 126:
            length = struct.unpack('!H', sock.recv(2))[0]
        elif length == 127:
            length = struct.unpack('!Q', sock.recv(8))[0]
        mask = sock.recv(4) if masked else b''
        payload = bytearray()
        while len(payload) < length:
            chunk = sock.recv(min(4096, length - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        if masked:
            payload = bytearray(b ^ mask[i % 4] for i, b in enumerate(payload))
        return opcode, bytes(payload)
    except:
        return None, None

def ws_relay(client, backend):
    try:
        while True:
            r, _, _ = select.select([client, backend], [], [], 300)
            for s in r:
                opcode, data = ws_recv(s)
                if opcode is None:
                    return
                if opcode == 0x8:  # close
                    ws_send(s, b'', 0x8)
                    return
                if opcode == 0x9:  # ping
                    ws_send(s, data, 0xA)  # pong
                    continue
                if s == client:
                    ws_send(backend, data, opcode)
                else:
                    ws_send(client, data, opcode)
    except:
        pass

def handle_ws(client_sock):
    backend = None
    try:
        backend = socket.socket()
        backend.settimeout(10)
        backend.connect(('127.0.0.1', XRAY_PORT))
        req_str = f"GET {current_path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        backend.sendall(req_str.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk:
                break
            resp += chunk
        if b"101" not in resp:
            return
        ws_relay(client_sock, backend)
    except Exception as e:
        print(f"[!] WS error: {e}")
    finally:
        try:
            client_sock.close()
        except:
            pass
        if backend:
            try:
                backend.close()
            except:
                pass

# ----- HTTP Handler -----
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            key = self.headers.get('Sec-WebSocket-Key', '')
            accept = base64.b64encode(
                hashlib.sha1((key + '258EAFA5-E914-47DA-95CA-C5AB0DC85B11').encode()).digest()
            ).decode()
            self.send_response(101)
            self.send_header('Upgrade', 'websocket')
            self.send_header('Connection', 'Upgrade')
            self.send_header('Sec-WebSocket-Accept', accept)
            self.end_headers()
            client = self.request
            self.request = None
            threading.Thread(target=handle_ws, args=(client,), daemon=True).start()
            return

        if self.path == '/':
            url = make_url()
            sub = make_subscription()
            html = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel VLESS</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:600px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:8px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.75em;margin:8px 0}}
.btn{{background:#238636;color:white;border:none;padding:8px 15px;border-radius:6px;cursor:pointer;font-size:.8em;margin:3px}}
.btn-b{{background:#1f6feb}}
</style></head><body>
<h1 style="background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent">🌀 Spinel VLESS</h1>
<p>{DOMAIN}</p>
<div class="box"><h3 style="color:#58a6ff">📡 VLESS Config</h3><code id="c">{url}</code>
<button class="btn" onclick="copy('c')">📋 Copy</button></div>
<div class="box"><h3 style="color:#58a6ff">🔗 Subscription</h3><code id="s">{sub}</code>
<button class="btn btn-b" onclick="copy('s')">📋 Copy Subscription</button></div>
<script>function copy(id){{navigator.clipboard.writeText(document.getElementById(id).textContent);alert('✅ Copied!')}}</script>
</body></html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK' if health_check() else b'FAIL')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, f, *a):
        pass

# ----- Main -----
if not download_xray():
    sys.exit(1)

proc = start_xray()
if not proc:
    sys.exit(1)

# Watchdog
def watchdog():
    while True:
        time.sleep(30)
        if proc.poll() is not None:
            print("[!] Xray stopped, restarting...")
            start_xray()

threading.Thread(target=watchdog, daemon=True).start()

import select

class ThreadedHTTPServer(HTTPServer):
    def process_request(self, r, a):
        threading.Thread(target=self._process, args=(r, a), daemon=True).start()
    def _process(self, r, a):
        try:
            self.finish_request(r, a)
        except:
            self.handle_error(r, a)
        finally:
            self.shutdown_request(r)

url = make_url()
sub = make_subscription()
print(f"\n{'='*50}")
print(f"Panel : http://{DOMAIN}:{PANEL_PORT}")
print(f"VLESS : {url}")
print(f"Sub   : {sub[:60]}...")
print(f"{'='*50}\n")

ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
