"""Run beside run.py: python review_handheld.py. Stop the main app first."""
import argparse
from datetime import datetime, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import math
from pathlib import Path
import secrets
import sqlite3
import sys
from urllib.parse import urlparse, parse_qs
import webbrowser

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from backend.config import settings
from backend.frame_calibration import FIELDS, attach, validate, ensure_schema
from backend.postprocess_quality import locate

PAGE = r'''<!doctype html><html lang="en"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Review handheld frames</title>
<style>*{box-sizing:border-box}body{margin:0;background:#f0f4f8;color:#182435;font:16px system-ui}main{max-width:1150px;margin:auto;padding:20px}h1{margin:0}p{line-height:1.5}.layout{display:grid;grid-template-columns:minmax(260px,1fr) minmax(300px,1fr);gap:24px}canvas{width:100%;max-height:75vh;object-fit:contain;background:#17202b}section{background:white;padding:18px;border-radius:16px}label{display:block;margin:12px 0}input,select,button{font:inherit;padding:10px;border:1px solid #acb9c9;border-radius:8px;max-width:100%}select{width:100%}input{width:100%}button{background:#1954c7;color:white;cursor:pointer;margin:8px 6px 0 0}button:disabled{opacity:.45;cursor:default}pre{white-space:pre-wrap;background:#f0f4f8;padding:12px}#message{font-weight:600}small{display:block;line-height:1.5}@media(max-width:700px){.layout{grid-template-columns:1fr}canvas{max-height:60vh}}</style>
<main><h1>Review handheld recordings</h1><p>Stop RoadPlotter while reviewing. Corrections apply to this photo’s unassigned sightings only. Original capture metadata and existing map records are preserved.</p>
<select id="frames" aria-label="Select photo"></select><p id="message" role="status"></p>
<div class="layout"><section><button id="rotateLeft">↶ Rotate left</button><button id="rotateRight">↷ Rotate right</button><p id="rotationInfo">Rotation: 0°</p><canvas id="canvas"></canvas><small>Orange: saved detector boxes. Cyan: your horizon line. Set the road-plane horizon, not the treetops or skyline. If you cannot determine it, leave this frame deferred.</small></section>
<section><h2>Per-photo calibration</h2><p>For a sloping horizon, set each endpoint separately. Values are percentages of image height; 0% is the top.</p>
<label>Horizon at left edge (%)<input id="left" type="number" min="-100" max="200" step="0.1"></label>
<label>Horizon at right edge (%)<input id="right" type="number" min="-100" max="200" step="0.1"></label>
<label>Camera height above road (metres)<input id="height" type="number" min="0.2" max="4" step="0.01"></label>
<label>FOV across ORIGINAL saved image width (degrees; unchanged by rotation)<input id="fov" type="number" min="10" max="150" step="0.1"></label>
<label>Camera forward heading (degrees clockwise from north)<input id="heading" type="number" min="0" max="360" step="0.1"></label>
<small>The prefilled heading is from capture metadata. Verify it: travel direction may differ from where a handheld camera points. FOV must match portrait/landscape capture and any crop. A guessed horizon cannot guarantee a correct location.</small>
<button id="preview">Preview projection</button><button id="save" disabled>Save correction &amp; queue retry</button><button id="next">Next photo</button>
<pre id="results">Choose a frame to begin.</pre><p>Saving does not run AI. After reviewing, close this tool, start RoadPlotter and run post-processing. Distant or invalid boxes remain deferred; confirmation thresholds stay unchanged.</p></section></div></main>
<script>
const token=__TOKEN__;const $=id=>document.getElementById(id);let rows=[],selected=null,img=null,validPreview=false,rotation=0;
async function api(path,body){const r=await fetch(path,body?{method:'POST',headers:{'Content-Type':'application/json','X-Review-Token':token},body:JSON.stringify(body)}:{});const d=await r.json();if(!r.ok)throw Error(d.error||r.statusText);return d}
function error(e){$('message').textContent=e.message;$('save').disabled=true}
function values(){for(const id of ['left','right','height','fov','heading'])if($(id).value.trim()==='')throw Error('Fill every calibration field.');return {rotation_deg:rotation,horizon_left:Number($('left').value)/100,horizon_right:Number($('right').value)/100,height_m:Number($('height').value),hfov_deg:Number($('fov').value),heading_deg:Number($('heading').value)}}
function rotateBox(d){const w=d.img_w,h=d.img_h;let b=[d.x1,d.y1,d.x2,d.y2];if(rotation===90)b=[h-d.y2,d.x1,h-d.y1,d.x2];if(rotation===180)b=[w-d.x2,h-d.y2,w-d.x1,h-d.y1];if(rotation===270)b=[d.y1,w-d.x2,d.y2,w-d.x1];return {b,w:rotation%180?h:w,h:rotation%180?w:h}}
function draw(){if(!img)return;const c=$('canvas'),x=c.getContext('2d'),w=img.naturalWidth,h=img.naturalHeight;
c.width=rotation%180?h:w;c.height=rotation%180?w:h;x.save();if(rotation===90){x.translate(h,0);x.rotate(Math.PI/2)}if(rotation===180){x.translate(w,h);x.rotate(Math.PI)}if(rotation===270){x.translate(0,w);x.rotate(-Math.PI/2)}x.drawImage(img,0,0);x.restore();
x.lineWidth=Math.max(2,c.width/350);x.strokeStyle='#ff8c22';x.fillStyle='#ff8c22';x.font=`${Math.max(16,c.width/45)}px system-ui`;for(const d of rows){const r=rotateBox(d),b=r.b,sx=c.width/r.w,sy=c.height/r.h;x.strokeRect(b[0]*sx,b[1]*sy,(b[2]-b[0])*sx,(b[3]-b[1])*sy);x.fillText('#'+d.id,b[0]*sx,Math.max(25,b[1]*sy-8))}
x.strokeStyle='#00e5ff';if($('left').value!==''&&$('right').value!==''){x.beginPath();x.moveTo(0,Number($('left').value)*c.height/100);x.lineTo(c.width,Number($('right').value)*c.height/100);x.stroke()}$('rotationInfo').textContent=`Rotation: ${rotation}° clockwise`}
function turn(degrees){rotation=(rotation+degrees+360)%360;validPreview=false;$('save').disabled=true;$('left').value='';$('right').value='';$('results').textContent='Orientation changed. Set both horizon values for this upright view, then preview. FOV and compass heading are unchanged.';draw()}
$('rotateLeft').onclick=()=>turn(-90);$('rotateRight').onclick=()=>turn(90);

async function load(){selected=Number($('frames').value);if(!selected)return;validPreview=false;$('save').disabled=true;img=null;rows=await api('/frame?id='+selected);const d=rows[0];const c=d._calibration;rotation=c?.rotation_deg||0;const f=d.img_w/(2*Math.tan(d.hfov_deg*Math.PI/360));const y=(d.img_h/2-f*Math.tan(d.camera_tilt_deg*Math.PI/180))/d.img_h;
$('left').value=((c?c.horizon_left:y)*100).toFixed(2);$('right').value=((c?c.horizon_right:y)*100).toFixed(2);$('height').value=c?c.height_m:d.camera_height_m;$('fov').value=c?c.hfov_deg:d.hfov_deg;$('heading').value=c?c.heading_deg:(d.heading_deg??'');$('results').textContent='Review this frame, then preview.';$('message').textContent=d.photo_path;
const image=new Image();image.onload=()=>{img=image;draw()};image.onerror=()=>error(Error('Original photo missing. Restore it under data/photos before reviewing.'));image.src='/photo?id='+selected;}
for(const id of ['left','right','height','fov','heading'])$(id).oninput=()=>{validPreview=false;$('save').disabled=true;draw()};
$('frames').onchange=()=>load().catch(error);
$('preview').onclick=async()=>{try{if(!img)throw Error('Photo must load before preview.');const snapshot=JSON.stringify({id:selected,calibration:values()});const r=await api('/preview',JSON.parse(snapshot));if(snapshot!==JSON.stringify({id:selected,calibration:values()}))return;$('results').textContent=r.results.map(x=>'#'+x.id+': '+((x.reason==='unprojectable_box'?'Box crosses or lies above the configured road horizon. Check rotation and calibration.':x.reason)||`projectable; ${x.distance_m.toFixed(1)} m ahead (estimate)`)).join('\n');validPreview=r.results.some(x=>!x.reason);$('save').disabled=!validPreview}catch(e){error(e)}};
$('save').onclick=async()=>{try{if(!validPreview)return;$('save').disabled=true;const r=await api('/save',{id:selected,calibration:values()});validPreview=false;$('message').textContent=`Saved ${r.queued} sightings for retry. Backup: ${r.backup}`;}catch(e){error(e)}};
$('next').onclick=()=>{const s=$('frames');if(s.selectedIndex<s.options.length-1){s.selectedIndex++;load().catch(error)}};
(async()=>{const fs=await api('/frames');for(const f of fs){const o=document.createElement('option');o.value=f.id;o.textContent=`${f.count} sightings — ${f.photo_path}`;$('frames').append(o)}if(fs.length)await load();else $('message').textContent='No unassigned sightings found.'})().catch(error);
</script></html>'''

class Review:
    def __init__(self, database, photos):
        self.database = Path(database).resolve()
        self.photos = Path(photos).resolve()
        if not self.database.is_file(): raise ValueError(f'Database not found: {self.database}')
        self.backup = None

    def connect(self):
        c=sqlite3.connect(str(self.database),timeout=10)
        c.row_factory=sqlite3.Row
        return c

    def rows(self,c,identifier):
        row=c.execute('SELECT photo_path FROM detections WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ValueError('Unknown detection')
        rows=[dict(r) for r in c.execute('SELECT * FROM detections WHERE photo_path=? AND pothole_id IS NULL ORDER BY id',(row['photo_path'],))]
        if not rows: raise ValueError('This photo has no unassigned sightings')
        return attach(c,rows)

    def preview(self,c,identifier,calibration):
        calibration=validate(calibration)
        rows=self.rows(c,identifier)
        observations=[dict(r) for r in c.execute('SELECT * FROM detections')]
        results=[]
        for d in rows:
            item,reason=locate({**d,'_calibration':calibration},observations,settings.MAX_DETECTION_DIST_M,30)
            results.append(dict(id=d['id'],reason=reason,distance_m=item['forward_m'] if item else None))
        return rows,calibration,results

    def save(self,identifier,calibration):
        c=self.connect()
        try:
            rows,values,results=self.preview(c,identifier,calibration)
            if not any(r['reason'] is None for r in results): raise ValueError('No projectable sightings; correction was not saved')
            if self.backup is None:
                folder=self.database.parent/'backups';folder.mkdir(exist_ok=True)
                backup=folder/('before_handheld_'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%f')+'.db')
                dest=sqlite3.connect(str(backup))
                try: c.backup(dest)
                finally: dest.close()
                self.backup=str(backup)
            c.execute('BEGIN IMMEDIATE')
            # Only unassigned detections may be retried: never duplicate existing map entries.
            current=self.rows(c,identifier)
            if {r['id'] for r in current}!={r['id'] for r in rows}: raise ValueError('Records changed; stop the app and preview again')
            ensure_schema(c)
            now=datetime.now(timezone.utc).isoformat()
            for d in rows:
                c.execute('INSERT OR REPLACE INTO frame_calibration (detection_id,horizon_left,horizon_right,height_m,hfov_deg,heading_deg,updated_at,rotation_deg) VALUES (?,?,?,?,?,?,?,?)',(d['id'],*(values[k] for k in FIELDS),now,values['rotation_deg']))
                c.execute('UPDATE detections SET processed=0,process_note=NULL WHERE id=? AND pothole_id IS NULL',(d['id'],))
            c.commit()
            return dict(queued=len(rows),backup=self.backup)
        except Exception:
            c.rollback();raise
        finally: c.close()


def serve(review,port):
    token=secrets.token_urlsafe(32)
    class Handler(BaseHTTPRequestHandler):
        def send(self,status,body,kind='application/json'):
            if kind=='application/json': body=json.dumps(body,allow_nan=False).encode()
            self.send_response(status);self.send_header('Content-Type',kind);self.send_header('Content-Length',str(len(body)));self.send_header('Cache-Control','no-store');self.send_header('X-Content-Type-Options','nosniff');self.end_headers();self.wfile.write(body)
        def do_GET(self):
            try:
                if self.headers.get('Host') not in (f'127.0.0.1:{port}',f'localhost:{port}'): return self.send(403,{'error':'Local access only'})
                url=urlparse(self.path)
                if url.path=='/':return self.send(200,PAGE.replace('__TOKEN__',json.dumps(token)).encode(),'text/html; charset=utf-8')
                c=review.connect()
                try:
                    if url.path=='/frames':return self.send(200,[dict(r) for r in c.execute('SELECT MIN(id) id,photo_path,COUNT(*) count FROM detections WHERE pothole_id IS NULL GROUP BY photo_path ORDER BY MIN(id)')])
                    identifier=int(parse_qs(url.query)['id'][0]);rows=review.rows(c,identifier)
                    if url.path=='/frame':return self.send(200,rows)
                    if url.path=='/photo':
                        photo=(review.photos/rows[0]['photo_path']).resolve()
                        if review.photos not in photo.parents:raise ValueError('Invalid photo path')
                        return self.send(200,photo.read_bytes(),'image/jpeg')
                    self.send(404,{'error':'Not found'})
                finally:c.close()
            except (ValueError,KeyError,OSError,sqlite3.Error) as e:self.send(400,{'error':str(e)})
        def do_POST(self):
            if self.headers.get('X-Review-Token')!=token:return self.send(403,{'error':'Invalid review token'})
            try:
                size=int(self.headers.get('Content-Length','0'))
                if not 0<size<8192:raise ValueError('Invalid request size')
                data=json.loads(self.rfile.read(size));identifier=int(data['id'])
                if self.path=='/save':return self.send(200,review.save(identifier,data['calibration']))
                if self.path!='/preview':return self.send(404,{'error':'Not found'})
                c=review.connect()
                try: _,_,results=review.preview(c,identifier,data['calibration'])
                finally:c.close()
                self.send(200,{'results':results})
            except (ValueError,KeyError,TypeError,OSError,sqlite3.Error) as e:self.send(400,{'error':str(e)})
        def log_message(self,*args):pass
    server=HTTPServer(('127.0.0.1',port),Handler)
    url=f'http://127.0.0.1:{port}/'
    print(f'Handheld review: {url}\nStop RoadPlotter before saving. Ctrl+C to exit.\nDatabase: {review.database}',flush=True)
    webbrowser.open(url)
    try:server.serve_forever()
    except KeyboardInterrupt:pass
    finally:server.server_close()

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--db',default=str(settings.DB_PATH))
    parser.add_argument('--photos',default=str(settings.PHOTOS_DIR))
    parser.add_argument('--port',type=int,default=8766)
    args=parser.parse_args()
    serve(Review(args.db,args.photos),args.port)
