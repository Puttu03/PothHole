#!/usr/bin/env bash
# One-time setup for Pothole Cloud on a Mac (also works on Linux).
#   ./setup.sh               full setup
#   SKIP_INSTALL=1 ./setup.sh   redo folders, database and certificate only
set -euo pipefail
cd "$(dirname "$0")"

say()  { printf '\n\033[1;33m==> %s\033[0m\n' "$*"; }
warn() { printf '\033[0;33m    %s\033[0m\n' "$*"; }

# ---------- Python ----------
PYTHON="${PYTHON:-}"
if [ -z "$PYTHON" ]; then
  for p in python3.12 python3.11 python3.10 python3; do
    if command -v "$p" >/dev/null 2>&1; then PYTHON="$p"; break; fi
  done
fi
[ -n "$PYTHON" ] || { echo "Python 3.10+ not found. On a Mac: brew install python@3.12"; exit 1; }
"$PYTHON" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 10) else 1)' \
  || { echo "$PYTHON is too old; need Python 3.10 or newer (brew install python@3.12)"; exit 1; }

if [ "${SKIP_INSTALL:-0}" != "1" ]; then
  say "Creating virtual environment (.venv) with $("$PYTHON" --version)"
  "$PYTHON" -m venv .venv
  # shellcheck disable=SC1091
  source .venv/bin/activate
  python -m pip install --upgrade pip wheel >/dev/null
  say "Installing packages (first time takes a few minutes: PyTorch is large)"
  python -m pip install -r requirements.txt
else
  [ -d .venv ] && source .venv/bin/activate || true
fi
PY="$(command -v python || command -v "$PYTHON")"

# ---------- folders + database ----------
say "Creating folders and the SQLite database"
mkdir -p data/photos data/runs data/training/raw models certs
"$PY" -m server.db init

# ---------- HTTPS certificate (phones only allow camera + GPS on https) ----------
LAN_IP=""
if command -v ipconfig >/dev/null 2>&1; then   # macOS
  LAN_IP="$(ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || true)"
fi
if [ -z "$LAN_IP" ] && command -v hostname >/dev/null 2>&1; then
  LAN_IP="$(hostname -I 2>/dev/null | awk '{print $1}' || true)"
fi
LAN_IP="${LAN_IP:-127.0.0.1}"

if [ ! -f certs/cert.pem ] || ! grep -q "$LAN_IP" certs/ip.txt 2>/dev/null; then
  say "Making a self-signed HTTPS certificate for localhost and $LAN_IP"
  cat > certs/openssl.cnf <<EOF
[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = pothole-cloud
[v3]
subjectAltName = DNS:localhost, IP:127.0.0.1, IP:$LAN_IP
basicConstraints = CA:FALSE
keyUsage = digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
EOF
  openssl req -x509 -newkey rsa:2048 -nodes -sha256 -days 825 \
    -keyout certs/key.pem -out certs/cert.pem -config certs/openssl.cnf 2>/dev/null
  echo "$LAN_IP" > certs/ip.txt
else
  say "HTTPS certificate already exists for $LAN_IP"
fi

# ---------- local SLM ----------
SLM_MODEL="${POTHOLE_SLM_MODEL:-qwen3-vl:4b}"
say "Local SLM ($SLM_MODEL via Ollama)"
if command -v ollama >/dev/null 2>&1; then
  if ollama list >/dev/null 2>&1; then
    ollama pull "$SLM_MODEL" || warn "Could not pull $SLM_MODEL; post-processing will use the size rule until it is available."
  else
    warn "Ollama is installed but not running. Start it (open the Ollama app, or: ollama serve), then: ollama pull $SLM_MODEL"
  fi
else
  warn "Ollama not found. Install it (brew install ollama, or ollama.com), then: ollama pull $SLM_MODEL"
  warn "Until then, post-processing scores potholes with a simple size rule."
fi

# ---------- detection model ----------
say "Detection model"
if [ -e models/pothole.mlpackage ] || [ -e models/pothole.pt ]; then
  echo "    Found: $(ls -d models/pothole.* | tr '\n' ' ')"
elif [ "${SKIP_MODEL:-0}" = "1" ]; then
  warn "Skipped (SKIP_MODEL=1). The server runs in MOCK mode until models/pothole.pt exists."
else
  echo "    Downloading the pretrained pothole model (PotholeNet: YOLO11m, Indian roads, about 40 MB, MIT)"
  "$PY" scripts/download_pretrained.py \
    || warn "Download failed. Run later: .venv/bin/python scripts/download_pretrained.py (server uses MOCK mode until then)"
fi

chmod +x run_server.sh 2>/dev/null || true
say "Done. Next:"
cat <<EOF
    ./run_server.sh                    start the server
    Phones on the same Wi-Fi open:     https://$LAN_IP:8443
    (accept the certificate warning once; it is your own self-signed certificate)

    Try it without real data:          .venv/bin/python scripts/seed_demo.py --lat <your lat> --lon <your lon>
                                       then press "Run post-processing" on the home page
EOF
