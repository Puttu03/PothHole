"""Back up database and rebuild derived defects from all raw sightings. Stop server first."""
from pathlib import Path
import sys,sqlite3,datetime
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from backend.config import settings
from backend import db
import papermill as pm
stamp=datetime.datetime.now().strftime('%Y%m%d_%H%M%S')
backup=settings.DB_PATH.with_name('before_reprocess_'+stamp+'.db')
db.init()
with sqlite3.connect(settings.DB_PATH) as source,sqlite3.connect(backup) as target:source.backup(target)
with db.session() as conn:
    count=conn.execute('SELECT COUNT(*) FROM detections').fetchone()[0]
    conn.execute('UPDATE detections SET processed=0,pothole_id=NULL,process_note=NULL')
    conn.execute('DELETE FROM feedback')
    conn.execute('DELETE FROM potholes')
print('Backup:',backup,'Raw detections:',count)
settings.RUNS_DIR.mkdir(parents=True,exist_ok=True)
pm.execute_notebook(str(settings.NOTEBOOK_DIR/'02_postprocess.ipynb'),str(settings.RUNS_DIR/('reprocess_'+stamp+'.ipynb')),cwd=str(settings.NOTEBOOK_DIR))
print('Reprocessing complete. Feedback and derived IDs were rebuilt; raw images retained.')
