// Scanner: grabs camera frames at N fps, tags them with GPS, streams them over a WebSocket.
// Wire format per frame: [4-byte big-endian JSON length][JSON metadata][JPEG bytes]
(() => {
  const $ = (id) => document.getElementById(id);
  const video = $('video'), overlay = $('overlay'), octx = overlay.getContext('2d');
  const grab = document.createElement('canvas'), gctx = grab.getContext('2d');
  const MAX_IN_FLIGHT = 2;

  // ---------- settings (kept on this phone) ----------
  const KEY = 'pothole.scanner.settings';
  let defaults = { device: 'scanner-' + Math.random().toString(36).slice(2, 6), height: 1.2, tilt: 8, fov: 66, fps: 5, width: 1280, quality: 0.7 };
  let cfg = { ...defaults };
  const fields = { device: 'sDevice', height: 'sHeight', tilt: 'sTilt', fov: 'sFov', fps: 'sFps', width: 'sWidth', quality: 'sQuality' };

  function loadSettings() {
    try { cfg = { ...defaults, ...JSON.parse(localStorage.getItem(KEY) || '{}') }; } catch { cfg = { ...defaults }; }
    for (const [k, id] of Object.entries(fields)) $(id).value = cfg[k];
  }
  function saveSettings() {
    for (const [k, id] of Object.entries(fields)) {
      const v = $(id).value;
      cfg[k] = k === 'device' ? (v.trim() || defaults.device) : Number(v);
    }
    try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch { /* private mode */ }
    if (running) restartTimer();
  }
  Object.values(fields).forEach((id) => $(id).addEventListener('change', saveSettings));
  $('settingsBtn').onclick = () => $('settings').classList.add('open');
  $('closeSettings').onclick = () => $('settings').classList.remove('open');
  $('resetSettings').onclick = () => {
    const device = cfg.device; cfg = { ...defaults, device };
    for (const [k, id] of Object.entries(fields)) $(id).value = cfg[k];
    saveSettings();
  };

  fetch('/api/config').then((r) => r.json()).then((c) => {
    defaults = { ...defaults, height: c.camera_height_m, tilt: c.camera_tilt_deg, fov: c.hfov_deg };
    loadSettings();
    if (c.detector_mode === 'mock') setPill('pillLat', 'warn', 'Mock detector');
    if (c.detector_mode === 'preview') { preview = true; setPill('pillLat', 'warn', 'Preview: fake results'); }
  }).catch(loadSettings);

  // ---------- status pills ----------
  function setPill(id, cls, text) {
    const el = $(id); el.className = 'pill ' + (cls || '');
    el.lastElementChild.textContent = text;
  }

  // ---------- GPS + compass ----------
  let fix = null, compass = null;
  function startGps() {
    if (!('geolocation' in navigator)) { setPill('pillGps', 'bad', 'No GPS on this device'); return; }
    navigator.geolocation.watchPosition((p) => {
      fix = p.coords;
      const acc = Math.round(fix.accuracy);
      setPill('pillGps', acc <= 10 ? 'ok' : acc <= 25 ? 'warn' : 'bad', `GPS ±${acc} m`);
      const kmh = fix.speed != null ? Math.round(fix.speed * 3.6) : null;
      $('pillSpeed').lastElementChild.textContent = kmh == null ? '— km/h' : `${kmh} km/h`;
    }, (e) => setPill('pillGps', 'bad', e.code === 1 ? 'GPS blocked' : 'GPS error'),
    { enableHighAccuracy: true, maximumAge: 0, timeout: 15000 });
  }
  async function startCompass() {
    try {
      if (typeof DeviceOrientationEvent !== 'undefined' && DeviceOrientationEvent.requestPermission) {
        await DeviceOrientationEvent.requestPermission();   // iOS asks once
      }
    } catch { /* denied: GPS heading only */ }
    window.addEventListener('deviceorientationabsolute', (e) => { if (e.alpha != null) compass = (360 - e.alpha) % 360; });
    window.addEventListener('deviceorientation', (e) => { if (e.webkitCompassHeading != null) compass = e.webkitCompassHeading; });
  }
  function heading() {
    // GPS heading is only meaningful while moving; fall back to the compass
    if (fix && fix.heading != null && !Number.isNaN(fix.heading) && (fix.speed || 0) > 1) return fix.heading;
    return compass;
  }

  // ---------- camera ----------
  async function startCamera() {
    const stream = await navigator.mediaDevices.getUserMedia({
      audio: false,
      video: { facingMode: { ideal: 'environment' }, width: { ideal: 1920 }, height: { ideal: 1080 } },
    });
    video.srcObject = stream;
    await video.play();
    $('empty').hidden = true;
  }

  // ---------- wake lock ----------
  let wakeLock = null;
  async function keepAwake() {
    try { wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* not supported */ }
  }
  document.addEventListener('visibilitychange', () => { if (running && document.visibilityState === 'visible') keepAwake(); });

  // ---------- WebSocket ----------
  let ws = null, backoff = 500, inFlight = 0;
  const sentAt = new Map();
  // Preview mode (scripts/preview_frontend.py): no server-side detection, so answer
  // each frame here with a fake result shaped exactly like the server's reply.
  let preview = false;
  function fakeSocket() {
    const sock = { readyState: WebSocket.OPEN, close() { this.readyState = WebSocket.CLOSED; },
      send(buf) {
        const n = new DataView(buf).getUint32(0, false);
        const meta = JSON.parse(new TextDecoder().decode(new Uint8Array(buf, 4, n)));
        const w = grab.width, h = grab.height, boxes = [];
        if (Math.random() < 0.12) {
          const cx = w * (0.35 + Math.random() * 0.3), cy = h * (0.62 + Math.random() * 0.2);
          const bw = w * (0.06 + Math.random() * 0.1), bh = h * (0.03 + Math.random() * 0.04);
          boxes.push({ x1: cx - bw / 2, y1: cy - bh / 2, x2: cx + bw / 2, y2: cy + bh / 2, conf: +(0.5 + Math.random() * 0.4).toFixed(2) });
        }
        const reply = { seq: meta.seq, boxes, saved: boxes.map(() => Date.now()), ms: 40, img_w: w, img_h: h };
        setTimeout(() => sock.onmessage?.({ data: JSON.stringify(reply) }), 80 + Math.random() * 120);
      } };
    return sock;
  }

  function connect() {
    if (preview) { ws = fakeSocket(); ws.onmessage = onResult; inFlight = 0; setPill('pillConn', 'ok', 'Preview'); return; }
    const url = `${location.protocol === 'https:' ? 'wss' : 'ws'}://${location.host}/ws/scan`;
    ws = new WebSocket(url);
    setPill('pillConn', 'warn', 'Connecting…');
    ws.onopen = () => { backoff = 500; inFlight = 0; setPill('pillConn', 'ok', 'Connected'); };
    ws.onclose = () => {
      setPill('pillConn', 'bad', 'Offline, retrying');
      if (running) setTimeout(connect, backoff = Math.min(backoff * 2, 5000));
    };
    ws.onerror = () => ws.close();
    ws.onmessage = onResult;
  }

  function onResult(ev) {
    inFlight = Math.max(0, inFlight - 1);
    const r = JSON.parse(ev.data);
    if (r.error) { console.warn('server:', r.error); return; }
    const t = sentAt.get(r.seq); sentAt.delete(r.seq);
    if (t) $('pillLat').lastElementChild.textContent = `${Math.round(performance.now() - t)} ms`;
    if (r.boxes.length) drawBoxes(r);
    if (r.saved.length) {
      counts.saved += r.saved.length; render();
      $('flash').classList.add('on'); setTimeout(() => $('flash').classList.remove('on'), 250);
      navigator.vibrate?.(60);
    }
  }

  function pack(meta, jpegBuf) {
    const head = new TextEncoder().encode(JSON.stringify(meta));
    const out = new Uint8Array(4 + head.length + jpegBuf.byteLength);
    new DataView(out.buffer).setUint32(0, head.length, false);
    out.set(head, 4);
    out.set(new Uint8Array(jpegBuf), 4 + head.length);
    return out.buffer;
  }

  // ---------- frame loop ----------
  let running = false, timer = null, seq = 0, sensorsOn = false;
  const counts = { sent: 0, saved: 0, skipped: 0 };
  function render() { $('cSent').textContent = counts.sent; $('cSaved').textContent = counts.saved; $('cSkipped').textContent = counts.skipped; }

  async function tick() {
    if (!video.videoWidth) return;
    if (!ws || ws.readyState !== WebSocket.OPEN || inFlight >= MAX_IN_FLIGHT) { counts.skipped++; render(); return; }
    const w = Number(cfg.width), h = Math.round(video.videoHeight * w / video.videoWidth);
    grab.width = w; grab.height = h;
    gctx.drawImage(video, 0, 0, w, h);
    // capture position NOW, together with the frame
    const meta = {
      seq: ++seq, captured_at: new Date().toISOString(), device_id: cfg.device,
      lat: fix?.latitude ?? null, lon: fix?.longitude ?? null, gps_accuracy_m: fix?.accuracy ?? null,
      heading_deg: heading(), speed_kmh: fix?.speed != null ? fix.speed * 3.6 : null,
      camera_height_m: cfg.height, camera_tilt_deg: cfg.tilt, hfov_deg: cfg.fov,
    };
    inFlight++;
    const blob = await new Promise((res) => grab.toBlob(res, 'image/jpeg', Number(cfg.quality)));
    if (!blob || ws.readyState !== WebSocket.OPEN) { inFlight--; return; }
    sentAt.set(meta.seq, performance.now());
    if (sentAt.size > 50) sentAt.delete(sentAt.keys().next().value);
    ws.send(pack(meta, await blob.arrayBuffer()));
    counts.sent++; render();
  }
  function restartTimer() { clearInterval(timer); timer = setInterval(tick, 1000 / Math.max(1, Number(cfg.fps))); }

  // ---------- box overlay ----------
  let clearTimer = null;
  function drawBoxes(r) {
    const W = overlay.clientWidth, H = overlay.clientHeight;
    overlay.width = W * devicePixelRatio; overlay.height = H * devicePixelRatio;
    octx.setTransform(devicePixelRatio, 0, 0, devicePixelRatio, 0, 0);
    octx.clearRect(0, 0, W, H);
    // video uses object-fit: contain -> letterboxed area
    const s = Math.min(W / r.img_w, H / r.img_h), ox = (W - r.img_w * s) / 2, oy = (H - r.img_h * s) / 2;
    const colors={pothole:'#ff7a1a',longitudinal_crack:'#2563eb',transverse_crack:'#9333ea',alligator_crack:'#e11d48',road_damage:'#64748b'};
    octx.lineWidth = 3; octx.strokeStyle = '#ff7a1a'; octx.fillStyle = '#ff7a1a';
    octx.font = '600 15px Barlow, sans-serif';
    for (const b of r.boxes) {
      octx.strokeStyle=octx.fillStyle=colors[b.damage_type] || '#ff7a1a';
      const x = ox + b.x1 * s, y = oy + b.y1 * s;
      octx.strokeRect(x, y, (b.x2 - b.x1) * s, (b.y2 - b.y1) * s);
      octx.fillText(`${b.label || 'pothole'} ${Math.round(b.conf * 100)}%`, x, Math.max(14, y - 6));
    }
    clearTimeout(clearTimer);
    clearTimer = setTimeout(() => octx.clearRect(0, 0, W, H), 700);
  }

  // ---------- start / stop ----------
  $('startBtn').onclick = async () => {
    const btn = $('startBtn');
    if (running) {
      running = false; clearInterval(timer); ws?.close(); wakeLock?.release?.();
      btn.textContent = 'Start scan'; btn.classList.remove('running');
      return;
    }
    try {
      await startCamera();
    } catch (e) {
      alert(location.protocol !== 'https:' && location.hostname !== 'localhost'
        ? 'The camera needs HTTPS. Open this page with https:// (see README).'
        : `Camera not available: ${e.message}`);
      return;
    }
    if (!sensorsOn) { sensorsOn = true; startGps(); startCompass(); }
    keepAwake();
    running = true; connect(); restartTimer();
    btn.textContent = 'Stop'; btn.classList.add('running');
  };

  loadSettings();
})();
