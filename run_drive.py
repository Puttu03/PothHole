"""Publish the main project's processed records and launch its Drive service."""
import argparse
import shutil
import subprocess
from pathlib import Path

from backend.drive_publish import publish

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public", action="store_true", help="Start a temporary HTTPS tunnel")
    args = parser.parse_args()
    if not shutil.which("docker"):
        parser.exit(1, "Start Docker Desktop before launching Drive.\n")
    root = Path(__file__).resolve().parent
    publish()
    compose = ["docker", "compose"]
    if args.public:
        compose += ["--profile", "public"]
    services = ["drive", "tunnel"] if args.public else ["drive"]
    subprocess.run(compose + ["up", "--build", "-d", *services], cwd=root, check=True)
    print("Local Drive: http://localhost:8080/drive", flush=True)
    if args.public:
        print("Open the HTTPS address from the tunnel log with /drive appended.", flush=True)
        try:
            subprocess.run(compose + ["logs", "-f", "tunnel"], cwd=root, check=True)
        except KeyboardInterrupt:
            pass

if __name__ == "__main__":
    main()
