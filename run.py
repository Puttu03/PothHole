"""Launch the RoadPlotter operator app and Docker Drive."""
import argparse
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import threading
import time
from urllib.request import urlopen

ROOT = Path(__file__).resolve().parent

def docker_ready():
    if not shutil.which("docker"):
        print("Install Docker Desktop to enable Docker Drive.", flush=True)
        return False
    def reachable():
        try:
            return subprocess.run(["docker", "info"], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL, timeout=5).returncode == 0
        except subprocess.TimeoutExpired:
            return False
    if reachable():
        return True
    if sys.platform == "darwin":
        subprocess.run(["open", "-a", "Docker"], check=False)
        print("Waiting for Docker Desktop to start…", flush=True)
        deadline = time.monotonic() + 90
        while time.monotonic() < deadline:
            if reachable():
                return True
            time.sleep(2)
    print("Docker engine unavailable. Start Docker Desktop and rerun to enable Docker Drive.", flush=True)
    return False

def start_drive(public, stop):
    try:
        if not docker_ready() or stop.is_set():
            return
        from backend.drive_publish import publish
        publish()
        services = ["drive", "tunnel"] if public else ["drive"]
        subprocess.run(["docker", "compose", "up", "--build", "-d", *services],
                       cwd=ROOT, check=True)
        local = "http://localhost:8080"
        deadline = time.monotonic() + 90
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                with urlopen(local + "/health", timeout=2):
                    break
            except OSError:
                stop.wait(2)
        else:
            if not stop.is_set():
                print("Drive did not become ready. Check docker compose logs drive.", flush=True)
            return
        print(f"Local Docker Drive: {local}/drive", flush=True)
        if public:
            deadline = time.monotonic() + 90
            while not stop.is_set() and time.monotonic() < deadline:
                logs = subprocess.run(["docker", "compose", "logs", "--no-color", "tunnel"],
                                      cwd=ROOT, capture_output=True, text=True, timeout=10)
                urls = re.findall(r"https://[a-zA-Z0-9-]+\.trycloudflare\.com", logs.stdout)
                if urls:
                    print(f"Cloudflare Drive: {urls[-1]}/drive", flush=True)
                    return
                stop.wait(2)
            if not stop.is_set():
                print("Cloudflare link unavailable. Check docker compose logs tunnel.", flush=True)
    except Exception as exc:
        print(f"Docker Drive startup failed: {exc}", flush=True)

def main(public=False):
    python = ROOT / ".venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if python.exists() and Path(sys.prefix).resolve() != (ROOT / ".venv").resolve():
        entry = ROOT / ("runc.py" if public else "run.py")
        os.execv(str(python), [str(python), str(entry), *sys.argv[1:]])
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--cert")
    parser.add_argument("--key")
    args = parser.parse_args()

    import uvicorn
    from backend.main import app

    stop = threading.Event()
    original_lifespan = app.router.lifespan_context
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(application):
        async with original_lifespan(application):
            scheme = "https" if args.cert and args.key else "http"
            print(f"Local RoadPlotter: {scheme}://localhost:{args.port}", flush=True)
            threading.Thread(target=start_drive, args=(public, stop), daemon=True).start()
            try:
                yield
            finally:
                stop.set()

    app.router.lifespan_context = lifespan
    uvicorn.run(app, host=args.host, port=args.port,
                ssl_certfile=args.cert, ssl_keyfile=args.key)

if __name__ == "__main__":
    main()
