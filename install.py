import os, sys, json, base64, subprocess, time, uuid, hashlib, threading, socket
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PANEL_PORT = 10000
XRAY_PORT = int(os.environ.get('PORT', 8080))

current_uid = str(uuid.uuid4())
current_path = f"/ws/{current_uid}"

xray_process = None
process_lock = threading.Lock()

print(f"Domain: {DOMAIN}")
print(f"Xray on PORT: {XRAY_PORT}")
print(f"Panel on: {PANEL_PORT}")
print(f"UUID: {current_uid}")
print(f"Path: {current_path}")

def download_xray():
    if os.path.exists('./xray') and os.path.getsize('./xray') > 10000000:
        return True
    try:
        r = req.get("https://github.com/XTLS/Xray-core/releases/download/v1.8.21/Xray-linux-64.zip", timeout=120)
        with open('xray.zip', 'wb') as f:
            f.write(r.content)
        import zipfile
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
        "inbounds": [
            {
                "listen": "0.0.0.0",
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
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "listen": "127.0.0.1",
                "port": PANEL_PORT,
                "protocol": "dokodemo-door",
                "settings": {
                    "address": "127.0.0.1",
                    "port": PANEL_PORT,
                    "network": "tcp"
                }
            }
        ],
        "outbounds": [
            {
                "protocol": "freedom",
                "tag": "direct",
                "settings": {"domainStrategy": "UseIP"}
            }
        ]
    }

def start_xray():
    global xray_process
    with process_lock:
        if xray_process is not None and xray_process.poll() is None:
            return True
        with open('xray_config.json', 'w') as f:
            json.dump(build_xray_config(), f, indent=2)
        xray_process = subprocess.Popen(
            ['./xray', 'run', '-config', 'xray_config.json'],
            stdout=sys.stdout,
            stderr=sys.stderr
        )
        time.sleep(3)
        ok = xray_process.poll() is None
        if ok:
            print(f"[+] Xray running on 0.0.0.0:{XRAY_PORT}")
        return ok

class H(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == '/' or self.path == '':
            url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
            sub = base64.b64encode((url + "\n").encode()).decode()
            html = f'''<!DOCTYPE html><html lang="fa" dir="rtl"><head><meta charset="UTF-8"><title>Spinel</title>
<style>body{{font-family:system-ui;background:#0d1117;color:#c9d1d9;padding:15px;text-align:center}}
.box{{background:#161b22;border:1px solid #30363d;border-radius:12px;padding:15px;max-width:600px;margin:15px auto;text-align:right}}
code{{background:rgba(0,0,0,.4);padding:10px;display:block;border-radius:6px;word-break:break-all;color:#3fb950;font-size:.8em;margin:10px 0}}
.btn{{background:#238636;color:white;border:none;padding:10px 20px;border-radius:8px;cursor:pointer;font-size:.9em;margin:4px}}</style></head><body>
<h1 style="background:linear-gradient(45deg,#58a6ff,#bc8cff);-webkit-background-clip:text;-webkit-text-fill-color:transparent">🌀 Spinel VLESS</h1>
<p style="color:#8b949e">{DOMAIN}</p>
<div class="box"><h3>📡 Config</h3><code id="c">{url}</code>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('c').textContent);alert('Copied!')">📋 Copy</button></div>
<div class="box"><h3>🔗 Subscription</h3><code id="s">{sub}</code>
<button class="btn" onclick="navigator.clipboard.writeText(document.getElementById('s').textContent);alert('Copied!')">📋 Copy Sub</button></div>
</body></html>'''
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(html.encode())
        elif self.path == '/health':
            self.send_response(200)
            self.end_headers()
            self.wfile.write(b'OK')
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, f, *a):
        pass

if __name__ == '__main__':
    download_xray()
    if start_xray():
        url = f"vless://{current_uid}@{DOMAIN}:443?security=none&encryption=none&type=ws&path={current_path}&host={DOMAIN}#Spinel"
        print(f"\nReady!\n{url}\n")
        
        # Panel on internal port
        panel = HTTPServer(('127.0.0.1', PANEL_PORT), H)
        threading.Thread(target=panel.serve_forever, daemon=True).start()
        print(f"[+] Panel on 127.0.0.1:{PANEL_PORT}")
        
        # Keep alive
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            pass
