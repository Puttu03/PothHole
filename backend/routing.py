"""Route from A to B via OSRM, plus the potholes that lie on it."""
import httpx

from . import db, geo
from .config import settings


async def get_routes(start, end):
    """start/end: (lat, lon). Returns dict(coords=[[lat, lon], ...], distance_m, duration_s)."""
    url = (f"{settings.OSRM_URL}/route/v1/driving/"
           f"{start[1]},{start[0]};{end[1]},{end[0]}?overview=full&geometries=geojson&alternatives=true")
    async with httpx.AsyncClient(timeout=15) as client:
        r = await client.get(url, headers={"User-Agent": "pothole-cloud-prototype"})
        r.raise_for_status()
        data = r.json()
    if data.get("code") != "Ok" or not data.get("routes"):
        raise ValueError(f"No route found ({data.get('code')})")
    return [{"coords": [[lat, lon] for lon, lat in route["geometry"]["coordinates"]],
             "distance_m": route["distance"], "duration_s": route["duration"]} for route in data["routes"][:3]]

async def get_route(start, end):
    return (await get_routes(start, end))[0]


def potholes_on_route(conn, coords, buffer_m=None):
    buffer_m = buffer_m or settings.ROUTE_BUFFER_M
    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    _, dlat, _, dlon = geo.bbox_around(0, 0, buffer_m)  # padding in degrees
    candidates = db.potholes_in_box(
        conn, min(lats) - dlat, max(lats) + dlat, min(lons) - dlon, max(lons) + dlon
    )
    hits = []
    for p in candidates:
        dist, along = geo.locate_on_route(coords, p["lat"], p["lon"])
        if dist <= buffer_m:
            p["route_offset_m"] = round(dist, 1)
            p["along_route_m"] = round(along, 1)
            hits.append(p)
    hits.sort(key=lambda p: p["along_route_m"])
    return hits
