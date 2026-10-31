"""Run the existing application on the local network and print access links."""
from pathlib import Path
import socket,subprocess,sys,argparse
root=Path(__file__).resolve().parent
p=argparse.ArgumentParser();p.add_argument('--port',type=int,default=8000);p.add_argument('--cert');p.add_argument('--key');a=p.parse_args()
if bool(a.cert)!=bool(a.key):p.error('Supply both --cert and --key')
try:
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as sock:
  sock.connect(('192.0.2.1',80));address=sock.getsockname()[0]
except OSError:address='YOUR_COMPUTER_IP'
scheme='https' if a.cert else 'http'
print('Phone on the same Wi-Fi: '+scheme+'://'+address+':'+str(a.port)+'/drive',flush=True)
print('Camera and phone GPS require HTTPS. HTTP supports browsing/search but normally blocks GPS.',flush=True)
print('If multiple network adapters exist, use your active Wi-Fi IPv4 address.',flush=True)
args=[sys.executable,str(root/'run.py'),'--host','0.0.0.0','--port',str(a.port)]
if a.cert:args+=['--cert',a.cert,'--key',a.key]
raise SystemExit(subprocess.call(args,cwd=root))
