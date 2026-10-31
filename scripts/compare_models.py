"""Run several pothole models on YOUR photos and put the results side by side.
Downloads each candidate into models/candidates/ (your active model is not touched).

    .venv/bin/python scripts/compare_models.py --images ~/Desktop/road_photos
    .venv/bin/python scripts/compare_models.py --images data/photos/2026-10-24 --conf 0.15
    .venv/bin/python scripts/compare_models.py --images pics --models potholenet hrp4k models/my_own.pt

Output in data/compare/: one side-by-side image per photo, plus summary.csv.
Boxes: orange = pothole, yellow = other road damage, grey = anything else.
Then switch with:  .venv/bin/python scripts/download_pretrained.py --preset <name> --force
"""
import argparse
import csv
import sys
import time
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.model_catalog import PRESETS, fetch  # noqa: E402

IMG_EXT = {".jpg", ".jpeg", ".png", ".webp", ".bmp"}
PANEL_W = 420


def colour(name):
    n = str(name).lower()
    if "pothole" in n:
        return (255, 122, 26)
    if "damage" in n or "crack" in n:
        return (242, 194, 48)
    return (160, 170, 178)


def font(size):
    for f in ("/System/Library/Fonts/Supplemental/Arial.ttf", "/Library/Fonts/Arial.ttf",
              "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"):
        try:
            return ImageFont.truetype(f, size)
        except OSError:
            pass
    return ImageFont.load_default()


def panel(img, dets, title):
    """Scale to PANEL_W wide, draw boxes, add a title bar."""
    s = PANEL_W / img.width
    p = img.resize((PANEL_W, round(img.height * s)))
    d = ImageDraw.Draw(p)
    small, big = font(14), font(17)
    for det in dets:
        x1, y1, x2, y2 = (v * s for v in det["xyxy"])
        c = colour(det["name"])
        d.rectangle([x1, y1, x2, y2], outline=c, width=3)
        label = f"{det['name']} {det['conf']:.0%}"
        ty = max(0, y1 - 18)
        d.rectangle([x1, ty, x1 + d.textlength(label, font=small) + 8, ty + 18], fill=c)
        d.text((x1 + 3, ty + 1), label, fill=(20, 25, 29), font=small)
    out = Image.new("RGB", (PANEL_W, p.height + 34), (38, 50, 59))
    out.paste(p, (0, 34))
    ImageDraw.Draw(out).text((10, 7), title, fill=(238, 241, 243), font=big)
    return out


def side_by_side(panels, gap=8):
    h = max(p.height for p in panels)
    sheet = Image.new("RGB", (sum(p.width for p in panels) + gap * (len(panels) - 1), h), (255, 255, 255))
    x = 0
    for p in panels:
        sheet.paste(p, (x, 0))
        x += p.width + gap
    return sheet


def load_candidates(names):
    from ultralytics import YOLO
    out = []
    for name in names:
        if name in PRESETS:
            p = PRESETS[name]
            dest = ROOT / "models" / "candidates" / f"{name}.pt"
            if not dest.exists():
                print(f"Downloading {name} ({p['repo']}) ...")
                fetch(p["repo"], p["file"], dest)
            out.append((name, YOLO(str(dest)), p["imgsz"]))
        elif Path(name).exists():
            out.append((Path(name).stem, YOLO(name), 640))
        else:
            raise SystemExit(f"Unknown model '{name}'. Presets: {', '.join(PRESETS)} or a path to a .pt file")
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--images", required=True, help="folder of your road photos")
    ap.add_argument("--models", nargs="+", default=list(PRESETS), help="presets and/or .pt paths")
    ap.add_argument("--conf", type=float, default=0.25, help="confidence threshold (try 0.15 to see near-misses)")
    ap.add_argument("--out", default=str(ROOT / "data" / "compare"))
    args = ap.parse_args()

    images = sorted(p for p in Path(args.images).expanduser().rglob("*") if p.suffix.lower() in IMG_EXT)
    if not images:
        raise SystemExit(f"No images found in {args.images}")
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    models = load_candidates(args.models)

    import torch
    device = "mps" if torch.backends.mps.is_available() else ("cuda" if torch.cuda.is_available() else "cpu")
    rows, totals = [], {m[0]: {"potholes": 0, "images_hit": 0, "ms": 0.0} for m in models}

    for img_path in images:
        img = ImageOps.exif_transpose(Image.open(img_path)).convert("RGB")   # phone photos: respect rotation
        panels, row = [], {"image": img_path.name}
        for name, model, imgsz in models:
            t0 = time.perf_counter()
            r = model.predict(img, imgsz=imgsz, conf=args.conf, device=device, verbose=False)[0]
            ms = (time.perf_counter() - t0) * 1000
            dets = [{"xyxy": b, "conf": c, "name": model.names[int(k)]}
                    for b, c, k in zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist())]
            ph = [d for d in dets if "pothole" in str(d["name"]).lower()]
            best = max((d["conf"] for d in ph), default=0)
            row[name] = f"{len(ph)} pothole(s), best {best:.0%}" + (f", +{len(dets) - len(ph)} other" if len(dets) > len(ph) else "")
            totals[name]["potholes"] += len(ph)
            totals[name]["images_hit"] += bool(ph)
            totals[name]["ms"] += ms
            panels.append(panel(img, dets, f"{name}: {len(ph)} pothole(s)"))
        side_by_side(panels).save(out / f"{img_path.stem}_compare.jpg", quality=88)
        rows.append(row)
        print(f"{img_path.name:32s} " + " | ".join(f"{m[0]}: {row[m[0]]}" for m in models))

    with open(out / "summary.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=["image"] + [m[0] for m in models])
        w.writeheader()
        w.writerows(rows)

    print(f"\n{'model':14s} {'photos with a pothole':>22s} {'pothole boxes':>14s} {'ms/photo':>9s}")
    for name, t in totals.items():
        print(f"{name:14s} {t['images_hit']:>14d} of {len(images):<5d} {t['potholes']:>14d} {t['ms'] / len(images):>9.0f}")
    print(f"\nSide-by-side images and summary.csv are in {out}")
    print("More boxes isn't automatically better: open the images and check they're on real potholes.")


if __name__ == "__main__":
    main()
