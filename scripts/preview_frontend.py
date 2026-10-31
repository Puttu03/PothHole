"""Preview the web apps with fake data. Needs nothing but the Python that ships with macOS:
no packages, no model, no database.

    python3 scripts/preview_frontend.py                 http://localhost:8000 (this Mac)
    python3 scripts/preview_frontend.py --https         https://<mac-ip>:8443 (phones on your Wi-Fi)
    python3 scripts/preview_frontend.py --lat 12.97 --lon 77.59 --heading 80

Then open:
    /             home page
    /scanner      camera + fake detections
    /driver?sim   a test car drives the demo road; watch the 100 m countdown
    /driver       real GPS on the phone, with the demo potholes
"""
import argparse
import json
import math
import mimetypes
import socket
import ssl
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parent.parent
WEB = ROOT / "frontend"
sys.path.insert(0, str(ROOT))
from backend import geo  # noqa: E402  (pure Python, no packages)

POTHOLES = []
GONE = {}
JOB = {"state": "idle", "started": None, "finished": None, "output": None, "error": None}
CONFIG = {}

# (metres along the demo road, metres right of centre, severity, ride score, width m, description)
DEMO = [
    (60, -0.8, "High", 6.9, 0.7, "Deep pothole about 70 cm wide in the left wheel path."),
    (140, 0.6, "Medium", 4.2, 0.35, "Pothole about 35 cm wide in the right wheel path, broken edges."),
    (230, 0.0, "Critical", 8.6, 1.1, "Large water-filled pothole across the lane centre, over 1 m wide."),
    (320, -0.9, "Low", 2.1, 0.25, "Small shallow pothole near the left wheel path."),
]
OFF_ROUTE = [(150, 40, "Medium", 4.8, 0.4), (90, -60, "High", 6.2, 0.6), (300, 80, "Low", 2.5, 0.3)]


def build_demo(lat, lon, heading):
    POTHOLES.clear()
    now = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())
    items = [(a, s, sev, sc, w, d) for a, s, sev, sc, w, d in DEMO]
    items += [(a, s, sev, sc, w, "Pothole on a side street.") for a, s, sev, sc, w in OFF_ROUTE]
    for i, (along, side, sev, score, width, desc) in enumerate(items, start=1):
        plat, plon = geo.offset_latlon(lat, lon, along, side, heading)
        POTHOLES.append({
            "id": i, "lat": plat, "lon": plon, "loc_accuracy_m": 2.5, "severity": sev, "ride_score": score,
            "width_m": width, "area_m2": round(math.pi / 4 * width * width * 0.7, 3), "surface": None,
            "lane_position": geo.lane_position(side), "description": desc, "times_seen": 6,
            "first_seen": now, "last_seen": now, "status": "open",
            "photo_url": f"/media/demo/{i}.svg", "full_photo_url": f"/media/demo/{i}.svg",
        })
    CONFIG.update({
        "detector_mode": "preview", "camera_height_m": 1.2, "camera_tilt_deg": 8.0, "hfov_deg": 66.0,
        "demo_start": [lat, lon], "demo_end": list(geo.offset_latlon(lat, lon, 400, 0, heading)),
    })


def photo_svg(pid):
    p = next((x for x in POTHOLES if x["id"] == pid), None)
    w = 60 + 110 * min(1.0, (p["width_m"] if p else 0.4))
    water = p and p["severity"] == "Critical"
    hole = "#3d5566" if water else "#2a2826"
    return f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 240 160">
<rect width="240" height="160" fill="#575a5c"/>
<g fill="#646769">{''.join(f'<circle cx="{(i * 37) % 240}" cy="{(i * 53) % 160}" r="{1 + i % 3}"/>' for i in range(60))}</g>
<ellipse cx="120" cy="92" rx="{w / 2 + 6}" ry="{w / 6 + 6}" fill="#6d6964"/>
<ellipse cx="120" cy="92" rx="{w / 2}" ry="{w / 6}" fill="{hole}"/>
<text x="10" y="150" font-family="sans-serif" font-size="11" fill="#c9cdd0">preview photo #{pid}</text></svg>"""


def route_between(a, b, n=80):
    coords = [[a[0] + (b[0] - a[0]) * i / n, a[1] + (b[1] - a[1]) * i / n] for i in range(n + 1)]
    hits = []
    for p in POTHOLES:
        if p["status"] != "open":
            continue
        off, along = geo.locate_on_route(coords, p["lat"], p["lon"])
        if off <= 15:
            hits.append({**p, "route_offset_m": round(off, 1), "along_route_m": round(along, 1)})
    hits.sort(key=lambda p: p["along_route_m"])
    length = geo.haversine_m(a[0], a[1], b[0], b[1])
    return {"coords": coords, "distance_m": length, "duration_s": length / 11, "count": len(hits),
            "severe_count": sum(p["severity"] in ("High", "Critical") for p in hits), "potholes": hits}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        sys.stderr.write("  %s %s\n" % (self.command, self.path))

    def send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else (json.dumps(body) if ctype == "application/json" else body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def file(self, path):
        if not path.is_file():
            return self.send(404, {"detail": "not found"})
        self.send(200, path.read_bytes(), mimetypes.guess_type(path.name)[0] or "application/octet-stream")

    def do_GET(self):
        url = urlparse(self.path)
        q = {k: v[0] for k, v in parse_qs(url.query).items()}
        path = url.path
        if path == "/":
            return self.file(WEB / "index.html")
        if path in ("/scanner", "/driver"):
            return self.file(WEB / f"{path[1:]}.html")
        if path.startswith("/static/"):
            target = (WEB / path[len("/static/"):]).resolve()
            return self.file(target) if str(target).startswith(str(WEB)) else self.send(403, {"detail": "no"})
        if path.startswith("/media/demo/"):
            try:
                return self.send(200, photo_svg(int(Path(path).stem)), "image/svg+xml")
            except ValueError:
                return self.send(404, {"detail": "not found"})
        if path == "/api/config":
            return self.send(200, CONFIG)
        if path == "/getpdata":
            rows = [p for p in POTHOLES if p["status"] == "open"]
            return self.send(200, {"count": len(rows), "potholes": rows})
        if path == "/route-potholes":
            try:
                a = [float(x) for x in q["start"].split(",")]
                b = [float(x) for x in q["end"].split(",")]
            except (KeyError, ValueError):
                return self.send(400, {"detail": "start and end must be 'lat,lon'"})
            return self.send(200, route_between(a, b))
        if path == "/process/status":
            return self.send(200, {**JOB, "unprocessed_detections": 0 if JOB["state"] == "done" else 12})
        self.send(404, {"detail": "not found"})

    def do_POST(self):
        path = urlparse(self.path).path
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else b""
        if path == "/process":
            JOB.update(state="running", started=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()), error=None)

            def finish():
                time.sleep(3)
                JOB.update(state="done", finished=time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime()))
            threading.Thread(target=finish, daemon=True).start()
            return self.send(200, {"started": True, **JOB})
        if path == "/feedback":
            try:
                fb = json.loads(body or b"{}")
                p = next(x for x in POTHOLES if x["id"] == int(fb["pothole_id"]))
            except (StopIteration, KeyError, ValueError):
                return self.send(404, {"detail": "Unknown pothole"})
            if fb.get("kind") == "gone":
                GONE[p["id"]] = GONE.get(p["id"], 0) + 1
                if GONE[p["id"]] >= 2:
                    p["status"] = "repaired"
            else:
                GONE[p["id"]] = 0
                p["status"] = "open"
            return self.send(200, {"pothole_id": p["id"], "status": p["status"]})
        self.send(404, {"detail": "not found"})


def lan_ip():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("10.255.255.255", 1))   # no packets are sent
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


def ensure_cert(ip):
    certs = ROOT / "certs"
    cert, key = certs / "cert.pem", certs / "key.pem"
    if cert.exists() and key.exists():
        return cert, key
    certs.mkdir(exist_ok=True)
    cnf = certs / "openssl.cnf"
    cnf.write_text(f"""[req]
distinguished_name = dn
x509_extensions = v3
prompt = no
[dn]
CN = pothole-cloud
[v3]
subjectAltName = DNS:localhost, IP:127.0.0.1, IP:{ip}
basicConstraints = CA:FALSE
extendedKeyUsage = serverAuth
""")
    subprocess.run(["openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "825",
                    "-keyout", str(key), "-out", str(cert), "-config", str(cnf)],
                   check=True, capture_output=True)
    (certs / "ip.txt").write_text(ip + "\n")
    return cert, key


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--lat", type=float, default=12.9716)
    ap.add_argument("--lon", type=float, default=77.5946)
    ap.add_argument("--heading", type=float, default=80.0, help="demo road direction, degrees from north")
    ap.add_argument("--https", action="store_true", help="serve HTTPS on your Wi-Fi so phones can use camera + GPS")
    ap.add_argument("--port", type=int)
    args = ap.parse_args()

    build_demo(args.lat, args.lon, args.heading)
    if args.https:
        ip = lan_ip()
        port = args.port or 8443
        server = ThreadingHTTPServer(("0.0.0.0", port), Handler)
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(*ensure_cert(ip))
        server.socket = ctx.wrap_socket(server.socket, server_side=True)
        base = f"https://{ip}:{port}"
        note = "Accept the certificate warning once on each phone."
    else:
        port = args.port or 8000
        server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
        base = f"http://localhost:{port}"
        note = "This Mac only. Use --https to open it on a phone."
    print(f"""
Pothole Cloud preview (fake data, no model)  {note}
  Home             {base}/
  Scanner          {base}/scanner
  Simulated drive  {base}/driver?sim
  Driver (GPS)     {base}/driver
Demo road starts at {args.lat}, {args.lon}, heading {args.heading:g}°. Ctrl+C to stop.
""")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


if __name__ == "__main__":
    main()
