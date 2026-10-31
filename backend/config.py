"""Central settings. Every value can be overridden with an environment variable
of the same name prefixed with POTHOLE_ (e.g. POTHOLE_CONF_THRESHOLD=0.5)."""
import json
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _model_meta():
    """models/model.json, written by scripts/download_pretrained.py: imgsz, task, source."""
    try:
        return json.loads((ROOT / "models" / "model.json").read_text())
    except (OSError, ValueError):
        return {}


MODEL_META = _model_meta()


def _env(name, default, cast=str):
    raw = os.environ.get(f"POTHOLE_{name}")
    if raw is None:
        return default
    if cast is bool:
        return raw.lower() in ("1", "true", "yes", "on")
    return cast(raw)


def _saved_qwen():
    try:
        value=(ROOT/'models/active_qwen.txt').read_text().strip()
        return value or 'qwen3.5:4b-q4_K_M'
    except OSError:
        return 'qwen3.5:4b-q4_K_M'

class Settings:
    # --- paths ---
    DATA_DIR = Path(_env("DATA_DIR", str(ROOT / "data")))
    DB_PATH = Path(_env("DB_PATH", str(ROOT / "data" / "pothole.db")))
    PHOTOS_DIR = Path(_env("PHOTOS_DIR", str(ROOT / "data" / "photos")))
    WEB_DIR = ROOT / "frontend"
    NOTEBOOK_DIR = ROOT / "notebooks"
    RUNS_DIR = ROOT / "data" / "runs"

    # --- detection model ---
    # First existing file wins. CoreML (.mlpackage) is fastest on Apple Silicon.
    # setup.sh downloads a pretrained pothole model into models/pothole.pt (see model_catalog.py)
    MODEL_CANDIDATES = [
        _env("MODEL_PATH", ""),
        str(ROOT / "models" / "pothole.mlpackage"),
        str(ROOT / "models" / "pothole.pt"),
    ]
    MOCK_DETECTOR = _env("MOCK", False, bool)   # fake detections for UI testing
    CONF_THRESHOLD = _env("CONF_THRESHOLD", 0.30, float)
    # input size the model was trained for (from models/model.json); override with POTHOLE_IMG_SIZE
    IMG_SIZE = _env("IMG_SIZE", MODEL_META.get("imgsz", 1280), int)
    MODEL_TASK = MODEL_META.get("task", "detect")
    # which of the model's classes count as potholes: comma-separated name fragments.
    # e.g. POTHOLE_CLASSES=pothole,road damage to also keep PotholeNet's "road damage" class
    CLASSES = [c.strip().lower() for c in _env("CLASSES", "pothole,longitudinal_crack,transverse_crack,alligator_crack,road_damage").split(",") if c.strip()]

    # --- camera defaults (scanner app can override per device) ---
    DEFAULT_CAMERA_HEIGHT_M = _env("CAMERA_HEIGHT_M", 1.2, float)
    DEFAULT_CAMERA_TILT_DEG = _env("CAMERA_TILT_DEG", 8.0, float)
    DEFAULT_HFOV_DEG = _env("HFOV_DEG", 66.0, float)

    # --- post-processing ---
    MERGE_RADIUS_M = _env("MERGE_RADIUS_M", 5.0, float)
    MAX_DETECTION_DIST_M = _env("MAX_DETECTION_DIST_M", 25.0, float)
    GONE_REPORTS_TO_CLOSE = _env("GONE_REPORTS_TO_CLOSE", 2, int)

    # --- local SLM (Ollama) ---
    OLLAMA_URL = _env("OLLAMA_URL", "http://localhost:11434")
    SLM_MODEL = _env("SLM_MODEL", _saved_qwen())

    # --- routing ---
    OSRM_URL = _env("OSRM_URL", "https://router.project-osrm.org")
    ROUTE_BUFFER_M = _env("ROUTE_BUFFER_M", 15.0, float)

    @property
    def model_path(self):
        selected = ROOT / 'models' / 'active_model.txt'
        if not os.environ.get('POTHOLE_MODEL_PATH') and selected.exists():
            name = selected.read_text().strip()
            target = ROOT / 'models' / name
            if target.parent == ROOT / 'models' and target.is_file() and target.suffix == '.pt':
                return target
        if not os.environ.get('POTHOLE_MODEL_PATH') and (ROOT/'models/road_damage.pt').is_file():
            return ROOT/'models/road_damage.pt'
        for p in self.MODEL_CANDIDATES:
            if p and Path(p).exists():
                return Path(p)
        return None


settings = Settings()
