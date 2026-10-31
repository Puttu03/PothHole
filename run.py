"""Start RoadPlotter with hotspot/LAN access and an optional HTTPS tunnel."""
import argparse
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
PYTHON = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')

def local_ip():
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.connect(('192.0.2.1', 80))
            return sock.getsockname()[0]
    except OSError:
        return 'YOUR_COMPUTER_IP'

def main():
    if PYTHON.exists() and Path(sys.prefix).resolve() != (ROOT / '.venv').resolve():
        os.execv(str(PYTHON), [str(PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])
    parser = argparse.ArgumentParser()
    parser.add_argument('--host', default='0.0.0.0')
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--cert')
    parser.add_argument('--key')
    parser.add_argument('--public', action='store_true', help='Use an installed cloudflared to create a temporary public HTTPS URL')
    args = parser.parse_args()
    if bool(args.cert) != bool(args.key):
        parser.error('Supply both --cert and --key')
    if args.public and args.cert:
        parser.error('For --public, omit --cert and --key; the tunnel provides HTTPS')
    if args.public and not shutil.which('cloudflared'):
        parser.error('Install cloudflared first, then run python run.py --public')
    os.chdir(ROOT)
    scheme = 'https' if args.cert else 'http'
    print('\nComputer: '+scheme+'://localhost:'+str(args.port), flush=True)
    if args.host not in ('127.0.0.1','localhost','::1'):
        base = scheme+'://'+local_ip()+':'+str(args.port)
        print('Phone connected to the same Wi-Fi/hotspot: '+base+'/drive', flush=True)
        print('Scanner: '+base+'/scanner', flush=True)
    print('Phone GPS/camera need HTTPS. HTTP local links are for browsing.', flush=True)
    tunnel = None
    if args.public:
        print('Starting a temporary HTTPS tunnel. Use the trycloudflare.com URL printed below, adding /drive.', flush=True)
        print('The public URL exposes the whole prototype, including model-management routes. Keep the URL private; stop with Ctrl+C.', flush=True)
        tunnel = subprocess.Popen(['cloudflared','tunnel','--url','http://127.0.0.1:'+str(args.port)])
    try:
        import uvicorn
        uvicorn.run('backend.main:app', host=args.host, port=args.port,
                    ssl_certfile=args.cert, ssl_keyfile=args.key)
    finally:
        if tunnel is not None:
            tunnel.terminate()
            try: tunnel.wait(timeout=5)
            except subprocess.TimeoutExpired:
                tunnel.kill(); tunnel.wait()

if __name__ == '__main__':
    main()
