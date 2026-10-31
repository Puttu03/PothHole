# Pothole Cloud — Product Plan

Oct 23, 2026 · @Mohamed Kamran

## What we are building

Pothole Cloud finds potholes on roads, works out exactly where they are and how bad they are, and warns drivers before they reach them.

It has two web apps, opened in the phone's browser, that share one Python (FastAPI) server:

- **Scanner app (employees).** Staff drive or walk the roads with a phone camera. The app streams camera frames, with the phone's GPS position and direction, to the server, which spots the potholes.
- **Driver app (consumers).** Everyday drivers see potholes on a map, plan a trip from A to B, and get a countdown alert ("Pothole in 100 m… 50 m…") with a photo as they get close.

In between, the cloud cleans up the raw reports: it moves each point from "where the phone was" to "where the pothole actually is", merges duplicates, and adds a severity level, a ride-impact score and a short description.

## How it works, end to end

A pothole goes from a phone sighting to a driver alert in five steps, matching your diagram.

&#91;embedded content: end-to-end flow · scanner to driver\]

1. **Serve the web app (GET /).** FastAPI sends the web app to the phone's browser, so nobody installs anything from an app store.
2. **Detect (POST /classify).** The scanner phone streams frames at 5 fps over a WebSocket; the server runs YOLO26m on each one and sends back the boxes.
3. **Submit (POST /submit).** Confirmed sightings, with photo, phone lat/long, heading and speed, are saved in DB1. Everything passes through the server, never straight to the database.
4. **Post-process (hook).** A Jupyter notebook, triggered by hand or by the server, finds the real pothole spot, merges repeats, scores it and writes it to DB.F.
5. **Serve pothole data (GET /getpdata).** The driver app pulls potholes from DB.F as JSON for its map, routes and alerts.

## Edge or server? Server only

We use server-only detection: the phone just streams frames, and the server finds every pothole.

- **On the phone:** no model. The browser grabs about 5 frames a second, shrinks each to a roughly 480 px JPEG, tags it with GPS, heading and time, and sends it over one WebSocket.
- **On the server:** YOLO26m (fine-tuned) checks every frame, drops false alarms like shadows, puddles and manhole covers, and saves confirmed potholes to DB1.

Why server only: one accurate model, nothing heavy on low-end phones, and a model update means updating one server. The cost is mobile data (about 1–1.5 Mbps, roughly 0.5–0.7 GB per hour per scanner) and needing signal while scanning. One M1 can serve about 5–10 scanners at once.

To keep it smooth: allow only 1–2 frames in flight and skip frames when the network is slow; record GPS when the frame is taken, not when the answer comes back; reconnect automatically when the connection drops.

The model needs fine-tuning before launch: the stock YOLO26 does not know what a pothole is. Train YOLO26m on HRP4K plus the pothole class of RDD2022, then add a few hundred frames from our own phones and roads.

## Post-processing: real location, severity, score, description

A Jupyter notebook takes every unprocessed report in DB1 through three steps, then writes it to DB.F. Run it by hand, or trigger it from the server (POST /process runs it with papermill).

### 1. Move the point from the phone to the pothole

The GPS gives the phone's position (x, y). The pothole is some metres ahead (x', y'). We work it out with basic geometry, assuming the road is flat:

1. **How far ahead (d).** We know the phone's mount height h (a setting in the scanner app, default about 1.2 m on a dashboard) and its tilt angle θ (also a setting, default 8°). Both are sent with every frame and saved in DB1, so each scanner can use its own values. The pixel row of the pothole's bottom edge gives the extra angle α below the camera centre. Then distance ahead = h ÷ tan(θ + α).
2. **How far left or right (s).** The pixel column and the camera's field of view give the sideways offset.
3. **Which way the car is facing (bearing β).** From GPS heading, or the compass when stopped.
4. **Shift the coordinates.** For short distances the Earth is flat enough:

```latex
\text{lat}' = \text{lat} + \frac{d\cos\beta - s\sin\beta}{R} \cdot \frac{180}{\pi}, \qquad \text{lon}' = \text{lon} + \frac{d\sin\beta + s\cos\beta}{R\cos(\text{lat})} \cdot \frac{180}{\pi}
```

R is the Earth's radius (6,371,000 m). Only trust detections within about 25 m; farther ones are too inaccurate.

### 2. Merge duplicates

The same pothole gets seen in many frames and on many drives. Group reports that fall within about 5 m of each other into one pothole, and average their positions. More sightings means a more confident, more accurate location.

### 3. Severity, ride-impact score and description (local SLM)

A small vision-language model running on the Mac looks at the pothole and does the judging: severity, ride-impact score and a plain description, in one call.

**What it gets:** the best photo, cropped around the pothole, plus the numbers we already worked out: approximate width and area in metres, distance from the camera, position in the lane, and how many times it was seen.

**What it returns (JSON):**

```json
{
  "severity": "High",
  "ride_score": 7.4,
  "surface": "deep, water-filled, broken edges",
  "lane_position": "left wheel path",
  "description": "Deep pothole about 60 cm wide in the left wheel path, partly filled with water."
}
```

- **Severity:** Low, Medium, High or Critical.
- **Ride-impact score:** 0 to 10, how much it will jolt a car or bike.
- **Description:** one plain line for the driver app.

**Model choice:** any small open vision model that runs locally, for example Qwen2.5-VL 3B, Gemma 3 4B or SmolVLM, served with Ollama or MLX on the Mac. Try two or three on the same 50 potholes and keep the one whose scores match your own judgement best.

**Keeping it reliable:** ask for JSON only and check it parses; give it a short scoring guide with an example of each severity level; if it fails or answers nonsense, fall back to a simple size-based rule and mark the row for review. Store the model name with each result so scores can be redone later with a better model.

## What each database stores

DB1 holds raw sightings exactly as the phone saw them; DB.F holds one clean record per real pothole.

**DB1 (pre) — one row per detection**

| Field | Example |
| --- | --- |
| Detection ID | det\_8f21 |
| Scanner user / device | emp\_014 / phone\_07 |
| Time | 2026-10-23 09:14:05 |
| Phone lat, long | 12.97162, 77.59460 |
| GPS accuracy (m) | 4.5 |
| Heading (deg) | 82 |
| Speed (km/h) | 32 |
| Camera height, tilt | 1.2 m, 8° |
| Photo | file path in the photos folder |
| Box (pixels) and model confidence | \[412, 610, 540, 668\], 0.87 |
| Processed? | yes / no |

**DB.F (final) — one row per pothole**

| Field | Example |
| --- | --- |
| Pothole ID | ph\_2291 |
| Pothole lat, long | 12.97168, 77.59481 |
| Location accuracy (m) | 2.1 |
| Severity | High |
| Ride-impact score (0–10) | 7.4 |
| Size (approx.) | 0.6 m × 0.4 m |
| Description | Deep pothole in left wheel path |
| Best photo + other photos | links |
| Times seen / first seen / last seen | 9 / 2026-10-02 / 2026-10-23 |
| Status | Open, Repaired, Unconfirmed |
| Linked detections | det\_8f21, det\_8f40, … |

For the prototype it stays simple: one SQLite file on the Mac holds both tables, and photos sit in a local folder with only their file path in the table. "Potholes near me" is a plain lat/long range filter.

## Driver app: map, route, and countdown alerts

The driver app shows potholes around you and warns you before you hit one.

**Map view.** A Leaflet map with OpenStreetMap tiles and the user's live position. Potholes appear as pins coloured by severity. Tapping a pin shows the photo, severity, score, description and when it was last seen.

**Plan a trip.** The user picks start and end by dropping pins, searching an address, or using "my location". The app gets a route (from a routing service such as OSRM) and shows only the potholes within about 10 m of that route, plus a summary like "6 potholes on this route, 2 high severity".

**While driving.**

1. The app tracks the phone's GPS every second or two.
2. It finds the next pothole ahead *on the route*, not just the nearest one in a straight line (so potholes on a parallel street don't trigger).
3. When it is within the alert threshold (default 100 m), a status bar appears at the top with the pothole photo, severity colour and a live countdown: 100 m → 75 → 50 → 25.
4. Optional voice or beep at 100 m and 50 m.
5. After passing it, the bar clears and moves to the next one.

**Settings.** Alert distance (50 / 100 / 200 m), minimum severity to alert on, sound on or off.

**Feedback.** After passing, the driver can tap "Still there" or "Gone". This keeps DB.F fresh and helps tune the scores.

To work in poor network areas, the app downloads the potholes along the route when the trip starts. The site must use HTTPS (browsers only allow camera and GPS on secure pages), and it keeps the screen awake during scans and trips.

## APIs

The server exposes five endpoints from your diagram, plus two the driver app needs.

| Endpoint | Who calls it | What it does |
| --- | --- | --- |
| GET / | Both apps | Serves the web app (pages and scripts) |
| POST /classify | Scanner app | Streams frames at 5 fps (as a WebSocket, /ws/scan); server runs YOLO26m and returns boxes + confidence |
| POST /submit | Scanner app | Saves confirmed detections (photo, lat/long, heading, speed, camera setup) into DB1 via the server |
| POST /process | You, or a button/script | Runs the notebook on all unprocessed DB1 rows: location fix, merge, severity, score, description → DB.F |
| GET /getpdata | Driver app | Returns potholes as JSON; accepts a map area or radius so it never sends the whole database |
| GET /route-potholes | Driver app | Takes start and end, returns the route line + potholes along it |
| POST /feedback | Driver app | "Still there" / "Gone" reports on a pothole |

Tip: /classify and /submit can be one call (the server classifies, then saves if confirmed). That halves uploads. Keep them separate only if scanner staff need to review before submitting.

Scanner endpoints need employee login; driver endpoints can be public but rate-limited.

## Tech stack and build order

Two web apps served by one Python FastAPI server, all running locally on the Mac.

| Part | Choice |
| --- | --- |
| Phone detection | None: the phone only captures and streams JPEG frames |
| Server detection | YOLO26m, CoreML on the M1, about 5 fps per stream |
| Backend | Python, FastAPI (serves the web apps and the JSON APIs) |
| Databases | One SQLite file on the Mac, two tables: DB1 and DB.F |
| Photo storage | A local photos folder on the Mac |
| Post-processing hook | A Jupyter notebook, run by hand or triggered via POST /process (papermill) |
| Descriptions | Local vision SLM (Ollama or MLX): severity, ride score, description |
| Maps and routing | Leaflet + OpenStreetMap tiles, OSRM for routes |
| Apps | Two web apps (scanner, driver) that open in any phone browser; can be added to the home screen as a PWA |

**Build in this order:**

1. **Model.** Fine-tune YOLO26m on pothole data; test on our own road footage.
2. **Scanner + DB1.** Camera capture, GPS, /classify, /submit. Drive a few roads and fill DB1.
3. **Post-processing + DB.F.** Location fix, merging, severity, score, description. Check accuracy by visiting a few potholes in person.
4. **Driver map.** /getpdata and the map with pins.
5. **Routes and alerts.** Start/end picking, route potholes, the 100 m countdown bar.
6. **Feedback and polish.** Still there / Gone, offline route cache, settings.

## Risks

The biggest risk is location error, because phone GPS alone is often 3–10 m off.

- **GPS error.** Merging many sightings and showing an accuracy circle helps. Alerts at 100 m are forgiving; pinpointing to the exact lane is not reliable.
- **Camera setup varies.** The distance math needs mount height and tilt. They are settings with defaults, so set them to match the real mount, or fix the scanner phone in a standard mount.
- **False alarms.** Shadows, patches, puddles, speed breakers. The server model plus the "seen more than once" rule cuts most of them.
