import os, sys, json, subprocess, time, uuid, socket
import requests as req

DOMAIN = os.environ.get('RAILWAY_PUBLIC_DOMAIN', '') or os.environ.get('RAILWAY_STATIC_URL', '') or socket.gethostname()
PORT = int(os.environ.get('PORT', 8080))

current_uid = str(uuid.uuid4())
current_path = f"/ws/{current_uid}"

print(f"Domain: {DOMAIN}")
print(f"Port: {PORT}")
print(f"UUID: {current_uid}")
print(f"Path: {current_path}")

def download_xray():
    if os.path.exists('./xray') and os.path.getsize('./xray') > 10000000:
        return True
    print("Downloading Xray...")
    try:
        r = req.get("https://github.com/XTLS/Xray-core/releases/download/v1.8.21/Xray-linux-64.zip", timeout=120)
        with open('xray.zip', 'wb') as f: f.write(r.content)
        import zipfile
        with zipfile.ZipFile('xray.zip', 'r') as z: z.extractall('.')
        os.chmod('./xray', 0o755)
        os.remove('xray.zip')
        print("Downloaded")
        return True
    except Exception as e:
        print(f"Error: {e}")
        return False

def build_config():
    return {
        "log": {"loglevel": "warning"},
        "inbounds": [{
            "listen": "0.0.0.0",
            "port": PORT,
            "protocol": "vless",
            "settings": {
                "clients": [{"id": current_uid}],
                "decryption": "none"
            },
            "streamSettings": {
                "network": "ws",
                "security": "none",
                "wsSettings": {"path": current_path}
            }
        }],
        "outbounds": [{
            "protocol": "freedom",
            "tag": "direct"
        }]
    }

def start_xray():
    config = build_config()
    with open('xray_config.json', 'w') as f:
        json.dump(config, f, indent=2)
    
    print("Starting Xray...")
    proc = subprocess.Popen(
        ['./xray', 'run', '-config', 'xray_config.json'],
        stdout=sys.stdout,
        stderr=sys.stderr
    )
    time.sleep(3)
    
    if proc.poll() is not None:
        print(f"Xray exited: {proc.returncode}")
        return False
    
    print(f"Xray running on 0.0.0.0:{PORT}")
    return True

if __name__ == '__main__':
    if not download_xray():
        sys.exit(1)
    
    if not start_xray():
        sys.exit(1)
    
    url = f"vless://{current_uid}@{DOMAIN}:443?security=tls&encryption=none&type=ws&path={current_path}&host={DOMAIN}&sni={DOMAIN}&fp=chrome#Spinel"
    
    print(f"""
╔══════════════════════════════════════════╗
║   🌀 Spinel VLESS Ready                 ║
╠══════════════════════════════════════════╣
║ {url}║
╚══════════════════════════════════════════╝

Domain: {DOMAIN}
Port: 443
Security: TLS
UUID: {current_uid}
Path: {current_path}
SNI: {DOMAIN}
Fingerprint: chrome

Copy → v2rayNG → Import from Clipboard
""")
    
    try:
        while True:
            time.sleep(3600)
    except KeyboardInterrupt:
        print("\nDone")
