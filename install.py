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
    if os.path.exists('./xray'):
        return True
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f:
            f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z:
            z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        return True
    except:
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
                "clients": [{"id": uid, "encryption": "none"}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": path}
            }
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct",
            "settings": {"domainStrategy": "UseIP"}
        }]
    }

def generate_all_configs():
    """تولید تمام کانفیگ‌های ممکن"""
    configs = []
    
    # 1. WebSocket + security=none (روش اصلی Railway)
    configs.append({
        "name": "WS-None",
        "url": f"vless://{uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={path}&host={DOMAIN}#Spinel-WS-None"
    })
    
    # 2. WebSocket + security=tls + allowInsecure
    configs.append({
        "name": "WS-TLS-Insecure",
        "url": f"vless://{uid}@{DOMAIN}:443?security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome&allowInsecure=1#Spinel-WS-TLS"
    })
    
    # 3. WebSocket + security=tls (بدون allowInsecure)
    configs.append({
        "name": "WS-TLS",
        "url": f"vless://{uid}@{DOMAIN}:443?security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome#Spinel-WS-TLS"
    })
    
    # 4. WebSocket + port 8080 + security=none
    configs.append({
        "name": "WS-8080-None",
        "url": f"vless://{uid}@{DOMAIN}:8080?security=none&encryption=none&type=ws&path={path}&host={DOMAIN}#Spinel-WS-8080"
    })
    
    # 5. TCP + security=none
    configs.append({
        "name": "TCP-None",
        "url": f"vless://{uid}@{DOMAIN}:443?security=none&encryption=none&type=tcp#Spinel-TCP-None"
    })
    
    # 6. TCP + security=tls
    configs.append({
        "name": "TCP-TLS",
        "url": f"vless://{uid}@{DOMAIN}:443?security=tls&encryption=none&type=tcp&sni={DOMAIN}&fp=chrome&alpn=h2,http/1.1#Spinel-TCP-TLS"
    })
    
    # 7. gRPC + security=tls
    configs.append({
        "name": "gRPC-TLS",
        "url": f"vless://{uid}@{DOMAIN}:443?security=tls&encryption=none&type=grpc&serviceName={path}&sni={DOMAIN}&fp=chrome&alpn=h2#Spinel-gRPC-TLS"
    })
    
    return configs

def make_subscription(configs):
    """ساخت لینک سابسکریپشن"""
    urls = [c["url"] for c in configs]
    content = "\n".join(urls)
    return base64.b64encode(content.encode()).decode()

download_xray()

with open('xray.json', 'w') as f:
    json.dump(build_xray_config(), f)

subprocess.Popen(
    ['./xray', 'run', '-config', 'xray.json'],
    stdout=subprocess.DEVNULL,
    stderr=subprocess.DEVNULL
)
time.sleep(2)

all_configs = generate_all_configs()
sub_b64 = make_subscription(all_configs)

def relay(a, b):
    try:
        while True:
            d = a.recv(4096)
            if not d:
                break
            b.send(d)
    except:
        pass
    finally:
        try:
            a.close()
        except:
            pass
        try:
            b.close()
        except:
            pass

def handle_ws(client):
    backend = None
    try:
        backend = socket.socket()
        backend.connect(('127.0.0.1', XRAY_PORT))
        req_str = f"GET {path} HTTP/1.1\r\nHost: 127.0.0.1\r\nUpgrade: websocket\r\nConnection: Upgrade\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\nSec-WebSocket-Version: 13\r\n\r\n"
        backend.send(req_str.encode())
        resp = b""
        while b"\r\n\r\n" not in resp:
            resp += backend.recv(4096)
        if b"101" not in resp:
            return
        t1 = threading.Thread(target=relay, args=(client, backend), daemon=True)
        t2 = threading.Thread(target=relay, args=(backend, client), daemon=True)
        t1.start()
        t2.start()
        t1.join()
        t2.join()
    except:
        pass
    finally:
        try:
            client.close()
        except:
            pass
        if backend is not None:
            try:
                backend.close()
            except:
                pass

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
        
        elif self.path == '/' or self.path == '':
            # نمایش همه کانفیگ‌ها
            configs_html = ""
            for i, c in enumerate(all_configs, 1):
                configs_html += f"""
                <div class="config-item">
                    <strong>#{i} - {c['name']}</strong>
                    <code>{c['url'][:80]}...</code>
                    <button class="btn" onclick="copy('{c['url'].replace(chr(39), chr(92)+chr(39))}')">📋 Copy</button>
                </div>"""
            
            h = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel VLESS</title>
<style>
body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
h1{{background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:700px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:8px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.75em;margin:8px 0}}
.btn{{background:#238636;color:white;border:none;padding:8px 15px;border-radius:6px;cursor:pointer;font-size:.8em;margin:3px}}
.btn-b{{background:#1f6feb}}.btn-r{{background:#da3633}}
.config-item{{background:rgba(0,0,0,.2);padding:10px;margin:8px 0;border-radius:8px;border:1px solid #30363d}}
.info{{color:#8b949e;font-size:.75em}}
</style></head><body>
<h1>🌀 Spinel VLESS</h1>
<p class="info">{DOMAIN} | UUID: {uid[:16]}...</p>

<div class="box">
<h3 style="color:#58a6ff">🔗 Subscription Link (All Configs)</h3>
<code>{sub_b64}</code>
<p class="info">Use this in v2rayNG: + → Import from Subscription</p>
<button class="btn btn-b" onclick="copy('{sub_b64}')">📋 Copy Subscription</button>
</div>

<div class="box">
<h3 style="color:#58a6ff">📡 All Configs ({len(all_configs)} methods)</h3>
{configs_html}
</div>

<div class="box">
<h3 style="color:#58a6ff">📱 How to Use</h3>
<p class="info" style="line-height:2">
1. Copy <strong>Subscription Link</strong> above<br>
2. Open v2rayNG → + → <strong>Import from Subscription</strong><br>
3. Paste the subscription code<br>
4. All configs will be imported<br>
5. Try each one to find working method ✅
</p>
</div>

<script>
function copy(t){{navigator.clipboard.writeText(t);alert('✅ Copied!')}}
</script></body></html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(h.encode())
        
        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, f, *a):
        pass

class T(HTTPServer):
    def process_request(self, r, a):
        threading.Thread(target=self.process_request_thread, args=(r, a), daemon=True).start()

    def process_request_thread(self, r, a):
        try:
            self.finish_request(r, a)
        except:
            self.handle_error(r, a)
        finally:
            self.shutdown_request(r)

print(f"\nPanel: http://{DOMAIN}:{PANEL_PORT}")
print(f"Subscription: {sub_b64[:50]}...\n")
T(('0.0.0.0', PANEL_PORT), H).serve_forever()
