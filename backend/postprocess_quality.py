"""Conservative recovery and explicit quality reasons for stored detections."""
import math
from datetime import datetime
from . import geo
from .frame_calibration import box_geometry, validate

def timestamp(value):
    try:return datetime.fromisoformat(value.replace('Z','+00:00')).timestamp()
    except (ValueError,TypeError,AttributeError):return None

def recover_heading(d, observations, max_seconds=30):
    """Use a same-device GPS trajectory only when displacement exceeds GPS noise."""
    t=timestamp(d.get('captured_at')); device=d.get('device_id')
    if t is None or not device:return None
    accuracy=d.get('gps_accuracy_m')
    if accuracy is None or accuracy>30:return None
    candidates=[]
    for other in observations:
        ot=timestamp(other.get('captured_at'));oa=other.get('gps_accuracy_m')
        if other.get('device_id')!=device or ot is None or oa is None or oa>30:continue
        dt=ot-t
        if not 1<=abs(dt)<=max_seconds:continue
        distance=geo.haversine_m(d['lat'],d['lon'],other['lat'],other['lon'])
        if distance<max(8,2*(accuracy+oa)) or distance/abs(dt)>45:continue
        a,b=(other,d) if dt<0 else (d,other)
        lat1,lat2=map(math.radians,(a['lat'],b['lat']));dl=math.radians(b['lon']-a['lon'])
        heading=math.degrees(math.atan2(math.sin(dl)*math.cos(lat2),math.cos(lat1)*math.sin(lat2)-math.sin(lat1)*math.cos(lat2)*math.cos(dl)))%360
        candidates.append((abs(dt),heading))
    if not candidates:return None
    candidates.sort()
    angles=[h for _,h in candidates[:4]]
    if any(abs((h-angles[0]+180)%360-180)>25 for h in angles):return None
    return angles[0]

def locate(d, observations, max_distance=25, max_accuracy=30):
    d=dict(d)
    calibration=d.get("_calibration")
    if calibration:
        try: calibration=validate(calibration)
        except (KeyError, ValueError, TypeError): return None,"invalid_calibration"
        d["heading_deg"]=calibration["heading_deg"]
        d["camera_height_m"]=calibration["height_m"]
        d["hfov_deg"]=calibration["hfov_deg"]
        d["camera_tilt_deg"]=0  # calibrated plane replaces the legacy tilt below
    for key in ('lat','lon','img_w','img_h','x1','y1','x2','y2','camera_height_m','camera_tilt_deg','hfov_deg','confidence'):
        value=d.get(key)
        if value is None or not math.isfinite(value):return None,'invalid_metadata'
    if not (-90<=d['lat']<=90 and -180<=d['lon']<=180):return None,'invalid_coordinates'
    if d['img_w']<=0 or d['img_h']<=0 or d['camera_height_m']<=0 or not 0<d['hfov_deg']<180:return None,'invalid_camera_settings'
    if not (0<=d['x1']<d['x2']<=d['img_w'] and 0<=d['y1']<d['y2']<=d['img_h']):return None,'invalid_box'
    accuracy=d.get('gps_accuracy_m')
    if accuracy is not None and (not math.isfinite(accuracy) or accuracy<0 or accuracy>max_accuracy):return None,'poor_gps'
    heading=d.get('heading_deg'); recovered=False
    if heading is None or not math.isfinite(heading):
        heading=recover_heading(d,observations);recovered=heading is not None
    if heading is None:return None,'missing_heading'
    g=box_geometry(d,calibration) if calibration else geo.box_to_ground((d['x1'],d['y1'],d['x2'],d['y2']),d['img_w'],d['img_h'],d['camera_height_m'],d['camera_tilt_deg'],d['hfov_deg'])
    if g is None:return None,'unprojectable_box'
    if g['forward_m']>max_distance:return None,'too_far'
    lat,lon=geo.offset_latlon(d['lat'],d['lon'],g['forward_m'],g['lateral_m'],heading)
    weight=d['confidence']/max(3,accuracy or 10)/(1+g['forward_m']/15)
    if recovered:weight*=0.5
    return {**d,**g,'heading_deg':heading,'heading_recovered':recovered,'p_lat':lat,'p_lon':lon,'weight':max(weight,1e-9)},None
