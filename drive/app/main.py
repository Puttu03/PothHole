"""Standalone Drive: shared published data, independent browser routes, reviewable feedback."""
import asyncio, math, os, sqlite3, time, uuid
from contextlib import contextmanager
from pathlib import Path
from urllib.parse import quote
import httpx
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from . import geo
ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.getenv('DRIVE_DATA_DIR',str(ROOT/'data')))
FEEDBACK_DIR = Path(os.getenv('DRIVE_FEEDBACK_DIR', str(DATA)))
app=FastAPI(title='RoadPlotter Drive')
app.mount('/static',StaticFiles(directory=ROOT/'frontend'),name='static')
@contextmanager
def snapshot():
    path=DATA/'road_data.sqlite'
    if not path.exists():raise HTTPException(503,'No published data. Run export_drive_data.py first.')
    conn=sqlite3.connect(path.resolve().as_uri()+'?mode=ro',uri=True,timeout=10)
    conn.row_factory=sqlite3.Row
    try:yield conn
    finally:conn.close()
def rows():
    with snapshot() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM potholes WHERE status='open' ORDER BY id LIMIT 10001")]
def records():
    data=rows()
    if len(data)>10000:raise HTTPException(503,'Dataset exceeds this deployment limit; partition data or upgrade the spatial backend.')
    return [{**{k:v for k,v in p.items() if k in ('id','lat','lon','severity','description','damage_type','times_seen','ride_score','loc_accuracy_m','width_m','area_m2','surface','lane_position','status','last_seen')},'photo_url':None,'full_photo_url':None} for p in data]
@app.get('/')
def home():return RedirectResponse('/drive')
@app.get('/drive')
@app.get('/driver')
def drive():return FileResponse(ROOT/'frontend'/'driver.html')
@app.get('/health')
def health():
    with snapshot() as c:c.execute('SELECT id FROM potholes LIMIT 1').fetchone()
    return {'status':'ok','mode':'drive-only'}
@app.get('/api/config')
def config():return {'mode':'drive-only','anonymous_visitors':True}
@app.get('/getpdata')
def nearby(lat:float|None=None,lon:float|None=None,radius_m:float=Query(5000,gt=0,le=50000)):
    if (lat is None)!=(lon is None):raise HTTPException(400,'Provide both latitude and longitude.')
    if lat is not None:point(f'{lat},{lon}')
    result=records()
    if lat is not None:result=[p for p in result if geo.haversine_m(lat,lon,p['lat'],p['lon'])<=radius_m]
    return {'count':len(result),'potholes':result}
def point(value):
    try:
        lat,lon=map(float,value.split(','))
        if not(math.isfinite(lat) and math.isfinite(lon) and -90<=lat<=90 and -180<=lon<=180):raise ValueError()
        return lat,lon
    except (ValueError,TypeError):raise HTTPException(400,'Expected valid latitude,longitude.')
# Bound provider concurrency and cache duplicate lookups within each worker.
lock=asyncio.Lock();cache={};slots=asyncio.Semaphore(4)
async def remote(url,params):
    key=(url,tuple(sorted(params.items())))
    async with lock:
        item=cache.get(key)
        if item and item[0]>time.monotonic():return item[1]
    try:
        async with slots:
            async with httpx.AsyncClient(timeout=15) as client:
                response=await client.get(url,params=params,headers={'User-Agent':'RoadPlotter-Drive/1.0'})
                response.raise_for_status();data=response.json()
    except (httpx.HTTPError,ValueError) as exc:raise HTTPException(502,'Map provider unavailable. Try again or use drop pins.') from exc
    async with lock:
        if len(cache)>=256:cache.pop(next(iter(cache)))
        cache[key]=(time.monotonic()+60,data)
    return data
@app.get('/api/drive/search')
@app.get('/api/drive/search-fallback')
async def search(q:str=Query(...,min_length=3,max_length=160)):
    data=await remote(os.getenv('PHOTON_URL','https://photon.komoot.io/api/'),{'q':q,'limit':8,'lang':'en','bbox':'68,6,98,38'})
    results=[]
    for f in data.get('features',[]):
        props=f.get('properties',{});lon,lat=f['geometry']['coordinates'][:2]
        if not(68<=lon<=98 and 6<=lat<=38):continue
        label=', '.join(dict.fromkeys(str(props[k]) for k in ('name','street','city','state','country') if props.get(k)))
        results.append({'label':label,'lat':lat,'lon':lon})
    return {'results':results}
@app.get('/api/drive/routes')
async def routes(start:str,end:str):
    a,b=point(start),point(end)
    url=os.getenv('OSRM_URL','https://router.project-osrm.org').rstrip('/')+f'/route/v1/driving/{a[1]},{a[0]};{b[1]},{b[0]}'
    data=await remote(url,{'overview':'full','geometries':'geojson','alternatives':'true'})
    if data.get('code')!='Ok' or not data.get('routes'):raise HTTPException(404,'No driving route found.')
    damage=await asyncio.to_thread(records)
    def assemble():
        choices=[]
        for r in data['routes'][:3]:
            coords=[[lat,lon] for lon,lat in r['geometry']['coordinates']]
            hits=[]
            # Bounding-box prefilter keeps unrelated records out of expensive segment tests.
            lats=[p[0] for p in coords];lons=[p[1] for p in coords]
            pad_lat=35/111000;pad_lon=35/(111000*max(.01,math.cos(math.radians(sum(lats)/len(lats)))))
            for p in damage:
                if not(min(lats)-pad_lat<=p['lat']<=max(lats)+pad_lat and min(lons)-pad_lon<=p['lon']<=max(lons)+pad_lon):continue
                distance,along=geo.locate_on_route(coords,p['lat'],p['lon'])
                if distance<=30:hits.append({**p,'route_offset_m':round(distance,1),'along_route_m':round(along,1)})
            hits.sort(key=lambda x:x['along_route_m'])
            choices.append({'coords':coords,'distance_m':r['distance'],'duration_s':r['duration'],'potholes':hits,'count':len(hits),'severe_count':sum(p.get('severity') in ('High','Critical') for p in hits)})
        return {'routes':choices}
    return await asyncio.to_thread(assemble)
class Feedback(BaseModel):
    pothole_id:int
    kind:str
@app.post('/feedback')
def feedback(fb:Feedback,request:Request):
    if request.headers.get('sec-fetch-site')=='cross-site':raise HTTPException(403,'Cross-site feedback rejected.')
    if fb.kind not in ('still_there','gone'):raise HTTPException(400,'Invalid feedback type.')
    with snapshot() as c:
        row=c.execute('SELECT status FROM potholes WHERE id=?',(fb.pothole_id,)).fetchone()
        if row is None:raise HTTPException(404,'Unknown record.')
    visitor=request.cookies.get('drive_visitor','')
    try:visitor=str(uuid.UUID(visitor))
    except ValueError:visitor=str(uuid.uuid4())
    with sqlite3.connect(FEEDBACK_DIR/'feedback.sqlite',timeout=15) as c:
        c.execute('PRAGMA journal_mode=WAL')
        c.execute('CREATE TABLE IF NOT EXISTS reports(visitor TEXT, pothole_id INTEGER, kind TEXT, updated_at TEXT DEFAULT CURRENT_TIMESTAMP, PRIMARY KEY(visitor,pothole_id))')
        c.execute('INSERT INTO reports(visitor,pothole_id,kind) VALUES(?,?,?) ON CONFLICT(visitor,pothole_id) DO UPDATE SET kind=excluded.kind,updated_at=CURRENT_TIMESTAMP',(visitor,fb.pothole_id,fb.kind))
    from fastapi.responses import JSONResponse
    response=JSONResponse({'status':row['status'],'feedback':'queued_for_review'})
    response.set_cookie('drive_visitor',visitor,httponly=True,samesite='lax',secure=request.url.scheme=='https',max_age=31536000)
    return response
