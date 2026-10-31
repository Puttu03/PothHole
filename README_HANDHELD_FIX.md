# Handheld recording recovery

This patch adds a local photo-by-photo camera calibration tool. It addresses location projection failures caused by incorrect fixed tilt metadata. It does not retrain YOLO, automatically infer the horizon, or guarantee detection/position accuracy. Existing confirmed/unconfirmed map records are not rebuilt.

## Install

Stop RoadPlotter and copy these files into your existing project, retaining the folder paths:

- `review_handheld.py` — new, next to `run.py`
- `backend/frame_calibration.py` — new
- `backend/postprocess_quality.py` — replace
- `notebooks/02_postprocess.ipynb` — replace

Keep your `data` folder and models. This is a patch for the earlier RoadPlotter Python backend project, not the original GitHub `server` layout.

## Run the review tool

From the project folder on Mac:

```
.venv/bin/python review_handheld.py
```

Windows:

```
.venv\Scripts\python.exe review_handheld.py
```

Open http://127.0.0.1:8766 on that computer if it does not open automatically. The review server is local-only; it is not exposed through the Drive tunnel. If your data is elsewhere, pass `--db PATH_TO_DB --photos PATH_TO_PHOTOS`.

1. Choose a photo. Orange boxes show stored detections, not new model inference.
2. Set the cyan horizon at both image edges. The endpoints can differ to account for camera roll. Identify the horizon of the road plane, not the tree/building skyline. Do not use one setting for every handheld photo or adjust merely to remove an error.
3. Verify camera height, horizontal FOV of the saved frame, and the camera's forward compass heading. Travel direction alone is insufficient when the camera points sideways.
4. Click **Preview projection**. If you cannot establish a reasonable calibration, leave the photo deferred. Road slopes, lens distortion and unknown FOV can still make this method inaccurate.
5. Click **Save correction & queue retry** for reviewed frames. A database snapshot is made in `data/backups` before the first save in each review session. No original image or capture geometry is overwritten. Corrections are stored in a separate `frame_calibration` table, keyed to detection IDs. Only unassigned sightings in that photo are queued, including older rejected/unassigned sightings.
6. Exit with Ctrl+C. Start RoadPlotter normally, then click **Run post-processing**.

The review tool does not run YOLO or Ollama and does not start post-processing itself. Do not run the main server, post-processing or a DB rebuild at the same time as this tool.

## Expected results

Corrected boxes may become projectable. The existing distance/GPS checks and confirmation threshold remain in place. Some boxes can remain deferred. The 95 records awaiting more sightings are a separate confirmation issue; this patch does not turn them into confirmed records. Three observations close enough to merge are still required by the current notebook default; that threshold alone is not proof of correctness.

The scoring step now uses the same per-sighting corrected geometry and no longer double-counts current sightings when choosing its best photo. Calibrated scoring remains marked `needs_review`. The existing map publication rule is otherwise unchanged.

For future recordings, this patch does not capture per-frame sensor orientation or automatically calibrate handheld video. Stable mounting reduces changing orientation; handheld frames still need per-photo review here. Estimated width and along-road length are geometric approximations, not physical pothole depth.

## Tests

`python -m unittest discover -s tests -p test_handheld_recovery.py` runs the included five geometry/data-preservation tests after installing this patch in the project. These use temporary databases. No model weights are included.

## Restore

If needed, stop all processes and preserve a copy of the current data first. The backup is a whole SQLite snapshot from before the first correction save. Restoring it also discards any changes made since that snapshot; do not replace a database while it is open. Do not delete your photos or model files.
