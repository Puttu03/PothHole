// Driver: map of potholes, route A -> B, countdown alert with photo as you approach.
(() => {
  const $ = (id) => document.getElementById(id);
  const DAMAGE_LABELS={pothole:'Pothole',longitudinal_crack:'Longitudinal crack',transverse_crack:'Transverse crack',alligator_crack:'Alligator crack',road_damage:'Road damage'};
  const DAMAGE_COLORS={pothole:'#ff7a1a',longitudinal_crack:'#2563eb',transverse_crack:'#9333ea',alligator_crack:'#e11d48',road_damage:'#64748b'};
  const damageLabel=p=>DAMAGE_LABELS[p.damage_type]||'Road damage';
  const SEV_RANK = { Low: 0, Medium: 1, High: 2, Critical: 3 };
  const SEV_COLOR = { Low: '#6cc287', Medium: '#f2c230', High: '#ff7a1a', Critical: '#e5484d' };
  const R = 6371000, rad = (d) => d * Math.PI / 180, deg = (r) => r * 180 / Math.PI;
  const SIM = new URLSearchParams(location.search).has('sim');
  const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  // ---------- settings ----------
  const KEY = 'pothole.driver.settings';
  const cfg = { threshold: 100, minSev: 'Low', beep: 1, voice: 1 };
  try { Object.assign(cfg, JSON.parse(localStorage.getItem(KEY) || '{}')); } catch { /* ignore */ }
  const sFields = { threshold: 'sThreshold', minSev: 'sMinSev', beep: 'sBeep', voice: 'sVoice' };
  for (const [k, id] of Object.entries(sFields)) {
    $(id).value = String(cfg[k]);
    $(id).addEventListener('change', () => {
      cfg[k] = k === 'minSev' ? $(id).value : Number($(id).value);
      try { localStorage.setItem(KEY, JSON.stringify(cfg)); } catch { /* ignore */ }
    });
  }
  $('setBtn').onclick = () => $('settings').classList.add('open');
  $('closeSettings').onclick = () => $('settings').classList.remove('open');

  // ---------- geometry ----------
  function dist(a, b) {
    const dp = rad(b[0] - a[0]), dl = rad(b[1] - a[1]);
    const h = Math.sin(dp / 2) ** 2 + Math.cos(rad(a[0])) * Math.cos(rad(b[0])) * Math.sin(dl / 2) ** 2;
    return 2 * R * Math.asin(Math.sqrt(h));
  }
  function bearing(a, b) {
    const y = Math.sin(rad(b[1] - a[1])) * Math.cos(rad(b[0]));
    const x = Math.cos(rad(a[0])) * Math.sin(rad(b[0])) - Math.sin(rad(a[0])) * Math.cos(rad(b[0])) * Math.cos(rad(b[1] - a[1]));
    return (deg(Math.atan2(y, x)) + 360) % 360;
  }
  const angleDiff = (a, b) => Math.abs(((a - b + 540) % 360) - 180);
  function locateOnRoute(route, p) {   // -> [offset from route m, distance along route m]
    const k = Math.cos(rad(route[0][0])), proj = (q) => [rad(q[1]) * R * k, rad(q[0]) * R];
    const [px, py] = proj(p);
    let best = [Infinity, 0], along = 0;
    for (let i = 0; i < route.length - 1; i++) {
      const [ax, ay] = proj(route[i]), [bx, by] = proj(route[i + 1]);
      const dx = bx - ax, dy = by - ay, seg = Math.hypot(dx, dy);
      const t = seg ? Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (seg * seg))) : 0;
      const d = Math.hypot(px - (ax + t * dx), py - (ay + t * dy));
      if (d < best[0]) best = [d, along + t * seg];
      along += seg;
    }
    return best;
  }

  // ---------- map ----------
  const map = L.map('map', { zoomControl: false, attributionControl: true }).setView([20.59, 78.96], 5);
  window.potholeMap = map;  // handy in the browser console
  L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19, attribution: '&copy; OpenStreetMap contributors',
  }).addTo(map);
  const layer = L.layerGroup().addTo(map);
  let routeLine = null, startMarker = null, endMarker = null;
  const meMarker = L.marker([0, 0], { icon: L.divIcon({ className: '', html: '<div class="me"></div>', iconSize: [18, 18] }), interactive: false });

  const potholes = new Map();  // id -> pothole
  function popupHtml(p) {
    const seen = p.last_seen ? new Date(p.last_seen).toLocaleDateString() : '—';
    return `<div class="pop sev-${esc(p.severity)}">
      ${p.photo_url ? `<img src="${esc(p.photo_url)}" alt="Pothole photo">` : ''}
      <strong>${esc(damageLabel(p))}</strong><br><span class="sev-chip">${esc(p.severity || 'Unscored')}</span>
      ${p.ride_score != null ? `<span class="meta"> ride impact ${Number(p.ride_score).toFixed(1)}/10</span>` : ''}
      <p>${esc(p.description || 'Pothole')}</p>
      <p class="meta">Seen ${esc(p.times_seen)} times, last on ${esc(seen)}</p>
      <div class="row">
        <button class="btn" data-id="${p.id}" data-fb="still_there">Still there</button>
        <button class="btn" data-id="${p.id}" data-fb="gone">Gone</button>
      </div></div>`;
  }
  function drawPotholes() {
    layer.clearLayers();
    for (const p of potholes.values()) {
      const c = DAMAGE_COLORS[p.damage_type] || '#64748b';
      const type=DAMAGE_LABELS[p.damage_type] ? p.damage_type : 'road_damage';
      L.marker([p.lat,p.lon], {icon:L.icon({iconUrl:'/static/icons/'+type+'.svg',iconSize:[34,34],iconAnchor:[17,17]}),title:damageLabel(p)}).bindPopup(popupHtml(p)).addTo(layer);
    }
  }
  map.on('popupopen', (e) => {
    e.popup.getElement().querySelectorAll('[data-fb]').forEach((b) => {
      b.onclick = () => { sendFeedback(Number(b.dataset.id), b.dataset.fb); map.closePopup(); };
    });
  });

  async function loadNear(pos) {
    try {
      const r = await (await fetch(`/getpdata?lat=${pos[0]}&lon=${pos[1]}&radius_m=3000`)).json();
      for (const p of r.potholes) potholes.set(p.id, p);
      drawPotholes();
      if (mode === 'idle') $('routeMsg').innerHTML = `<b>${r.count}</b> pothole${r.count === 1 ? '' : 's'} within 3 km`;
    } catch { if (mode === 'idle') $('routeMsg').textContent = 'Could not load potholes. Check the connection.'; }
  }

  // ---------- route planning ----------
  let mode = 'idle', start = null, route = null;  // route = {coords, potholes}
  function setMode(m) {
    mode = m;
    $('planBtn').hidden = m !== 'idle';
    $('myLocBtn').hidden = m !== 'pickStart' || !me;
    $('clearBtn').hidden = m === 'idle';
    if (m === 'pickStart') $('routeMsg').textContent = 'Tap the map to set the start.';
    if (m === 'pickEnd') $('routeMsg').textContent = 'Tap the map to set the destination.';
  }
  $('planBtn').onclick = () => { unlockAudio(); clearRoute(); setMode('pickStart'); };
  $('myLocBtn').onclick = () => { if (me) setStart(me); };
  $('clearBtn').onclick = () => { clearRoute(); setMode('idle'); if (me) loadNear(me); };

  function clearRoute() {
    [routeLine, startMarker, endMarker].forEach((l) => l && map.removeLayer(l));
    routeLine = startMarker = endMarker = null; route = null; start = null;
    clearInterval(simTimer);
    $('routeChoices').replaceChildren();
    $('alert').classList.remove('show');
  }
  function setStart(p) {
    start = p;
    startMarker = L.circleMarker(p, { radius: 8, color: '#fff', weight: 3, fillColor: '#4aa3ff', fillOpacity: 1 }).addTo(map);
    setMode('pickEnd');
  }
  map.on('click', async (e) => {
    const p = [e.latlng.lat, e.latlng.lng];
    if (mode === 'pickStart') return setStart(p);
    if (mode !== 'pickEnd') return;
    await planRoute(start, p);
  });

  async function planRoute(a, b) {
    endMarker = L.circleMarker(b, { radius: 8, color: '#fff', weight: 3, fillColor: '#ff7a1a', fillOpacity: 1 }).addTo(map);
    $('routeMsg').textContent = 'Finding the route…';
    try {
      const res = await fetch(`/api/drive/routes?start=${a[0]},${a[1]}&end=${b[0]},${b[1]}`);
      if (!res.ok) throw new Error((await res.json()).detail);
      const options = (await res.json()).routes;
      if (!options.length) throw new Error('No driving route found');
      $('routeChoices').replaceChildren();
      options.forEach((option,index)=>{
        const button=document.createElement('button');
        button.textContent=`Route ${index+1} · ${Math.round(option.duration_s/60)} min · ${(option.distance_m/1000).toFixed(1)} km · ${option.count} recorded road defects`;
        button.onclick=()=>{
          route=option;
          if(routeLine)map.removeLayer(routeLine);
          routeLine=L.polyline(route.coords,{color:'#1967d2',weight:6}).addTo(map);
          map.fitBounds(routeLine.getBounds(),{padding:[60,160]});
          $('routeMsg').textContent=button.textContent;
          for(const ph of route.potholes)potholes.set(ph.id,ph);
          drawPotholes();announced.clear();
          $('routeChoices').querySelectorAll('button').forEach(x=>x.classList.remove('selected'));button.classList.add('selected');
          if(SIM)simulateDrive(route.coords);
        };
        if(index===0)button.classList.add('selected');
        $('routeChoices').append(button);
      });
      route=options[0];
      routeLine = L.polyline(route.coords, { color: '#1967d2', weight: 6, opacity: 0.85 }).addTo(map);
      map.fitBounds(routeLine.getBounds(), { padding: [40, 140] });
      for (const ph of route.potholes) potholes.set(ph.id, ph);
      drawPotholes();
      const km = (route.distance_m / 1000).toFixed(1);
      $('routeMsg').innerHTML = `<b>${route.count}</b> pothole${route.count === 1 ? '' : 's'} on this ${km} km route` +
        (route.severe_count ? `, <b>${route.severe_count}</b> severe` : '');
      setMode('route');
      follow = false; $('followBtn').classList.remove('on');
      if (SIM) simulateDrive(route.coords);
    } catch (err) {
      $('routeMsg').textContent = `No route: ${err.message}`;
      map.removeLayer(endMarker); endMarker = null; setMode('pickEnd');
    }
  }

  // ---------- follow ----------
  let follow = true;
  $('followBtn').onclick = () => {
    follow = !follow; $('followBtn').classList.toggle('on', follow); $('followBtn').setAttribute('aria-pressed', follow);
    if (follow && me) map.setView(me, Math.max(map.getZoom(), 17));
  };
  map.on('dragstart', () => { follow = false; $('followBtn').classList.remove('on'); });

  // ---------- sound + voice ----------
  let audio = null;
  function unlockAudio() { try { audio = audio || new AudioContext(); audio.resume(); } catch { /* none */ } }
  document.addEventListener('pointerdown', unlockAudio, { once: true });
  function beep(times) {
    if (!cfg.beep || !audio) return;
    for (let i = 0; i < times; i++) {
      const o = audio.createOscillator(), g = audio.createGain(), t = audio.currentTime + i * 0.22;
      o.frequency.value = 880; o.connect(g); g.connect(audio.destination);
      g.gain.setValueAtTime(0.25, t); g.gain.exponentialRampToValueAtTime(0.001, t + 0.18);
      o.start(t); o.stop(t + 0.2);
    }
  }
  function say(text) {
    if (!cfg.voice || !('speechSynthesis' in window)) return;
    speechSynthesis.cancel(); speechSynthesis.speak(new SpeechSynthesisUtterance(text));
  }

  // ---------- next pothole + alert ----------
  let me = null, myHeading = null, prev = null, lastLoad = null, current = null, currentDist = null;
  const announced = new Map();  // id -> set of thresholds already announced

  function nextPothole() {
    const minRank = SEV_RANK[cfg.minSev] ?? 0;
    const ok = (p) => (SEV_RANK[p.severity] ?? 1) >= minRank;
    if (route) {
      const [off, myAlong] = locateOnRoute(route.coords, me);
      if (off < 40) {
        let best = null;
        for (const p of route.potholes) {
          if (!ok(p)) continue;
          const d = p.along_route_m - myAlong;
          if (d > -5 && (!best || d < best.d)) best = { p, d: Math.max(0, d) };
        }
        return best;
      }
    }
    // no route (or off route): nearest pothole roughly ahead of us
    let best = null;
    for (const p of potholes.values()) {
      if (!ok(p)) continue;
      const d = dist(me, [p.lat, p.lon]);
      if (d > cfg.threshold * 1.5) continue;
      if (myHeading != null && d > 8 && angleDiff(bearing(me, [p.lat, p.lon]), myHeading) > 50) continue;
      if (!best || d < best.d) best = { p, d };
    }
    return best;
  }

  function updateAlert() {
    const hit = nextPothole();
    // just passed the one we were tracking? ask the driver about it
    if (current && (!hit || hit.p.id !== current.id) && currentDist != null && currentDist < 30) askFeedback(current);
    if (!hit || hit.d > cfg.threshold) { $('alert').classList.remove('show'); current = hit?.p || null; currentDist = hit?.d ?? null; return; }
    const p = hit.p, d = Math.round(hit.d);
    current = p; currentDist = hit.d;
    const el = $('alert');
    el.className = `alert show sev-${p.severity || 'Medium'}`;
    $('aImg').src = p.photo_url || ''; $('aImg').hidden = !p.photo_url;
    $('aSev').textContent = `${damageLabel(p)} · ${p.severity || 'Unscored'}`;
    $('aDesc').textContent = p.description || 'Pothole ahead';
    $('aDist').textContent = d >= 20 ? Math.round(d / 5) * 5 : d;   // calm countdown: 100, 95, 90 …
    // announce once at the threshold and once at half of it
    const done = announced.get(p.id) || new Set();
    for (const t of [cfg.threshold, cfg.threshold / 2]) {
      if (hit.d <= t && !done.has(t)) {
        done.add(t); beep(t === cfg.threshold ? 1 : 2);
        say(`${p.severity && p.severity !== 'Low' ? p.severity + ' ' : ''}${damageLabel(p)} in ${Math.round(t)} meters`);
        break;
      }
    }
    announced.set(p.id, done);
  }

  // ---------- feedback ----------
  let toastFor = null, toastTimer = null;
  function askFeedback(p) {
    toastFor = p; $('toast').classList.add('show');
    clearTimeout(toastTimer); toastTimer = setTimeout(() => $('toast').classList.remove('show'), 9000);
  }
  $('toast').querySelectorAll('[data-fb]').forEach((b) => {
    b.onclick = () => {
      if (b.dataset.fb && toastFor) sendFeedback(toastFor.id, b.dataset.fb);
      $('toast').classList.remove('show');
    };
  });
  async function sendFeedback(id, kind) {
    try {
      const r = await (await fetch('/feedback', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ pothole_id: id, kind }),
      })).json();
      if (r.status === 'repaired') {
        potholes.delete(id);
        if (route) route.potholes = route.potholes.filter((p) => p.id !== id);
        drawPotholes();
      }
    } catch { /* offline: ignore for the prototype */ }
  }

  // ---------- location ----------
  let wakeLock = null;
  async function keepAwake() { try { wakeLock = await navigator.wakeLock?.request('screen'); } catch { /* ignore */ } }
  document.addEventListener('visibilitychange', () => { if (document.visibilityState === 'visible') keepAwake(); });
  keepAwake();

  function onFix(here, gpsHeading, speed) {
    if (gpsHeading != null && !Number.isNaN(gpsHeading) && (speed || 0) > 1) myHeading = gpsHeading;
    else if (prev && dist(prev, here) > 8) myHeading = bearing(prev, here);
    if (!prev || dist(prev, here) > 8) prev = here;
    const first = !me; me = here;
    meMarker.setLatLng(me); if (first) { meMarker.addTo(map); map.setView(me, 16); setMode(mode); }
    else if (follow) map.panTo(me, { animate: true });
    if (!route && (!lastLoad || dist(lastLoad, me) > 1000)) { lastLoad = me; loadNear(me); }
    updateAlert();
  }

  // ---------- simulated drive (open /driver?sim) ----------
  // Instead of GPS, a fake car drives each planned route at 40 km/h, so alerts can be tested at a desk.
  let simTimer = null;
  function simulateDrive(coords) {
    clearInterval(simTimer);
    const STEP = 40 / 3.6 / 2;            // metres per half second at 40 km/h
    let i = 0, along = 0;
    follow = true; $('followBtn').classList.add('on');
    simTimer = setInterval(() => {
      if (!route) { clearInterval(simTimer); return; }
      along += STEP;
      while (i < coords.length - 1 && along > dist(coords[i], coords[i + 1])) { along -= dist(coords[i], coords[i + 1]); i++; }
      if (i >= coords.length - 1) {          // arrived: pause, then drive the route again
        clearInterval(simTimer); setTimeout(() => route && simulateDrive(coords), 3000); return;
      }
      const a = coords[i], b = coords[i + 1], t = along / Math.max(0.01, dist(a, b));
      onFix([a[0] + (b[0] - a[0]) * t, a[1] + (b[1] - a[1]) * t], bearing(a, b), STEP * 2);
    }, 500);
  }

  if (SIM) {
    $('routeMsg').textContent = 'Simulated drive: plan a route and a test car will drive it.';
    fetch('/api/config').then((r) => r.json()).then((c) => {
      if (!c.demo_start || !c.demo_end) return;
      onFix(c.demo_start, null, 0);          // preview server: drive the demo road straight away
      setStart(c.demo_start);
      planRoute(c.demo_start, c.demo_end);
    }).catch(() => {});
  } else {
    let watchId=null;
    const locationButton=document.createElement('button');
    locationButton.id='enableLocationBtn';locationButton.className='btn';locationButton.textContent='Enable location';
    locationButton.setAttribute('aria-label','Enable GPS location');
    $('routeActions').append(locationButton);
    const message=document.createElement('p');message.id='gpsStatus';message.setAttribute('role','status');
    message.style.cssText='margin:4px 0;font-size:12px;line-height:1.4;max-width:100%;overflow-wrap:anywhere';
    $('panel').append(message);
    function gpsError(error){
      locationButton.disabled=false;locationButton.textContent='Retry location';
      if(error.code===1)message.textContent='Location permission blocked. Allow location for this website in your browser or phone settings, then retry.';
      else if(error.code===2)message.textContent='Position unavailable. Turn on phone Location Services and try outdoors.';
      else message.textContent='GPS timed out. Keep this page open, check Location Services, and retry.';
    }
    function gpsFix(pos){
      const c=pos.coords;
      if(!Number.isFinite(c.latitude)||!Number.isFinite(c.longitude))return;
      onFix([c.latitude,c.longitude],c.heading,c.speed);
      message.textContent='Location active · accuracy ±'+Math.round(c.accuracy)+' m';
      locationButton.disabled=false;locationButton.textContent='Recenter';
    }
    function startLocation(){
      if(!window.isSecureContext){message.textContent='Location needs HTTPS on your phone. Open the server using https://, not http://. Localhost only works on the device running the server.';locationButton.textContent='HTTPS required';return;}
      if(!navigator.geolocation){message.textContent='This browser does not provide location access.';return;}
      locationButton.disabled=true;message.textContent='Finding your position… Allow the location prompt.';
      if(me){follow=true;$('followBtn').classList.add('on');map.setView(me,17);}
      if(watchId!==null)navigator.geolocation.clearWatch(watchId);
      navigator.geolocation.getCurrentPosition(gpsFix,gpsError,{enableHighAccuracy:false,maximumAge:30000,timeout:15000});
      watchId=navigator.geolocation.watchPosition(gpsFix,gpsError,{enableHighAccuracy:true,maximumAge:2000,timeout:30000});
      locationButton.disabled=false;
    }
    locationButton.onclick=startLocation;
    if(!window.isSecureContext)message.textContent='GPS unavailable over HTTP. Open this page over HTTPS on your phone.';
    else message.textContent='Tap Enable location and allow access to show your position.';
    window.addEventListener('pagehide',()=>{if(watchId!==null)navigator.geolocation.clearWatch(watchId)});
  }
  setInterval(() => { if (me && !route) loadNear(me); }, 60000);

  let chosenStart=null, chosenEnd=null, searchVersion=0;
  for(const [field,button,kind] of [['startSearch','searchStart','start'],['endSearch','searchEnd','end']]){
    $(field).addEventListener('input',()=>{if(kind==='start')chosenStart=null;else chosenEnd=null;searchVersion++;$('searchResults').replaceChildren()});
    $(field).addEventListener('keydown',e=>{if(e.key==='Enter')$(button).click()});
    $(button).onclick=async()=>{
      const query=$(field).value.trim();const coordinates=query.split(',').map(Number);if(coordinates.length===2&&coordinates.every(Number.isFinite)&&Math.abs(coordinates[0])<=90&&Math.abs(coordinates[1])<=180){if(kind==='start')chosenStart=coordinates;else chosenEnd=coordinates;map.setView(coordinates,15);$('searchMessage').textContent='Coordinates selected.';return}if(query.length<3){$('searchMessage').textContent='Enter at least three characters.';return}
      const version=++searchVersion;$('searchMessage').textContent='Searching…';
      try{
        let response=await fetch('/api/drive/search?q='+encodeURIComponent(query));let data=await response.json();if(!response.ok || !data.results?.length){response=await fetch('/api/drive/search-fallback?q='+encodeURIComponent(query));data=await response.json();}
        if(version!==searchVersion)return;if(!response.ok)throw new Error(data.detail);
        $('searchResults').replaceChildren();
        for(const place of data.results){const item=document.createElement('button');item.textContent=place.label;item.onclick=()=>{
          if(kind==='start')chosenStart=[place.lat,place.lon];else chosenEnd=[place.lat,place.lon];
          $(field).value=place.label;$('searchResults').replaceChildren();map.setView([place.lat,place.lon],14);
        };$('searchResults').append(item)}
        $('searchMessage').textContent=data.results.length?'Choose a search result.':'No locations found. Try a nearby landmark.';
      }catch(e){$('searchMessage').textContent=e.message}
    };
  }
  $('useLocation').onclick=()=>{if(!me){document.getElementById('enableLocationBtn')?.click();$('searchMessage').textContent='Allow location access, then tap Use my location again.';return}chosenStart=[...me];$('startSearch').value='My location'};
  $('findRoutes').onclick=async()=>{
    if(!chosenStart||!chosenEnd){$('searchMessage').textContent='Select both starting point and destination from search results.';return}
    $('findRoutes').disabled=true;
    try{clearRoute();setStart(chosenStart);await planRoute(chosenStart,chosenEnd)}finally{$('findRoutes').disabled=false}
  };
  $('shareDrive').onclick=async()=>{try{await navigator.clipboard.writeText(location.origin+'/drive');$('searchMessage').textContent='Drive-only link copied. Other devices need access to this server.'}catch{$('searchMessage').textContent='Drive-only link: '+location.origin+'/drive'}};

  // Explicit map-pin selection for either route endpoint.
  let pinMode=null, pickedStartMarker=null, pickedEndMarker=null;
  function finishPinMode(){pinMode=null;map.getContainer().style.cursor='';$('cancelPin').hidden=true;}
  function beginPinMode(which){
    pinMode=which;mode='pinSelection';map.getContainer().style.cursor='crosshair';
    $('cancelPin').hidden=false;
    $('searchMessage').textContent='Tap the map to place your '+(which==='start'?'starting point':'destination')+'.';
    $('routeMsg').textContent=$('searchMessage').textContent;
    const toggle=document.getElementById('plannerToggle');
    if(document.getElementById('searchPanel').classList.contains('expanded'))toggle?.click();
  }
  $('dropStart').onclick=()=>beginPinMode('start');
  $('dropEnd').onclick=()=>beginPinMode('end');
  $('cancelPin').onclick=()=>{finishPinMode();mode=route?'route':'idle';$('searchMessage').textContent='Pin placement cancelled.';};
  map.on('click',event=>{
    if(!pinMode)return;
    const point=[event.latlng.lat,event.latlng.lng],which=pinMode;
    const marker=L.marker(point,{draggable:true,title:which==='start'?'Starting point':'Destination'}).addTo(map);
    function apply(position){
      if(which==='start'){chosenStart=position;$('startSearch').value='Dropped pin: '+position.map(v=>v.toFixed(6)).join(', ');}
      else{chosenEnd=position;$('endSearch').value='Dropped pin: '+position.map(v=>v.toFixed(6)).join(', ');}
    }
    if(which==='start'){if(pickedStartMarker)map.removeLayer(pickedStartMarker);pickedStartMarker=marker;}
    else{if(pickedEndMarker)map.removeLayer(pickedEndMarker);pickedEndMarker=marker;}
    apply(point);
    marker.bindTooltip(which==='start'?'Start':'Destination',{permanent:true,direction:'top'});
    marker.on('dragend',()=>{const q=marker.getLatLng();apply([q.lat,q.lng]);$('searchMessage').textContent='Pin moved. Press Find driving routes to update the route.';});
    finishPinMode();mode='idle';
    $('searchMessage').textContent=(which==='start'?'Start':'Destination')+' pin placed. '+(chosenStart&&chosenEnd?'Press Find driving routes.':'Select the other route point.');
    $('routeMsg').textContent=$('searchMessage').textContent;
    const sheet=document.getElementById('searchPanel');if(!sheet.classList.contains('expanded'))document.getElementById('plannerToggle')?.click();
  });
  document.addEventListener('keydown',e=>{if(e.key==='Escape'&&pinMode){finishPinMode();mode='idle';}});
})();
