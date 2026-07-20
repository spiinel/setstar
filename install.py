import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket
import requests as req

# ========== CONFIG ==========
DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PORT = int(os.environ.get('PORT', 8080))

print(f"""
╔══════════════════════════════════════╗
║   🌀 Spinel VLESS - Railway Edition ║
║   Domain: {DOMAIN}                   ║
║   Port: {PORT}                       ║
╚══════════════════════════════════════╝
""")

# ========== DOWNLOAD XRAY ==========
def download_xray():
    if os.path.exists('./xray'): return True
    print("[*] Downloading Xray Core...")
    try:
        url = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
        r = req.get(url, timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("[+] Xray downloaded")
        return True
    except Exception as e:
        print(f"[-] Error: {e}")
        return False

# ========== GENERATE KEYS ==========
def generate_reality_keys():
    try:
        r = subprocess.run(['./xray', 'x25519'], capture_output=True, text=True, timeout=10)
        pk, pub = None, None
        for line in r.stdout.split('\n'):
            if 'Private key:' in line: pk = line.split(':')[1].strip()
            if 'Public key:' in line: pub = line.split(':')[1].strip()
        if pk and pub: return pk, pub
    except: pass
    return 'aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd', 'Ag0kP6mSdY2xU4kP6mSdY2xU4kP6mSdY2xU4kP6mSd'

# ========== BUILD XRAY CONFIG (Sanayi Style) ==========
def build_xray_config(uid, private_key, short_id):
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [
            {
                "tag": "vless-ws-tls",
                "listen": "0.0.0.0",
                "port": PORT,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": uid, "encryption": "none"}],
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "ws",
                    "security": "none",
                    "wsSettings": {
                        "path": f"/ws/{uid}",
                        "headers": {"Host": DOMAIN}
                    }
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            },
            {
                "tag": "vless-reality",
                "listen": "0.0.0.0",
                "port": PORT + 1,
                "protocol": "vless",
                "settings": {
                    "clients": [{"id": uid, "flow": "xtls-rprx-vision", "encryption": "none"}],
                    "decryption": "none"
                },
                "streamSettings": {
                    "network": "tcp",
                    "security": "reality",
                    "realitySettings": {
                        "show": False,
                        "dest": "www.google.com:443",
                        "xver": 0,
                        "serverNames": ["www.google.com", "google.com", "www.apple.com", "apple.com"],
                        "privateKey": private_key,
                        "shortIds": ["", short_id],
                        "minClientVer": "",
                        "maxClientVer": "",
                        "maxTimeDiff": 0
                    }
                },
                "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
            }
        ],
        "outbounds": [
            {"protocol": "freedom", "tag": "direct", "settings": {}},
            {"protocol": "blackhole", "tag": "blocked", "settings": {}}
        ]
    }

# ========== MAKE VLESS URLS ==========
def make_ws_url(uid):
    path = f"/ws/{uid}"
    params = f"security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome"
    return f"vless://{uid}@{DOMAIN}:443?{params}#Spinel-WS"

def make_reality_url(uid, public_key, short_id):
    params = f"security=reality&encryption=none&flow=xtls-rprx-vision&sni=www.google.com&fp=chrome&alpn=h2,http/1.1&pbk={public_key}&sid={short_id}"
    return f"vless://{uid}@{DOMAIN}:443?{params}#Spinel-Reality"

# ========== MAIN ==========
if not download_xray():
    print("[-] Failed to download Xray")
    sys.exit(1)

uid = str(uuid_lib.uuid4())
private_key, public_key = generate_reality_keys()
short_id = uuid_lib.uuid4().hex[:16]

ws_url = make_ws_url(uid)
reality_url = make_reality_url(uid, public_key, short_id)

config = build_xray_config(uid, private_key, short_id)
with open('xray_config.json', 'w') as f:
    json.dump(config, f, indent=2)

print("[*] Starting Xray...")
subprocess.Popen(['./xray', 'run', '-config', 'xray_config.json'],
                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
time.sleep(2)

# ========== SIMPLE OUTPUT ==========
print(f"""
╔══════════════════════════════════════════════════╗
║   ✅ Spinel VLESS Ready                          ║
╚══════════════════════════════════════════════════╝

📡 WebSocket + TLS (Recommended):
{ws_url}

📡 Reality + TCP (Alternative):
{reality_url}

📋 Connection Info:
   Domain: {DOMAIN}
   Port: 443 (WebSocket) / 443 (Reality)
   UUID: {uid}
   WS Path: /ws/{uid}
   Reality SNI: www.google.com
   Fingerprint: chrome

💡 How to use:
   1. Copy one of the VLESS links above
   2. Open v2rayNG/Nekobox
   3. Import from clipboard
   4. Connect ✅
""")

# ========== KEEP ALIVE ==========
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    print("\n[*] Shutting down...")
