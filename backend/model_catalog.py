"""Pretrained pothole models the scripts know how to fetch from Hugging Face.

imgsz is the input size each model was trained at (or the closest size that works
well on the Mac). Metrics are the authors' own numbers on their own test sets, so
they are not comparable with each other; compare on your roads with
scripts/compare_models.py."""

PRESETS = {
    "potholenet": {
        "repo": "Vansh180/PotholeNet-V1",
        "file": "Vision Classification.pt",
        "imgsz": 768,
        "licence": "MIT",
        "about": "YOLO11m, ~23k street photos from Indian cities; classes pothole, road damage, garbage",
    },
    "hrp4k": {
        "repo": "dronefreak/hrp4k-yolov8m",
        "file": "best.pt",
        "imgsz": 1280,
        "licence": "AGPL-3.0",
        "about": "YOLOv8m, HRP4K 4K perspective road photos; class pothole; best on small, distant potholes",
    },
    "pothole-seg": {
        "repo": "keremberke/yolov8m-pothole-segmentation",
        "file": "best.pt",
        "imgsz": 640,
        "licence": "see model card",
        "about": "YOLOv8m segmentation (outlines, not just boxes), Roboflow pothole-segmentation set; mostly close-up potholes",
    },
}
PRESETS["hrp4k-yolo26m"] = {"repo":"dronefreak/hrp4k-yolo26m", "file":"best.pt", "imgsz":1280, "licence":"AGPL-3.0", "about":"YOLO26m trained on HRP4K"}
DEFAULT_PRESET = "hrp4k-yolo26m"


def fetch(repo, filename, dest):
    """Download one weights file to dest. If `filename` isn't in the repo, use its only .pt file."""
    import shutil
    from huggingface_hub import hf_hub_download, list_repo_files

    try:
        path = hf_hub_download(repo_id=repo, filename=filename)
    except Exception:
        pts = [f for f in list_repo_files(repo) if f.endswith(".pt")]
        if len(pts) != 1:
            raise SystemExit(f"Can't find '{filename}' in {repo}; .pt files there: {pts or 'none'}")
        filename = pts[0]
        path = hf_hub_download(repo_id=repo, filename=filename)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(path, dest)
    return filename
