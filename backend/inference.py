"""Inference engine. Loads the pothole model (a pretrained one from model_catalog.py, or your own)
once and runs it on JPEG frames. Only classes named like a pothole are kept (POTHOLE_CLASSES).

Priority: CoreML (.mlpackage, uses the Neural Engine) > PyTorch .pt on MPS > CPU.
With POTHOLE_MOCK=1 (or no model file) it returns fake boxes so the apps can be
tested before training is done."""
import io
import logging
import random
import threading
import time

from PIL import Image

from .config import settings
from .damage_labels import canonical, LABELS

log = logging.getLogger("pothole.inference")


def _norm(name):
    return str(name).lower().replace("_", " ").replace("-", " ")


class Detector:
    def __init__(self):
        self.lock = threading.Lock()   # one model, one frame at a time
        self.model = None
        self.mode = "mock"
        self.device = None
        self.keep_classes = None       # class ids that count as potholes (None = all)
        self.class_names = {}
        path = settings.model_path
        if settings.MOCK_DETECTOR or path is None:
            if path is None and not settings.MOCK_DETECTOR:
                log.warning("No model found in models/ -> running in MOCK mode. "
                            "Run scripts/download_pretrained.py (or ./setup.sh) to get one.")
            return
        from ultralytics import YOLO  # imported lazily so mock mode needs no torch

        try:
            self._load(YOLO, path)
        except Exception as e:
            fallback = path.with_suffix(".pt")
            if path.suffix != ".mlpackage" or not fallback.exists():
                raise
            log.warning("CoreML model failed to load (%s); falling back to %s", e, fallback.name)
            self._load(YOLO, fallback)
        # warm-up so the first real frame is not slow
        self.predict(Image.new("RGB", (settings.IMG_SIZE, settings.IMG_SIZE)))

    def _load(self, YOLO, path):
        if path.suffix == ".pt":
            self.model = YOLO(str(path))                       # task comes from the checkpoint
            import torch
            self.device = "cuda:0" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
            self.mode = f"pytorch-{self.device}"
        else:
            self.model = YOLO(str(path), task=settings.MODEL_TASK)
            self.device = None
            self.mode = "coreml"
        self.class_names = dict(self.model.names or {})
        keep = [i for i, n in self.class_names.items() if canonical(n) in settings.CLASSES]
        self.keep_classes = keep
        if not keep:
            raise ValueError("Model has no recognised road-damage classes. Use named classes or D00/D10/D20/D40.")
        #   # no matching name: keep everything the model finds
        log.info("Loaded %s (%s, %s px). Classes %s; keeping %s", path.name, self.mode, settings.IMG_SIZE,
                 self.class_names, [self.class_names[i] for i in keep] if keep else "all")

    @staticmethod
    def decode(jpeg_bytes: bytes) -> Image.Image:
        return Image.open(io.BytesIO(jpeg_bytes)).convert("RGB")

    def predict(self, image: Image.Image):
        """Returns (boxes, ms). boxes: [{x1,y1,x2,y2,conf}] in the image's pixels."""
        t0 = time.perf_counter()
        if self.model is None:
            if not settings.MOCK_DETECTOR:
                raise RuntimeError("No detector loaded. Download/select a YOLO model in System & Models and restart.")
            boxes = self._mock(image)
        else:
            with self.lock:
                kw = dict(imgsz=settings.IMG_SIZE, conf=settings.CONF_THRESHOLD, verbose=False)
                if self.device:
                    kw["device"] = self.device
                if self.keep_classes is not None:
                    kw["classes"] = self.keep_classes
                result = self.model.predict(image, **kw)[0]
            boxes = []
            for xyxy, conf, cls in zip(result.boxes.xyxy.tolist(), result.boxes.conf.tolist(),
                                       result.boxes.cls.tolist()):
                x1, y1, x2, y2 = xyxy
                boxes.append({"x1": x1, "y1": y1, "x2": x2, "y2": y2, "conf": round(conf, 3),
                              "damage_type": canonical(self.class_names.get(int(cls))),
                              "label": LABELS[canonical(self.class_names.get(int(cls)))],
                              "source_label": str(self.class_names.get(int(cls)))})
        return boxes, round((time.perf_counter() - t0) * 1000, 1)

    @staticmethod
    def _mock(image):
        # roughly one frame in eight "sees" a pothole in the lower-middle of the frame
        if random.random() > 0.12:
            return []
        w, h = image.size
        cx = w * random.uniform(0.35, 0.65)
        cy = h * random.uniform(0.62, 0.85)
        bw, bh = w * random.uniform(0.06, 0.16), h * random.uniform(0.03, 0.07)
        return [{"x1": cx - bw / 2, "y1": cy - bh / 2, "x2": cx + bw / 2, "y2": cy + bh / 2,
                 "conf": round(random.uniform(0.5, 0.9), 3)}]


_detector = None


def get_detector() -> Detector:
    global _detector
    if _detector is None:
        _detector = Detector()
    return _detector
