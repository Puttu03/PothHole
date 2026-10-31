"""Explicit per-detection calibration; never overwrite original capture metadata."""
import math

SCHEMA = '''CREATE TABLE IF NOT EXISTS frame_calibration (
 detection_id INTEGER PRIMARY KEY, horizon_left REAL NOT NULL,
 horizon_right REAL NOT NULL, height_m REAL NOT NULL, hfov_deg REAL NOT NULL,
 heading_deg REAL NOT NULL, updated_at TEXT NOT NULL)'''
FIELDS = ('horizon_left', 'horizon_right', 'height_m', 'hfov_deg', 'heading_deg')


def validate(values):
    result = {key: float(values[key]) for key in FIELDS}
    limits = ((-1, 2), (-1, 2), (0.2, 4), (10, 150), (0, 360))
    for (key, value), (lo, hi) in zip(result.items(), limits):
        if not math.isfinite(value) or not lo <= value <= hi:
            raise ValueError(f'{key} must be between {lo} and {hi}')
    rotation = float(values.get('rotation_deg', 0))
    if rotation not in (0, 90, 180, 270):
        raise ValueError('rotation_deg must be 0, 90, 180 or 270 clockwise')
    result['rotation_deg'] = int(rotation)
    return result


def ensure_schema(conn):
    conn.execute(SCHEMA)
    columns = {r[1] for r in conn.execute('PRAGMA table_info(frame_calibration)')}
    if 'rotation_deg' not in columns:
        conn.execute('ALTER TABLE frame_calibration ADD COLUMN rotation_deg INTEGER NOT NULL DEFAULT 0')


def rotated_detection(d, rotation):
    """Rotate pixel-boundary coordinates clockwise, leaving input unchanged."""
    w, h = d['img_w'], d['img_h']
    x1, y1, x2, y2 = (d[k] for k in ('x1', 'y1', 'x2', 'y2'))
    if rotation == 90:
        box = (h-y2, x1, h-y1, x2)
    elif rotation == 180:
        box = (w-x2, h-y2, w-x1, h-y1)
    elif rotation == 270:
        box = (y1, w-x2, y2, w-x1)
    elif rotation == 0:
        box = (x1, y1, x2, y2)
    else:
        raise ValueError('Invalid rotation')
    return {**d, 'img_w': h if rotation % 180 else w,
            'img_h': w if rotation % 180 else h,
            **dict(zip(('x1','y1','x2','y2'), box))}


def attach(conn, rows):
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='frame_calibration'").fetchone():
        return rows
    corrections = {r['detection_id']: dict(r) for r in conn.execute('SELECT * FROM frame_calibration')}
    return [{**r, '_calibration': corrections[r['id']]} if r['id'] in corrections else r for r in rows]


def box_geometry(d, calibration):
    """Intersect camera rays with a plane defined by the manually reviewed horizon.

    Horizon heights are fractions of the rotated frame height at x=0 and x=width.
    Works with sloped horizons (camera roll). Assumes square pixels, flat road,
    known horizontal FOV and perpendicular camera height above that plane.
    """
    c = validate(calibration)
    # FOV is always measured along the ORIGINAL saved image width.
    # Rotation swaps dimensions but preserves focal length in pixels.
    f = d['img_w'] / (2 * math.tan(math.radians(c['hfov_deg']) / 2))
    d = rotated_detection(d, c['rotation_deg'])
    w, h = d['img_w'], d['img_h']
    intercept = c['horizon_left'] * h
    slope = (c['horizon_right'] - c['horizon_left']) * h / w
    normal = [-slope*f, f, h/2 - slope*w/2 - intercept]
    def unit(v):
        length = math.sqrt(sum(x*x for x in v))
        return [x/length for x in v]
    def dot(a,b): return sum(x*y for x,y in zip(a,b))
    n = unit(normal)
    forward = unit([-n[0]*n[2], -n[1]*n[2], 1-n[2]*n[2]])
    right = [n[1]*forward[2]-n[2]*forward[1], n[2]*forward[0]-n[0]*forward[2], n[0]*forward[1]-n[1]*forward[0]]
    def point(u,v):
        ray = [(u-w/2)/f, (v-h/2)/f, 1]
        den = dot(n,ray)
        if den <= math.sin(math.radians(1))*math.sqrt(dot(ray,ray)):
            return None
        scale = c['height_m']/den
        return scale*dot(ray,forward), scale*dot(ray,right)
    x1,y1,x2,y2 = (d[k] for k in ('x1','y1','x2','y2'))
    bottom, top = point((x1+x2)/2,y2), point((x1+x2)/2,y1)
    left,right_pt = point(x1,y2),point(x2,y2)
    if any(p is None for p in (bottom,top,left,right_pt)):
        return None  # do not invent size for a box crossing the horizon
    width = math.dist(left,right_pt)
    depth = max(0.05,min(abs(top[0]-bottom[0]),3*width+0.5))
    forward_m = bottom[0]+depth/2
    if forward_m < 0:
        return None
    return dict(forward_m=forward_m,lateral_m=bottom[1],width_m=width,
                depth_m=depth,area_m2=math.pi/4*width*depth)
