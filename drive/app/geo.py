"""Flat-road geometry used by the post-process notebook and the server.

Conventions
- tilt_deg: how far the camera points BELOW the horizon (positive = down).
- hfov_deg: horizontal field of view of the frame as sent (not the full sensor).
- bearing: degrees clockwise from north (GPS heading).
- forward d: metres ahead of the phone; lateral s: metres to the right (+) / left (-).
"""
import math

EARTH_R = 6_371_000.0


def _focal(img_w, img_h, hfov_deg):
    fx = (img_w / 2) / math.tan(math.radians(hfov_deg) / 2)
    return fx, fx  # square pixels: fy == fx


def pixel_to_ground(u, v, img_w, img_h, cam_h, tilt_deg, hfov_deg):
    """Ground position of pixel (u, v). Returns (forward_m, lateral_m) or None
    if the pixel is at/above the horizon."""
    fx, fy = _focal(img_w, img_h, hfov_deg)
    cx, cy = img_w / 2, img_h / 2
    alpha = math.atan((v - cy) / fy)                 # below optical axis
    depression = math.radians(tilt_deg) + alpha      # below horizon
    if depression <= math.radians(1.0):
        return None
    slant = cam_h / math.sin(depression)             # camera -> ground point
    forward = cam_h / math.tan(depression)
    lateral = (u - cx) / fx * slant * math.cos(alpha)  # pinhole: x/f = X/Z
    return forward, lateral


def box_to_ground(box, img_w, img_h, cam_h, tilt_deg, hfov_deg):
    """Use the bottom-centre of the box (where the pothole touches the road).
    Returns dict(forward_m, lateral_m, width_m, depth_m, area_m2) or None."""
    x1, y1, x2, y2 = box
    bottom = pixel_to_ground((x1 + x2) / 2, y2, img_w, img_h, cam_h, tilt_deg, hfov_deg)
    top = pixel_to_ground((x1 + x2) / 2, y1, img_w, img_h, cam_h, tilt_deg, hfov_deg)
    left = pixel_to_ground(x1, y2, img_w, img_h, cam_h, tilt_deg, hfov_deg)
    right = pixel_to_ground(x2, y2, img_w, img_h, cam_h, tilt_deg, hfov_deg)
    if not (bottom and left and right):
        return None
    width = abs(right[1] - left[1])
    depth = (top[0] - bottom[0]) if top else width   # along-road extent
    depth = max(0.05, min(depth, 3 * width + 0.5))   # clamp perspective blow-ups
    # centre of the pothole: halfway into its along-road extent
    return {
        "forward_m": bottom[0] + depth / 2,
        "lateral_m": bottom[1],
        "width_m": width,
        "depth_m": depth,
        "area_m2": math.pi / 4 * width * depth,      # ellipse approximation
    }


def offset_latlon(lat, lon, forward_m, lateral_m, bearing_deg):
    """Move (lat, lon) forward along bearing and sideways to the right."""
    b = math.radians(bearing_deg)
    north = forward_m * math.cos(b) - lateral_m * math.sin(b)
    east = forward_m * math.sin(b) + lateral_m * math.cos(b)
    dlat = north / EARTH_R
    dlon = east / (EARTH_R * math.cos(math.radians(lat)))
    return lat + math.degrees(dlat), lon + math.degrees(dlon)


def haversine_m(lat1, lon1, lat2, lon2):
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_R * math.asin(math.sqrt(a))


def bbox_around(lat, lon, radius_m):
    dlat = math.degrees(radius_m / EARTH_R)
    dlon = math.degrees(radius_m / (EARTH_R * math.cos(math.radians(lat))))
    return lat - dlat, lat + dlat, lon - dlon, lon + dlon


def lane_position(lateral_m):
    if lateral_m < -1.5:
        return "left of lane"
    if lateral_m < -0.4:
        return "left wheel path"
    if lateral_m <= 0.4:
        return "lane centre"
    if lateral_m <= 1.5:
        return "right wheel path"
    return "right of lane"


# ---------- route helpers (local flat projection, fine for city-scale routes) ----------
def _project(lat, lon, lat0):
    k = math.cos(math.radians(lat0))
    return math.radians(lon) * EARTH_R * k, math.radians(lat) * EARTH_R


def locate_on_route(route, lat, lon):
    """route: list of [lat, lon]. Returns (distance_from_route_m, along_route_m)."""
    lat0 = route[0][0]
    px, py = _project(lat, lon, lat0)
    best = (float("inf"), 0.0)
    along = 0.0
    for (alat, alon), (blat, blon) in zip(route, route[1:]):
        ax, ay = _project(alat, alon, lat0)
        bx, by = _project(blat, blon, lat0)
        dx, dy = bx - ax, by - ay
        seg = math.hypot(dx, dy)
        t = 0.0 if seg == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / seg**2))
        qx, qy = ax + t * dx, ay + t * dy
        dist = math.hypot(px - qx, py - qy)
        if dist < best[0]:
            best = (dist, along + t * seg)
        along += seg
    return best
