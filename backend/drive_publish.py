"""Publish only map fields. No raw sightings, photos, or personal metadata are exported."""
import argparse,os,sqlite3,tempfile
from pathlib import Path
FIELDS='id lat lon loc_accuracy_m severity ride_score width_m area_m2 surface lane_position description times_seen last_seen status damage_type'.split()
def export(source,destination):
    source=Path(source).resolve();destination=Path(destination).resolve()
    if source==destination:raise ValueError('Source and destination must differ.')
    destination.parent.mkdir(parents=True,exist_ok=True)
    fd,name=tempfile.mkstemp(dir=destination.parent,suffix='.sqlite');os.close(fd)
    try:
        with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src,sqlite3.connect(name) as dst:
            cols={r[1]:r[2] for r in src.execute('PRAGMA table_info(potholes)')}
            required={'id','lat','lon','status'}
            if not required<=cols.keys():raise ValueError('Not a compatible RoadPlotter map database.')
            fields=[f for f in FIELDS if f in cols]
            dst.execute('CREATE TABLE potholes ('+', '.join('"'+f+'" '+('INTEGER' if f in ('id','times_seen') else 'REAL' if f in ('lat','lon','loc_accuracy_m','ride_score','width_m','area_m2') else 'TEXT') for f in fields)+')')
            names=','.join(fields)
            query='SELECT '+names+" FROM potholes WHERE status='open'"
            # Legacy databases may not have times_seen. Existing confirmed rows require >=3.
            if 'times_seen' in cols:query+=' AND times_seen>=3'
            rows=src.execute(query).fetchall()
            dst.executemany('INSERT INTO potholes VALUES('+','.join('?' for _ in fields)+')',rows)
            dst.commit()
        os.chmod(name, 0o644)
        os.replace(name,destination)
        print(f'Published {len(rows)} confirmed open records to {destination}')
    finally:Path(name).unlink(missing_ok=True)

def publish():
    from .config import settings
    export(settings.DB_PATH, Path(__file__).resolve().parents[1] / "drive_public" / "road_data.sqlite")

if __name__ == "__main__":
    publish()
