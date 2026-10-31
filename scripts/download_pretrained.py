"""Download a ready-trained pothole detector into models/pothole.pt, record its settings
in models/model.json, and on a Mac export it to CoreML (models/pothole.mlpackage).

    .venv/bin/python scripts/download_pretrained.py                     # default: potholenet
    .venv/bin/python scripts/download_pretrained.py --preset hrp4k --force
    .venv/bin/python scripts/download_pretrained.py --list
    .venv/bin/python scripts/download_pretrained.py --repo <hf-repo> --file best.pt --imgsz 640 --force

Restart the server afterwards. Try models on your own photos first with scripts/compare_models.py.
"""
import argparse
import json
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
MODELS = ROOT / "models"
sys.path.insert(0, str(ROOT))
from backend.model_catalog import DEFAULT_PRESET, PRESETS, fetch  # noqa: E402


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--preset", default=DEFAULT_PRESET, choices=sorted(PRESETS))
    ap.add_argument("--repo", help="any Hugging Face repo instead of a preset")
    ap.add_argument("--file", default="best.pt", help="weights file in --repo")
    ap.add_argument("--imgsz", type=int, help="input size (default: the preset's)")
    ap.add_argument("--list", action="store_true", help="show the presets and exit")
    ap.add_argument("--no-coreml", action="store_true", help="skip the CoreML export on a Mac")
    ap.add_argument("--force", action="store_true", help="replace an existing models/pothole.pt")
    args = ap.parse_args()

    if args.list:
        for name, p in PRESETS.items():
            star = " (default)" if name == DEFAULT_PRESET else ""
            print(f"{name}{star}\n  {p['repo']}  ·  {p['imgsz']} px  ·  licence {p['licence']}\n  {p['about']}\n")
        return

    preset = {"repo": args.repo, "file": args.file, "imgsz": args.imgsz or 640, "licence": "see model card"} \
        if args.repo else dict(PRESETS[args.preset])
    if args.imgsz:
        preset["imgsz"] = args.imgsz

    MODELS.mkdir(exist_ok=True)
    target = MODELS / "pothole.pt"
    if target.exists() and not args.force:
        print(f"{target} already exists. Use --force to replace it.")
        return

    print(f"Downloading {preset['repo']} ...")
    used_file = fetch(preset["repo"], preset["file"], target)
    print(f"Saved {target} ({target.stat().st_size / 1e6:.0f} MB)")
    stale = MODELS / "pothole.mlpackage"
    if stale.exists():
        shutil.rmtree(stale)          # the old CoreML copy belongs to the previous model

    from ultralytics import YOLO
    model = YOLO(str(target))
    names = dict(model.names)
    print(f"Task: {model.task}  Classes: {names}")
    if not any("pothole" in str(n).lower() for n in names.values()):
        print("Warning: no class is named 'pothole'; set POTHOLE_CLASSES to the class names to keep.")
    meta = {"preset": None if args.repo else args.preset, "repo": preset["repo"], "file": used_file,
            "imgsz": preset["imgsz"], "task": model.task, "classes": {int(k): str(v) for k, v in names.items()},
            "licence": preset["licence"]}
    (MODELS / "model.json").write_text(json.dumps(meta, indent=2))
    print(f"Settings saved to models/model.json (input {preset['imgsz']} px, licence {preset['licence']})")

    if platform.system() == "Darwin" and not args.no_coreml:
        print("Exporting to CoreML for the Neural Engine ...")
        r = subprocess.run([sys.executable, str(ROOT / "scripts" / "export_coreml.py")])
        if r.returncode != 0:
            print("CoreML export failed; the server will use models/pothole.pt on the GPU instead.")
    print("Done. Restart the server to use the model.")


if __name__ == "__main__":
    main()
