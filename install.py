import os, sys, json, base64, subprocess, time, uuid, hashlib, threading, socket, select, struct, traceback, logging
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

# ==================== LOGGING ====================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [%(levelname)s] %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
log = logging.getLogger('Spinel')

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

log.info(f"Domain: {DOMAIN} | Panel: {PANEL_PORT} | Xray: {XRAY_PORT}")

# ==================== DOWNLOAD ====================
def download_xray():
    if os.path.exists('./xray') and os.path.getsize('./xray') > 10000000:
        return True
    
    log.info(f"Downloading Xray {XRAY_VERSION}...")
    try:
        r = req.get(XRAY_URL, timeout=120, headers={'User-Agent': 'Mozilla/5.0'})
        if r.status_code != 200 or len(r.content) < 5000000:
            log.error(f"Download failed: status={r.status_code}, size={len(r.content)}")
            return False
        
        with open('xray.zip', 'wb') as f:
            f.write(r.content)
        
        import zipfile
        if not zipfile.is_zipfile('xray.zip'):
            log.error("Downloaded file is not a valid ZIP")
            os.remove('xray.zip')
            return False
        
        with zipfile.ZipFile('xray.zip', 'r') as z:
            z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        
        if not os.path.exists('./xray') or os.path.getsize('./xray') < 10000000:
            log.error("Extracted xray binary is invalid")
            return False
        
        log.info("Xray downloaded successfully")
        return True
    except Exception as e:
        log.error(f"Download error: {e}")
        return False

# ==================== XRAY CONFIG ====================
def build_config():
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
        
        with open('xray_config.json', 'w') as f:
            json.dump(build_config(), f, indent=2)
        
        try:
            log_file = open('xray.log', 'a')
            xray_process = subprocess.Popen(
                ['./xray', 'run', '-config', 'xray_config.json'],
                stdout=log_file,
                stderr=subprocess.STDOUT
            )
            time.sleep(3)
            
            if xray_process.poll() is not None:
                log.error("Xray exited immediately - check xray.log")
                return False
            
            log.info(f"Xray started (PID: {xray_process.pid})")
            return True
        except Exception as e:
            log.error(f"Xray start error: {e}")
            return False

# ==================== HEALTH CHECK ====================
def health_check():
    try:
        s = socket.socket()
        s.settimeout(5)
        s.connect(('127.0.0.1', XRAY_PORT))
        
        req = (
            f"GET {current_path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{XRAY_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        s.sendall(req.encode())
        
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
        
        s.close()
        
        if b"101" in resp:
            log.info("Health check: WebSocket upgrade OK")
            return True
        else:
            log.warning(f"Health check: unexpected response: {resp[:200]}")
            return False
    except Exception as e:
        log.warning(f"Health check failed: {e}")
        return False

# ==================== WATCHDOG ====================
def watchdog():
    while True:
        time.sleep(30)
        with process_lock:
            if xray_process is None or xray_process.poll() is not None:
                log.warning("Watchdog: Xray not running, restarting...")
                start_xray()
            elif not health_check():
                log.warning("Watchdog: Health check failed, restarting Xray...")
                try:
                    xray_process.terminate()
                    xray_process.wait(timeout=5)
                except:
                    try:
                        xray_process.kill()
                    except:
                        pass
                start_xray()

# ==================== WEBSOCKET PIPE ====================
def pipe_data(src, dst, name):
    """Simple pipe with error handling"""
    try:
        while True:
            data = src.recv(32768)
            if not data:
                break
            dst.sendall(data)
    except (socket.timeout, ConnectionError, BrokenPipeError, OSError):
        pass
    except Exception as e:
        log.debug(f"Pipe {name} error: {e}")
    finally:
        try:
            src.close()
        except:
            pass
        try:
            dst.close()
        except:
            pass

def handle_ws_client(client_sock, client_addr):
    """Handle WebSocket upgrade and relay"""
    backend = None
    try:
        # Connect to Xray
        backend = socket.socket()
        backend.settimeout(10)
        backend.connect(('127.0.0.1', XRAY_PORT))
        
        # Send WebSocket upgrade request
        req = (
            f"GET {current_path} HTTP/1.1\r\n"
            f"Host: 127.0.0.1:{XRAY_PORT}\r\n"
            f"Upgrade: websocket\r\n"
            f"Connection: Upgrade\r\n"
            f"Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n"
            f"\r\n"
        )
        backend.sendall(req.encode())
        
        # Read upgrade response
        resp = b""
        while b"\r\n\r\n" not in resp:
            chunk = backend.recv(4096)
            if not chunk:
                log.warning(f"WS: No response from Xray for {client_addr}")
                return
            resp += chunk
        
        if b"101" not in resp:
            log.warning(f"WS: Xray didn't upgrade for {client_addr}")
            return
        
        # Now just pipe data - no frame parsing needed!
        # Railway handles WebSocket frames, Xray handles them too
        # We just need to move bytes between client and Xray
        
        t1 = threading.Thread(target=pipe_data, args=(client_sock, backend, f"CLIENT->XRAY"), daemon=True)
        t2 = threading.Thread(target=pipe_data, args=(backend, client_sock, f"XRAY->CLIENT"), daemon=True)
        t1.start()
        t2.start()
        t1.join(timeout=300)
        t2.join(timeout=300)
        
    except Exception as e:
        log.error(f"WS error for {client_addr}: {e}")
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
            client_addr = self.client_address
            
            threading.Thread(
                target=handle_ws_client,
                args=(client, client_addr),
                daemon=True
            ).start()
            return
        
        if self.path == '/':
            url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
            sub = base64.b64encode((url + "\n").encode()).decode()
            
            html = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel VLESS</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:600px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
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

    def log_message(self, format, *args):
        pass

# ==================== THREADED SERVER ====================
class ThreadedHTTPServer(HTTPServer):
    def process_request(self, request, client_address):
        t = threading.Thread(
            target=self._process,
            args=(request, client_address),
            daemon=True
        )
        t.start()

    def _process(self, request, client_address):
        try:
            self.finish_request(request, client_address)
        except Exception as e:
            log.error(f"Request error: {e}")

# ==================== MAIN ====================
if __name__ == '__main__':
    if not download_xray():
        log.error("Failed to download Xray")
        sys.exit(1)
    
    if not start_xray():
        log.error("Failed to start Xray")
        sys.exit(1)
    
    threading.Thread(target=watchdog, daemon=True).start()
    
    url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
    log.info(f"Panel: http://{DOMAIN}:{PANEL_PORT}")
    log.info(f"VLESS: {url}")
    
    try:
        ThreadedHTTPServer(('0.0.0.0', PANEL_PORT), Handler).serve_forever()
    except KeyboardInterrupt:
        log.info("Shutting down...")
