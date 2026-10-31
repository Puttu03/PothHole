"""Export the pothole model to CoreML so the server runs it on the Neural Engine.
Run on the Mac (download_pretrained.py and the training notebook call this for you):

    .venv/bin/python scripts/export_coreml.py
"""
import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
from backend.config import settings  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", default=str(ROOT / "models" / "pothole.pt"))
    ap.add_argument("--imgsz", type=int, default=settings.IMG_SIZE,
                    help="must match the server's POTHOLE_IMG_SIZE (default %(default)s)")
    args = ap.parse_args()

    weights = Path(args.weights)
    if not weights.exists():
        sys.exit(f"Not found: {weights}. Run scripts/download_pretrained.py first.")

    from ultralytics import YOLO
    # settings.IMG_SIZE already follows models/model.json, so the export matches the server
    exported = Path(YOLO(str(weights)).export(format="coreml", imgsz=args.imgsz, half=True))
    target = ROOT / "models" / "pothole.mlpackage"
    if target.exists():
        shutil.rmtree(target)
    shutil.move(str(exported), target)
    print(f"CoreML model ready: {target} (input {args.imgsz} px)\nRestart the server to use it.")


if __name__ == "__main__":
    main()
