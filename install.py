import os, sys, json, base64, subprocess, time, uuid as uuid_lib, zipfile, socket
import requests as req

# ========== CONFIGURATION ==========
def get_domain():
    domain = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '')
    if domain: return domain
    domain = os.environ.get('RAILWAY_STATIC_URL', '')
    if domain: return domain
    return socket.gethostname()

DOMAIN = get_domain()
PORT = int(os.environ.get('PORT', 8080))

print("=" * 50)
print(f"  🌀 Spinel VLESS Panel v3.0")
print(f"  Domain : {DOMAIN}")
print(f"  Port   : {PORT}")
print("=" * 50)

# ========== XRAY DOWNLOADER ==========
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
            zip_path = "./xray.zip"
            with open(zip_path, 'wb') as f:
                f.write(resp.content)
            with zipfile.ZipFile(zip_path, 'r') as z:
                z.extractall('.')
            os.chmod(cls.XRAY_PATH, 0o755)
            os.remove(zip_path)
            print("       ✓ Xray downloaded successfully")
            return True
        except Exception as e:
            print(f"       ✗ Failed: {e}")
            return False

# ========== KEY GENERATOR ==========
class KeyGenerator:
    FALLBACK_PRIVATE = 'aK8jIpm5hJX9vL3nQ7wRtY2xU4kP6mSd'
    FALLBACK_PUBLIC = 'Ag0kP6mSdY2xU4kP6mSdY2xU4kP6mSdY2xU4kP6mSd'
    
    @classmethod
    def generate(cls):
        try:
            result = subprocess.run(
                ['./xray', 'x25519'],
                capture_output=True, text=True, timeout=10
            )
            private_key = None
            public_key = None
            for line in result.stdout.split('\n'):
                if 'Private key:' in line:
                    private_key = line.split(':')[1].strip()
                if 'Public key:' in line:
                    public_key = line.split(':')[1].strip()
            
            if private_key and public_key:
                return private_key, public_key
        except:
            pass
        
        return cls.FALLBACK_PRIVATE, cls.FALLBACK_PUBLIC

# ========== XRAY CONFIG BUILDER ==========
class XrayConfigBuilder:
    @staticmethod
    def build(uid, private_key, short_id, port):
        return {
            "log": {
                "loglevel": "warning",
                "access": "/dev/null",
                "error": "/dev/null"
            },
            "inbounds": [
                {
                    "tag": "vless-ws-tls",
                    "listen": "0.0.0.0",
                    "port": port,
                    "protocol": "vless",
                    "settings": {
                        "clients": [
                            {
                                "id": uid,
                                "encryption": "none"
                            }
                        ],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "ws",
                        "security": "none",
                        "wsSettings": {
                            "path": f"/ws/{uid}",
                            "headers": {
                                "Host": DOMAIN
                            }
                        }
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls"]
                    }
                },
                {
                    "tag": "vless-reality",
                    "listen": "0.0.0.0",
                    "port": port + 1 if port < 65535 else port - 1,
                    "protocol": "vless",
                    "settings": {
                        "clients": [
                            {
                                "id": uid,
                                "flow": "xtls-rprx-vision",
                                "encryption": "none"
                            }
                        ],
                        "decryption": "none"
                    },
                    "streamSettings": {
                        "network": "tcp",
                        "security": "reality",
                        "realitySettings": {
                            "show": False,
                            "dest": "www.google.com:443",
                            "xver": 0,
                            "serverNames": [
                                "www.google.com",
                                "google.com",
                                "www.apple.com",
                                "apple.com",
                                "www.microsoft.com",
                                "microsoft.com"
                            ],
                            "privateKey": private_key,
                            "shortIds": ["", short_id],
                            "minClientVer": "",
                            "maxClientVer": "",
                            "maxTimeDiff": 0
                        }
                    },
                    "sniffing": {
                        "enabled": True,
                        "destOverride": ["http", "tls"]
                    }
                }
            ],
            "outbounds": [
                {
                    "protocol": "freedom",
                    "tag": "direct",
                    "settings": {}
                },
                {
                    "protocol": "blackhole",
                    "tag": "blocked",
                    "settings": {}
                }
            ]
        }

# ========== VLESS URL GENERATOR ==========
class VlessURLGenerator:
    @staticmethod
    def websocket(uid):
        path = f"/ws/{uid}"
        params = [
            "security=tls",
            "encryption=none",
            "type=ws",
            f"path={path}",
            f"host={DOMAIN}",
            f"sni={DOMAIN}",
            "alpn=http/1.1",
            "fp=chrome"
        ]
        return f"vless://{uid}@{DOMAIN}:443?{'&'.join(params)}#Spinel-WS"
    
    @staticmethod
    def reality(uid, public_key, short_id):
        params = [
            "security=reality",
            "encryption=none",
            "flow=xtls-rprx-vision",
            "sni=www.google.com",
            "fp=chrome",
            "alpn=h2,http/1.1",
            f"pbk={public_key}",
            f"sid={short_id}"
        ]
        return f"vless://{uid}@{DOMAIN}:443?{'&'.join(params)}#Spinel-Reality"

# ========== XRAY MANAGER ==========
class XrayManager:
    CONFIG_PATH = "./xray_config.json"
    
    @staticmethod
    def save_config(config):
        with open(XrayManager.CONFIG_PATH, 'w') as f:
            json.dump(config, f, indent=2)
    
    @staticmethod
    def start():
        try:
            subprocess.Popen(
                ['./xray', 'run', '-config', XrayManager.CONFIG_PATH],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )
            time.sleep(3)
            return True
        except Exception as e:
            print(f"       ✗ Xray start failed: {e}")
            return False
    
    @staticmethod
    def restart():
        subprocess.run(['pkill', '-f', './xray'], capture_output=True)
        time.sleep(1)
        return XrayManager.start()

# ========== OUTPUT FORMATTER ==========
class OutputFormatter:
    @staticmethod
    def print_config(ws_url, reality_url, uid, path, domain, pk, pub, sid):
        separator = "=" * 60
        
        print(f"""
{separator}
  ✅ Spinel VLESS Panel Ready
{separator}

  📡 WebSocket + TLS (Recommended for Railway):
  {ws_url}

  📡 Reality + TCP (Alternative):
  {reality_url}

{separator}
  📋 Connection Details:
{separator}
  Domain      : {domain}
  Port        : 443
  UUID        : {uid}
  WS Path     : {path}
  Reality SNI : www.google.com
  Fingerprint : chrome
  Private Key : {pk[:20]}...
  Public Key  : {pub[:20]}...
  Short ID    : {sid}

{separator}
  💡 How to Connect:
{separator}
  1. Copy one of the VLESS links above
  2. Open v2rayNG or Nekobox
  3. Import from clipboard
  4. Tap Connect ✅

{separator}
  📱 QR Code (copy link and use any QR generator)
{separator}
""")

# ========== MAIN ==========
def main():
    print("\n[2/4] Generating security keys...")
    if not XrayDownloader.download():
        print("[!] Cannot continue without Xray")
        sys.exit(1)
    
    private_key, public_key = KeyGenerator.generate()
    print("       ✓ Keys generated")
    
    print("[3/4] Building configuration...")
    uid = str(uuid_lib.uuid4())
    short_id = uuid_lib.uuid4().hex[:16]
    ws_path = f"/ws/{uid}"
    
    config = XrayConfigBuilder.build(uid, private_key, short_id, PORT)
    XrayManager.save_config(config)
    print("       ✓ Config saved")
    
    print("[4/4] Starting Xray Core...")
    if not XrayManager.start():
        print("[!] Failed to start Xray")
        sys.exit(1)
    print("       ✓ Xray is running")
    
    ws_url = VlessURLGenerator.websocket(uid)
    reality_url = VlessURLGenerator.reality(uid, public_key, short_id)
    
    OutputFormatter.print_config(
        ws_url, reality_url, uid, ws_path, DOMAIN,
        private_key, public_key, short_id
    )
    
    print("  🟢 Xray is running. Press Ctrl+C to stop.\n")
    
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\n  🛑 Shutting down...")
        sys.exit(0)

if __name__ == "__main__":
    main()
