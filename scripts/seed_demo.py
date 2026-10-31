"""Fill DB1 with simulated sightings so you can test post-processing and the
driver app before any real scanning.

It places a few potholes along a straight road, "drives" past them several
times with noisy GPS, and writes the frames a dashboard camera would have
seen (synthetic images, boxes where the geometry says they should be).

    python scripts/seed_demo.py --lat 12.9716 --lon 77.5946 --heading 80
Then run the post-process notebook (or POST /process) and open /driver."""
import argparse
import math
import random
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend import db, geo  # noqa: E402
from backend.config import settings  # noqa: E402

W, H = 640, 360
CAM_H, TILT, HFOV = settings.DEFAULT_CAMERA_HEIGHT_M, settings.DEFAULT_CAMERA_TILT_DEG, settings.DEFAULT_HFOV_DEG


def ground_to_pixel(forward, lateral):
    """Inverse of geo.pixel_to_ground."""
    fx = (W / 2) / math.tan(math.radians(HFOV) / 2)
    depression = math.atan2(CAM_H, forward)
    alpha = depression - math.radians(TILT)
    v = H / 2 + fx * math.tan(alpha)
    slant = math.hypot(forward, CAM_H)
    u = W / 2 + lateral * fx / (slant * math.cos(alpha))
    return u, v


def frame(boxes, seed):
    rnd = random.Random(seed)
    img = Image.new("RGB", (W, H), (120, 170, 210))                     # sky
    d = ImageDraw.Draw(img)
    horizon = ground_to_pixel(1000, 0)[1]
    d.rectangle([0, horizon, W, H], fill=(78, 80, 82))                  # asphalt
    for _ in range(400):                                               # texture
        x, y = rnd.uniform(0, W), rnd.uniform(horizon, H)
        g = rnd.randint(65, 95)
        d.point((x, y), fill=(g, g, g))
    for x1, y1, x2, y2 in boxes:
        d.ellipse([x1, y1, x2, y2], fill=(38, 36, 34), outline=(105, 100, 95), width=2)
    return img.filter(ImageFilter.GaussianBlur(0.6))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--lat", type=float, default=12.9716)
    ap.add_argument("--lon", type=float, default=77.5946)
    ap.add_argument("--heading", type=float, default=80.0, help="road direction, degrees from north")
    ap.add_argument("--passes", type=int, default=3)
    ap.add_argument("--gps-noise", type=float, default=3.0, help="metres")
    args = ap.parse_args()

    random.seed(7)
    db.init()
    # potholes: (metres along the road, metres right of the lane centre, width m, length m)
    truth = [(60, -0.8, 0.7, 0.5), (140, 0.6, 0.35, 0.3), (230, 0.0, 1.1, 0.8), (320, -0.9, 0.25, 0.2)]
    out_dir = settings.PHOTOS_DIR / "demo"
    out_dir.mkdir(parents=True, exist_ok=True)

    n = 0
    with db.session() as conn:
        for p in range(args.passes):
            lane_shift = random.uniform(-0.4, 0.4)       # driver not always centred
            for step in range(0, 400, 3):                # a frame every 3 m (~5 fps at 54 km/h)
                boxes, hits = [], []
                for along, lat_off, wid, length in truth:
                    fwd = along - step
                    if not 6 <= fwd <= 20:
                        continue
                    lateral = lat_off - lane_shift
                    u1, v_near = ground_to_pixel(fwd - length / 2, lateral - wid / 2)
                    u2, _ = ground_to_pixel(fwd - length / 2, lateral + wid / 2)
                    _, v_far = ground_to_pixel(fwd + length / 2, lateral)
                    box = (u1, v_far, u2, v_near)
                    if 0 <= u1 and u2 <= W and v_near <= H:
                        boxes.append(box); hits.append(box)
                if not hits:
                    continue
                car_lat, car_lon = geo.offset_latlon(args.lat, args.lon, step, lane_shift, args.heading)
                nlat, nlon = geo.offset_latlon(car_lat, car_lon, random.gauss(0, args.gps_noise),
                                               random.gauss(0, args.gps_noise), args.heading)
                rel = Path("demo") / f"pass{p}_step{step:03d}.jpg"
                frame(boxes, seed=p * 1000 + step).save(settings.PHOTOS_DIR / rel, quality=85)
                for x1, y1, x2, y2 in hits:
                    db.insert_detection(conn, {
                        "captured_at": db.now_iso(), "device_id": "demo", "lat": nlat, "lon": nlon,
                        "gps_accuracy_m": args.gps_noise * 1.5, "heading_deg": args.heading + random.gauss(0, 2),
                        "speed_kmh": 54, "camera_height_m": CAM_H, "camera_tilt_deg": TILT, "hfov_deg": HFOV,
                        "img_w": W, "img_h": H, "photo_path": str(rel),
                        "x1": x1, "y1": y1, "x2": x2, "y2": y2, "confidence": round(random.uniform(0.55, 0.92), 2),
                    })
                    n += 1

    print(f"Inserted {n} demo detections. True pothole locations:")
    for along, lat_off, *_ in truth:
        print("  ", tuple(round(v, 6) for v in geo.offset_latlon(args.lat, args.lon, along, lat_off, args.heading)))


if __name__ == "__main__":
    main()
