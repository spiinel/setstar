import os, sys, json, base64, subprocess, time, uuid, hashlib, threading, socket, select, struct, traceback
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

# ==================== CONFIG ====================
DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PANEL_PORT = int(os.environ.get('PORT', 8080))
XRAY_PORT = 10086
XRAY_VERSION = "v25.1.30"
XRAY_URL = f"https://github.com/XTLS/Xray-core/releases/download/{XRAY_VERSION}/Xray-linux-64.zip"

current_uid = str(uuid.uuid4())
current_path = f"/ws/{current_uid}"

xray_process = None
process_lock = threading.Lock()

print(f"[*] Domain : {DOMAIN}")
print(f"[*] Panel  : {PANEL_PORT}")
print(f"[*] Xray   : {XRAY_PORT}")
print(f"[*] UUID   : {current_uid[:16]}...")

# ==================== DOWNLOAD ====================
def download_xray():
    if os.path.exists('./xray'):
        return True
    try:
        print(f"[*] Downloading Xray {XRAY_VERSION}...")
        r = req.get(XRAY_URL, timeout=120)
        if r.status_code != 200:
            print(f"[-] HTTP {r.status_code}")
            return False
        with open('xray.zip', 'wb') as f:
            f.write(r.content)
        import zipfile
        with zipfile.ZipFile('xray.zip', 'r') as z:
            z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("[+] Downloaded")
        return True
    except Exception as e:
        print(f"[-] {e}")
        return False

# ==================== XRAY CONFIG ====================
def build_xray_config():
    return {
        "log": {"loglevel": "info"},
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
            "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct",
            "settings": {"domainStrategy": "UseIP"}
        }]
    }

# ==================== XRAY PROCESS ====================
def start_xray():
    global xray_process
    with process_lock:
        if xray_process and xray_process.poll() is None:
            return True

        config = build_xray_config()
        with open('xray_config.json', 'w') as f:
            json.dump(config, f, indent=2)

        try:
            xray_process = subprocess.Popen(
                ['./xray', 'run', '-config', 'xray_config.json'],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(2)
            if xray_process.poll() is not None:
                print("[-] Xray exited immediately")
                return False
            print(f"[+] Xray PID: {xray_process.pid}")
            return True
        except Exception as e:
            print(f"[-] Xray start error: {e}")
            return False

# ==================== HEALTH CHECK ====================
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

# ==================== WATCHDOG ====================
def watchdog():
    global xray_process
    while True:
        time.sleep(30)
        with process_lock:
            if xray_process is None or xray_process.poll() is not None:
                print("[!] Xray stopped, restarting...")
                start_xray()

# ==================== WEBSOCKET RELAY (SAFE) ====================
def ws_send_frame(sock, payload, opcode=0x2):
    try:
        header = bytearray([0x80 | opcode])
        length = len(payload)
        if length <= 125:
            header.append(length)
        elif length <= 65535:
            header.append(126)
            header.extend(struct.pack('!H', length))
        else:
            header.append(127)
            header.extend(struct.pack('!Q', length))
        sock.sendall(bytes(header) + payload)
        return True
    except:
        return False

def ws_recv_frame(sock):
    try:
        header = sock.recv(2)
        if len(header) < 2:
            return None, None
        opcode = header[0] & 0x0F
        length = header[1] & 0x7F
        if length == 126:
            data = sock.recv(2)
            if len(data) < 2:
                return None, None
            length = struct.unpack('!H', data)[0]
        elif length == 127:
            data = sock.recv(8)
            if len(data) < 8:
                return None, None
            length = struct.unpack('!Q', data)[0]
        payload = bytearray()
        while len(payload) < length:
            chunk = sock.recv(min(4096, length - len(payload)))
            if not chunk:
                break
            payload.extend(chunk)
        return opcode, bytes(payload)
    except:
        return None, None

def relay_ws(client, backend):
    sockets = [client, backend]
    try:
        while True:
            readable, _, exceptional = select.select(sockets, [], sockets, 60)
            if exceptional:
                break
            for s in readable:
                opcode, data = ws_recv_frame(s)
                if opcode is None:
                    return
                if opcode == 0x8:
                    return
                if opcode == 0x9:
                    ws_send_frame(s, data, 0xA)
                    continue
                target = backend if s == client else client
                if not ws_send_frame(target, data, opcode):
                    return
    except:
        pass

def handle_ws_client(client_sock):
    backend = None
    try:
        backend = socket.socket()
        backend.settimeout(10)
        backend.connect(('127.0.0.1', XRAY_PORT))
        
        req_str = (
            f"GET {current_path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{XRAY_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        backend.sendall(req_str.encode())
        
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk:
                break
            resp += chunk
        
        if b"101" not in resp:
            return
        
        relay_ws(client_sock, backend)
    except Exception as e:
        print(f"[!] WS relay error: {e}")
        traceback.print_exc()
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

# ==================== HTTP HANDLER ====================
class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path.startswith('/ws/'):
            key = self.headers.get('Sec-WebSocket-Key', '')
            if not key:
                self.send_response(400)
                self.end_headers()
                return
            
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
            threading.Thread(target=handle_ws_client, args=(client,), daemon=True).start()
            return

        if self.path == '/':
            url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
            sub = base64.b64encode((url + "\n").encode()).decode()
            
            html = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel VLESS</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:600px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:8px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.75em;margin:8px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:.9em;margin:4px}}
.btn-b{{background:#1f6feb}}</style></head><body>
<h1 style="background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent">🌀 Spinel VLESS</h1>
<p style="color:#8b949e">{DOMAIN}</p>
<div class="box"><h3 style="color:#58a6ff">📡 VLESS Config</h3><code id="c">{url}</code>
<button class="btn" onclick="copy('c')">📋 Copy Config</button></div>
<div class="box"><h3 style="color:#58a6ff">🔗 Subscription</h3><code id="s">{sub}</code>
<button class="btn btn-b" onclick="copy('s')">📋 Copy Subscription</button></div>
<script>function copy(id){{navigator.clipboard.writeText(document.getElementById(id).textContent);alert('Copied!')}}</script>
</body></html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())
        
        elif self.path == '/health':
            ok = health_check()
            self.send_response(200 if ok else 503)
            self.end_headers()
            self.wfile.write(b'OK' if ok else b'FAIL')
        
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, f, *a):
        pass

# ==================== THREADED SERVER ====================
class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request, client_address):
        t = threading.Thread(target=self._process, args=(request, client_address), daemon=True)
        t.start()

    def _process(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception as e:
            print(f"[!] Request error: {e}")
            traceback.print_exc()
        finally:
            self.shutdown_request(request)

# ==================== MAIN ====================
if __name__ == '__main__':
    if not download_xray():
        sys.exit(1)

    if not start_xray():
        sys.exit(1)

    threading.Thread(target=watchdog, daemon=True).start()

    url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
    sub = base64.b64encode((url + "\n").encode()).decode()

    print(f"""
╔══════════════════════════════════════╗
║   🌀 Spinel VLESS Ready             ║
╠══════════════════════════════════════╣
║ Panel: http://{DOMAIN}:{PANEL_PORT}  ║
║ VLESS: {url[:50]}...║
╚══════════════════════════════════════╝
""")

    try:
        ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        print("\n[*] Shutting down...")
