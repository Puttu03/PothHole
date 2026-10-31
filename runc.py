"""Start RoadPlotter and a temporary Cloudflare HTTPS tunnel.
Place beside run.py; run: python runc.py
Requires cloudflared installed and project setup completed.
"""
import argparse
import os
from pathlib import Path
import re
import shutil
import socket
import subprocess
import sys
import threading
import time

ROOT = Path(__file__).resolve().parent
URL_PATTERN = re.compile(r'https://[a-zA-Z0-9-]+\.trycloudflare\.com')

def wait_for_server(process, port, timeout):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if process.poll() is not None:
            raise RuntimeError('RoadPlotter stopped during startup. Read the server error above.')
        try:
            with socket.create_connection(('127.0.0.1', port), timeout=1):
                return
        except OSError:
            time.sleep(0.25)
    raise RuntimeError('Server startup timed out. Check the terminal or increase --timeout.')

def stop(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()

def show_tunnel_output(stream, urls):
    try:
        for line in stream:
            match = URL_PATTERN.search(line)
            if match and match.group() not in urls:
                url = match.group()
                urls.append(url)
                print('\n' + '=' * 64, flush=True)
                print('ROADPLOTTER HTTPS LINKS', flush=True)
                print('Website: ' + url, flush=True)
                print('Drive:   ' + url + '/drive', flush=True)
                print('Scanner: ' + url + '/scanner', flush=True)
                print('Models:  ' + url + '/system', flush=True)
                print('Open on your phone and allow location/camera access.', flush=True)
                print('Keep this terminal open. Press Ctrl+C to stop both services.', flush=True)
                print('=' * 64 + '\n', flush=True)
            elif 'ERR' in line or 'error' in line.lower():
                print('[Cloudflare] ' + line.rstrip(), flush=True)
    finally:
        stream.close()

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8000)
    parser.add_argument('--timeout', type=int, default=180, help='Server startup timeout in seconds')
    parser.add_argument('--cloudflared', help='Optional full path to the cloudflared executable')
    args = parser.parse_args()
    if not 1 <= args.port <= 65535:
        parser.error('Port must be between 1 and 65535.')
    run_file = ROOT / 'run.py'
    if not run_file.is_file():
        parser.error('Place runc.py in the project folder beside run.py.')
    binary = args.cloudflared or shutil.which('cloudflared')
    if not binary:
        print('cloudflared is not installed or is not on PATH.\n', flush=True)
        print('Mac:     brew install cloudflared', flush=True)
        print('Windows: winget install --id Cloudflare.cloudflared', flush=True)
        print('\nReopen the terminal after installation, then run python runc.py.', flush=True)
        return 1
    if not Path(binary).is_file() and not shutil.which(binary):
        parser.error('The specified cloudflared executable does not exist.')
    try:
        with socket.create_connection(('127.0.0.1', args.port), timeout=1):
            print('Port ' + str(args.port) + ' is already in use. Stop the old server or use --port 8001.', flush=True)
            return 1
    except OSError:
        pass
    python = ROOT / '.venv' / ('Scripts/python.exe' if os.name == 'nt' else 'bin/python')
    executable = str(python) if python.is_file() else sys.executable
    server = tunnel = None
    thread = None
    try:
        print('Starting RoadPlotter from: ' + str(ROOT), flush=True)
        print('The temporary public URL exposes this prototype, including management pages. Keep it private.', flush=True)
        server = subprocess.Popen([executable, str(run_file), '--host', '127.0.0.1', '--port', str(args.port)], cwd=ROOT)
        wait_for_server(server, args.port, args.timeout)
        print('Server ready. Creating Cloudflare HTTPS link…', flush=True)
        tunnel = subprocess.Popen([binary, 'tunnel', '--url', 'http://127.0.0.1:' + str(args.port)],
                                  cwd=ROOT, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                  text=True, encoding='utf-8', errors='replace', bufsize=1)
        urls = []
        thread = threading.Thread(target=show_tunnel_output, args=(tunnel.stdout, urls), daemon=True)
        thread.start()
        started = time.monotonic()
        warned = False
        while True:
            if server.poll() is not None:
                raise RuntimeError('RoadPlotter stopped. Check its terminal output.')
            if tunnel.poll() is not None:
                raise RuntimeError('Cloudflare Tunnel stopped. Check connectivity and Cloudflare errors above.')
            if not urls and not warned and time.monotonic() - started > 45:
                print('Still waiting for a public URL. Check your internet connection; quick tunnels may be unavailable.', flush=True)
                warned = True
            time.sleep(0.5)
    except KeyboardInterrupt:
        print('\nStopping RoadPlotter and Cloudflare…', flush=True)
        return 0
    except (OSError, RuntimeError) as error:
        print('\nError: ' + str(error), flush=True)
        return 1
    finally:
        stop(tunnel)
        stop(server)
        if thread is not None:
            thread.join(timeout=2)

if __name__ == '__main__':
    raise SystemExit(main())
