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
