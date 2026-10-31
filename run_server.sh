#!/usr/bin/env bash
# Start the Pothole Cloud server.
#   ./run_server.sh            HTTPS on port 8443, reachable by phones on your Wi-Fi
#   ./run_server.sh --http     plain HTTP on http://localhost:8000 (this Mac only)
#   ./run_server.sh --mock     fake detections (test the apps before training)
#   PORT=9443 ./run_server.sh  another port
# Any POTHOLE_* environment variable overrides a setting (see server/config.py).
set -euo pipefail
cd "$(dirname "$0")"
[ -d .venv ] && source .venv/bin/activate

MODE=https
for arg in "$@"; do
  case "$arg" in
    --http) MODE=http ;;
    --mock) export POTHOLE_MOCK=1 ;;
    -h|--help) sed -n '2,7p' "$0"; exit 0 ;;
    *) echo "Unknown option: $arg (try --help)"; exit 1 ;;
  esac
done

if [ "$MODE" = http ]; then
  PORT="${PORT:-8000}"
  echo "Pothole Cloud on http://localhost:$PORT  (camera and GPS only work on localhost over http)"
  exec python -m uvicorn backend.main:app --host 127.0.0.1 --port "$PORT"
fi

if [ ! -f certs/cert.pem ] || [ ! -f certs/key.pem ]; then
  echo "No HTTPS certificate in certs/. Run ./setup.sh first (or use --http for local testing)."
  exit 1
fi
PORT="${PORT:-8443}"
IP="$(cat certs/ip.txt 2>/dev/null || echo localhost)"
echo "Pothole Cloud on https://$IP:$PORT  (and https://localhost:$PORT)"
exec python -m uvicorn backend.main:app --host 0.0.0.0 --port "$PORT" \
  --ssl-keyfile certs/key.pem --ssl-certfile certs/cert.pem
