# Pothole Cloud (prototype)

Phones scan roads and stream frames to a Mac. The Mac finds potholes with a pretrained pothole model (PotholeNet, trained on Indian city roads), stores them, works out where each pothole really is, scores it with a local SLM, and warns drivers on a map as they approach.

Everything runs locally on one Mac: a FastAPI server, a SQLite file, a photos folder and two Jupyter notebooks.

## What's in the folder

| Path | What it is |
| --- | --- |
| `setup.sh` | One-time setup: Python packages, database, HTTPS certificate, pothole model, Ollama model |
| `run_server.sh` | Starts the server |
| `server/main.py` | FastAPI app: web pages, WebSocket scanning, all endpoints |
| `server/inference.py` | Detection engine (CoreML, else PyTorch on MPS, else mock) |
| `server/db.py` | SQLite tables: `detections` (DB1), `potholes` (DB.F), `feedback` |
| `server/geo.py` | Camera geometry and lat/long maths |
| `server/routing.py` | Routes via OSRM, potholes along a route |
| `server/config.py` | All settings, each overridable with a `POTHOLE_*` variable |
| `web/` | Home page, scanner app, driver app |
| `notebooks/01_train_yolo26.ipynb` | Optional, later: train your own model on your roads |
| `notebooks/02_postprocess.ipynb` | DB1 → DB.F: locate, merge, score |
| `scripts/preview_frontend.py` | Preview the web apps with fake data, no installs needed |
| `scripts/seed_demo.py` | Fake drives past known potholes, for testing the real pipeline |
| `scripts/download_pretrained.py` | Download a pretrained pothole model (setup.sh runs it) |
| `scripts/compare_models.py` | Try several models on your own photos, side by side |
| `server/model_catalog.py` | The pretrained models the scripts know about |
| `scripts/export_coreml.py` | Convert the model to CoreML |

## Preview the apps (no installs)

To check the screens without installing anything, use the Python that comes with macOS:

```bash
python3 scripts/preview_frontend.py            # http://localhost:8000 on this Mac
python3 scripts/preview_frontend.py --https    # https://<mac-ip>:8443 for phones on your Wi-Fi
```

It serves the real pages with fake potholes and fake detections; nothing is saved. Open `/driver?sim` to watch a test car drive the demo road and trigger the countdown. Add `--lat`, `--lon` and `--heading` to put the demo road near you. The map tiles need internet.

`/driver?sim` also works on the real server: every route you plan gets driven by a test car instead of your GPS.

## Quick start

```bash
./setup.sh                      # once: also downloads the pothole model
./run_server.sh
```

No training needed: `setup.sh` downloads a ready-trained model. Open `https://localhost:8443` on the Mac, or `https://<mac-ip>:8443` on a phone on the same Wi-Fi (the address is printed at start). The certificate is self-signed, so the browser warns once: choose "Show details → visit this website" (Safari) or "Advanced → Proceed" (Chrome).

**Try the whole flow without driving:**

```bash
.venv/bin/python scripts/seed_demo.py --lat 12.9716 --lon 77.5946 --heading 80
```

Then on the home page press **Run post-processing**, open **Drive**, and you'll see 4 potholes along a 400 m road. Use your own coordinates to see them near you.

## The flow

1. **Scan** (`/scanner`): mount the phone (landscape is best), set its height and tilt in Settings, press Start. Frames (1280 px by default; 960 px is plenty for the 768 px default model) go to the server at 5 fps over `/ws/scan`; frames with potholes are saved to `data/photos/` and a row per box goes into DB1.
2. **Post-process**: press the button on the home page (`POST /process` runs the notebook with papermill), or open `notebooks/02_postprocess.ipynb` in Jupyter and Run All. It:
   - turns each box into a real pothole position using mount height, tilt, field of view and heading;
   - merges sightings of the same pothole (radius grows with poor GPS);
   - asks the local SLM for severity, ride score (0–10) and a one-line description, falling back to a size rule if the SLM is unavailable;
   - shows a pothole to drivers only after 3 sightings.
3. **Drive** (`/driver`): the map shows open potholes. Tap **Plan a route**, set start (or "Start from my location") and destination. While driving, a bar shows the next pothole with its photo and counts down from 100 m, with a beep and voice at 100 m and 50 m. After you pass one, the app asks "Still there?"; two "Gone" answers mark it repaired.

## The detection model

`setup.sh` downloads a ready-trained model into `models/pothole.pt`, saves its settings (input size, classes) in `models/model.json`, and on a Mac exports it to CoreML. Three are available:

| Preset | Model | Trained on | Input | Licence |
| --- | --- | --- | --- | --- |
| `potholenet` (default) | YOLO11m | ~23k street photos from Indian cities; classes pothole, road damage, garbage | 768 px | MIT |
| `hrp4k` | YOLOv8m | 4K road photos; best on small, distant potholes | 1280 px | AGPL-3.0 |
| `pothole-seg` | YOLOv8m-seg | Mostly close-up potholes, with outlines | 640 px | see model card |

The authors' accuracy figures are on their own test sets, so they don't tell you which is best on your roads. Check with your own photos:

```bash
.venv/bin/python scripts/compare_models.py --images ~/Desktop/road_photos
```

It downloads each candidate into `models/candidates/` (your active model isn't touched) and writes one side-by-side image per photo into `data/compare/`. Then switch:

```bash
.venv/bin/python scripts/download_pretrained.py --preset hrp4k --force    # or potholenet / pothole-seg
```

and restart the server. `--list` shows the presets; `--repo <hf-repo> --file <weights.pt> --imgsz <px>` takes any other model.

Only classes named like "pothole" are kept. PotholeNet also has a "road damage" class (cracks, worn and broken surface), which may catch shallow, eroded concrete. To keep it too:

```bash
POTHOLE_CLASSES="pothole,road damage" ./run_server.sh
```

The server picks `models/pothole.mlpackage` first, then `models/pothole.pt`. If the CoreML file fails to load, it falls back to the `.pt` file. With neither, it runs in mock mode.

**Training your own later (optional):** no pretrained model will be perfect on your exact roads. Once the scanner has saved a few hundred real frames, label them and run `notebooks/01_train_yolo26.ipynb` with `BASE_MODEL = '../models/pothole.pt'` to fine-tune the current model. Include frames of plain road with no pothole. A Colab/Kaggle GPU is much faster than the Mac.

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET | `/` `/scanner` `/driver` | Web apps |
| WS | `/ws/scan` | Frame = 4-byte big-endian JSON length + JSON metadata + JPEG. Reply: boxes, saved ids, ms |
| POST | `/classify` | One image → boxes (nothing saved) |
| POST | `/submit` | One image + `meta` JSON (+ optional `boxes`) → saved to DB1 |
| POST | `/process` | Run the post-process notebook |
| GET | `/process/status` | Last run + number of sightings waiting |
| GET | `/getpdata?lat=&lon=&radius_m=` | Open potholes as JSON (all if no point given) |
| GET | `/route-potholes?start=lat,lon&end=lat,lon` | Route + potholes on it, in driving order |
| POST | `/feedback` | `{"pothole_id": 3, "kind": "still_there" or "gone"}` |

## Settings

Set as environment variables before `./run_server.sh`, e.g. `POTHOLE_CONF_THRESHOLD=0.5 ./run_server.sh`.

| Variable | Default | Meaning |
| --- | --- | --- |
| `POTHOLE_CONF_THRESHOLD` | 0.30 | Minimum detection confidence |
| `POTHOLE_IMG_SIZE` | from `models/model.json` | Model input size; re-run `export_coreml.py` after changing it |
| `POTHOLE_CLASSES` | pothole | Class names to keep, comma-separated |
| `POTHOLE_CAMERA_HEIGHT_M` | 1.2 | Default mount height (the scanner app can override it) |
| `POTHOLE_CAMERA_TILT_DEG` | 8 | Default tilt below the horizon |
| `POTHOLE_HFOV_DEG` | 66 | Default horizontal field of view |
| `POTHOLE_SLM_MODEL` | qwen3-vl:4b | Ollama vision model for scoring (`qwen3-vl:2b` lighter, `qwen3-vl:8b` needs 16 GB) |
| `POTHOLE_OLLAMA_URL` | http://localhost:11434 | Ollama address |
| `POTHOLE_OSRM_URL` | https://router.project-osrm.org | Routing service (public demo server) |
| `POTHOLE_MOCK` | off | `1` = fake detections |
| `POTHOLE_GONE_REPORTS_TO_CLOSE` | 2 | "Gone" reports before a pothole is marked repaired |

Notebook-only settings (merge radius, minimum sightings, max distance) are in the first cell of `02_postprocess.ipynb`.

## Getting good locations

- Measure the mount height (camera lens to road) and set it in the scanner's Settings.
- Tilt: how far the camera points below the horizon. If potholes land too far ahead on the map, increase the tilt; too close, decrease it.
- Keep the phone level (no roll) and pointing straight ahead.
- Scanning the same road two or three times averages out GPS error.

## Troubleshooting

- **Camera or GPS won't start on the phone:** the page must be `https://`. Use the address printed by `run_server.sh` and accept the certificate warning.
- **iPhone compass:** Safari asks for motion permission when you press Start; allow it.
- **"Ollama not reachable" in the notebook:** start the Ollama app (or `ollama serve`) and `ollama pull qwen3-vl:4b`. Scores fall back to the size rule meanwhile and are flagged `needs_review`.
- **Routing fails:** the public OSRM demo server needs internet and can be slow. You can run your own OSRM and set `POTHOLE_OSRM_URL`.
- **Mac's IP changed:** run `SKIP_INSTALL=1 ./setup.sh` to make a new certificate.
- **Too much mobile data:** in the scanner's Settings lower the frame width to 960 px or the rate to 3 fps.
- **Too slow on the Mac:** check the server log says `coreml`; if not, run `scripts/export_coreml.py`. Lowering `POTHOLE_IMG_SIZE` to 960 also helps.
- **Start over:** stop the server and delete `data/pothole.db` and `data/photos/`.
