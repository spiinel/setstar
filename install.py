import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket
import requests as req

def get_domain():
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if domain: return domain
    domain = os.environ.get('RAILWAY_STATIC_URL', '')
    if domain: return domain
    return socket.gethostname()

DOMAIN = get_domain()
PORT = int(os.environ.get('PORT', 8080))

print("=" * 50)
print(f"  🌀 Spinel VLESS Panel v3.1")
print(f"  Domain : {DOMAIN}")
print(f"  Port   : {PORT}")
print("=" * 50)

class XrayDownloader:
    XRAY_URL = "https://github.com/XTLS/Xray-core/releases/latest/download/Xray-linux-64.zip"
    XRAY_PATH = "./xray"
    
    @classmethod
    def download(cls):
        if os.path.exists(cls.XRAY_PATH):
            return True
        print("[1/4] Downloading Xray Core...")
        try:
            resp = req.get(cls.XRAY_URL, timeout=120)
            with open('./xray.zip', 'wb') as f: f.write(resp.content)
            with zipfile.ZipFile('./xray.zip', 'r') as z: z.extractall('.')
            os.chmod(cls.XRAY_PATH, 0o755)
            os.remove('./xray.zip')
            print("       ✓ Xray downloaded")
            return True
        except Exception as e:
            print(f"       ✗ Failed: {e}")
            return False

class KeyGenerator:
    @classmethod
    def generate(cls):
        try:
            result = subprocess.run(['./xray', 'x25519'], capture_output=True, text=True, timeout=10)
            pk, pub = None, None
            for line in result.stdout.split('\n'):
                if 'Private key:' in line: pk = line.split(':')[1].strip()
                if 'Public key:' in line: pub = line.split(':')[1].strip()
            if pk and pub: return pk, pub
        except: pass
        return ('aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd', 'Ag0kP6mSdY2xU4kP6mSdY2xU4kP6mSdY2xU4kP6mSd')

class XrayConfigBuilder:
    @staticmethod
    def build(uid, pk, sid, port):
        return {
            "log": {"loglevel": "warning"},
            "inbounds": [
                {
                    "tag": "vless-ws",
                    "listen": "0.0.0.0",
                    "port": port,
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": uid, "encryption": "none"}],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "none",
                        "wsSettings": {"path": f"/ws/{uid}"}
                    },
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
                },
                {
                    "tag": "vless-reality",
                    "listen": "0.0.0.0",
                    "port": port + 1 if port < 65535 else port - 1,
                    "protocol": "vless",
                    "settings": {
                        "clients": [{"id": uid, "flow": "xtls-rprx-vision", "encryption": "none"}],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "dest": "www.google.com:443",
                            "serverNames": ["www.google.com", "google.com"],
                            "privateKey": pk,
                            "shortIds": ["", sid]
                        }
                    },
                    "sniffing": {"enabled": True, "destOverride": ["http", "tls"]}
                }
            ],
            "outbounds": [
                {"protocol": "freedom", "tag": "direct"},
                {"protocol": "blackhole", "tag": "blocked"}
            ]
        }

class VlessURLGenerator:
    @staticmethod
    def websocket(uid):
        path = f"/ws/{uid}"
        params = f"security=tls&encryption=none&type=ws&path={path}&host={DOMAIN}&sni={DOMAIN}&alpn=http/1.1&fp=chrome"
        return f"vless://{uid}@{DOMAIN}:443?{params}#SpinelWS"
    
    @staticmethod
    def reality(uid, pub, sid):
        params = f"security=reality&encryption=none&flow=xtls-rprx-vision&sni=www.google.com&fp=chrome&pbk={pub}&sid={sid}"
        return f"vless://{uid}@{DOMAIN}:443?{params}#SpinelReality"

class XrayManager:
    @staticmethod
    def save_config(config):
        with open('./xray_config.json', 'w') as f:
            json.dump(config, f, indent=2)
    
    @staticmethod
    def start():
        try:
            subprocess.Popen(['./xray', 'run', '-config', './xray_config.json'],
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            time.sleep(3)
            return True
        except: return False

def main():
    if not XrayDownloader.download():
        sys.exit(1)
    
    print("[2/4] Generating keys...")
    pk, pub = KeyGenerator.generate()
    
    print("[3/4] Building config...")
    uid = str(uuid_lib.uuid4())
    sid = uuid_lib.uuid4().hex[:16]
    
    config = XrayConfigBuilder.build(uid, pk, sid, PORT)
    XrayManager.save_config(config)
    
    print("[4/4] Starting Xray...")
    if not XrayManager.start():
        sys.exit(1)
    
    ws_url = VlessURLGenerator.websocket(uid)
    reality_url = VlessURLGenerator.reality(uid, pub, sid)
    
    print(f"""
╔══════════════════════════════════════════════╗
║   ✅ VLESS Ready                             ║
╠══════════════════════════════════════════════╣
║ WebSocket + TLS:                            ║
║ {ws_url}║
╠══════════════════════════════════════════════╣
║ Reality:                                    ║
║ {reality_url}║
╠══════════════════════════════════════════════╣
║ Domain: {DOMAIN}:443                        ║
║ UUID:   {uid}║
║ Path:   /ws/{uid[:8]}...                    ║
╚══════════════════════════════════════════════╝

📱 Copy the WebSocket link above
   Paste into v2rayNG → Import
""")
    
    try:
        while True: time.sleep(3600)
    except KeyboardInterrupt: pass

if __name__ == "__main__":
    main()
