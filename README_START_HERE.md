# RoadPlotter — Windows Z6 and Apple Silicon

Run `python setup.py` once, then `python run.py`. Open http://localhost:8000.
Python 3.11 recommended. Install Ollama separately and keep it running.
Use System & Models to download weights. Downloads require internet.
The explicit Qwen quantization tag must exist in your Ollama registry; if unavailable set POTHOLE_SLM_MODEL to a verified 4-bit tag.

For phones use trusted HTTPS: python run.py --host 0.0.0.0 --cert certificate.pem --key key.pem.
Default loopback binding keeps model management local. Do not expose this prototype directly to the public internet; authentication is not implemented.

## Folders
- frontend/: existing home, camera scanner and driver UI; system.html shows hardware and model availability.
- backend/: main.py HTTP/WebSocket endpoints; inference.py YOLO; config.py settings; db.py SQLite; geo.py projection; routing.py routes; system_models.py hardware/downloads.
- notebooks/: post-processing and optional training notebooks.
- scripts/: model download/export, data sharing and training tools.
- models/: downloaded or user-trained weights (not bundled).
- data/: database and photos (created at runtime).

## Share processed data
Stop scanning and processing first.
`python scripts/share_data.py export roads.zip --directory data`
On the other machine:
`python scripts/share_data.py import roads.zip --directory imported_data`
Set POTHOLE_DB_PATH to imported_data/pothole.db and POTHOLE_PHOTOS_DIR to imported_data/photos before starting.

## Fine-tuning and sharing weights
Provide a licensed YOLO dataset with independent train/validation/test splits.
`python scripts/train_indian_roads.py --data datasets/roads/data.yaml --device 0`
On Mac use --device mps. Share training_runs/indian_roads/weights/best.pt together with model class names, licence and evaluation report. Only load trusted PyTorch weights.
The dataset is NOT bundled or downloaded in this build. Kaggle access and dataset licensing still require verification. No fine-tuning was performed here.

## Limitations and verification
This is an engineering preview, not a fault-free release. Hardware execution, model downloads, browser cameras and end-to-end training need testing on real devices. Original postprocessing runs in a separate process and does not yet coordinate GPU unloading with the scanning server; stop scanning and avoid simultaneous AI workloads. Missing detector weights currently use the upstream mock mode, which the scanner labels. Data transfer is snapshot import, not synchronization or merging.

## Drive-only page
Open /drive (for example http://localhost:8000/drive). Includes explicit place search, route alternatives, GPS origin, map selection, alerts and link copying. /driver remains compatible. Search and route services require internet. This is an independent OpenStreetMap interface, not Google Maps. A local URL is accessible only from its host; remote phones need a reachable HTTPS server.

## Road-damage labels
Scanner, storage, map popups and spoken alerts now preserve damage types. Supported names: pothole, longitudinal_crack (D00), transverse_crack (D10), alligator_crack (D20), road_damage; D40 maps to pothole. Different classes are never merged during post-processing. Existing records migrate as pothole. Crack fallback severity stays unscored and flagged for review; pothole area rules are not applied to cracks.

IMPORTANT: bundled configuration still downloads HRP4K pothole-only weights. No new trained model is bundled. Train on a four-class RDD dataset or supply trusted compatible weights with named classes. Set POTHOLE_MODEL_PATH to that .pt file and restart. System & Models lists the actual supported classes. Numeric class names without a mapping are rejected. This update does not itself add learned crack-detection ability to pothole-only weights.

## Model selection update
System & Models now offers upload, installed-model selection and an optional third-party RDD2022 YOLOv8s download. Source: https://huggingface.co/SreekarAditya/yolo-rdd2022-benchmark . It supports D00/D10/D20/D40, not a fifth unspecified-damage class. HRP4K YOLO26m remains the pothole preset. Download/select once and restart; future starts automatically use models/active_model.txt, or models/road_damage.pt when no selection exists. POTHOLE_MODEL_PATH overrides UI selection. Downloads are explicit, not silently initiated. Models are not hot-swapped during inference. Model source and inference compatibility need real-device evaluation. No weights are bundled.

## YOLO26 multi-class download options
System & Models offers YOLO26s RDD FRDC Distilled v2 and YOLO26n RDD FRDC Distilled. These are separate from the HRP4K YOLO26m pothole-only preset. Sources:
- https://huggingface.co/TamAko783/YOLO26s_RDD_FRDC_Distilled_v2
- https://huggingface.co/TamAko783/YOLO26n_RDD_FRDC_Distilled
Downloads discover the source's .pt file; ambiguous files fail explicitly. Select/download, restart, and inspect supported classes. These community models use combined training data including RDD2022 and support four classes, not unspecified road damage. Weights are not bundled; actual loading and accuracy need device testing.

## Recommended fast profile
For both Z6 and M4, choose YOLO26n RDD Distilled under System & Models. This is a smaller community-trained four-class detector, not custom fine-tuning performed for this project. Existing selections are preserved; explicitly download/select YOLO26n and restart to switch. Qwen remains Qwen3.5 4B quantized. Speed and accuracy require local evaluation.

## Independent model choices
Open /system. Select an installed YOLO model and restart. For Qwen, choose 2B or 4B, click Save Qwen choice, then Download saved Qwen model if it is not installed. The choice persists in models/active_qwen.txt and applies to subsequent notebook jobs. Running jobs are unaffected. Environment overrides take precedence after restart. qwen3.5:2b uses Ollama's published quantization for that tag; it is not claimed to be 4-bit. Provider availability of the explicit 4B tag must be checked at download time; errors are displayed.
