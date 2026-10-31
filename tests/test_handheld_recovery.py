import importlib.util
import math
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import geo
from backend.frame_calibration import box_geometry,attach,rotated_detection,ensure_schema
from backend.postprocess_quality import locate
from review_handheld import Review

BASE=dict(id=1,photo_path='frame.jpg',lat=12.3,lon=76.6,gps_accuracy_m=5,heading_deg=0,
          img_w=1280,img_h=2276,camera_height_m=1.2,camera_tilt_deg=8,hfov_deg=66,
          x1=443,y1=623,x2=627,y2=718,confidence=.817,processed=0,
          process_note='unprojectable_box',pothole_id=None)
CAL=dict(horizon_left=.12,horizon_right=.12,height_m=1.2,hfov_deg=66,heading_deg=0)

class Tests(unittest.TestCase):
    def test_known_deferred_geometry(self):
        self.assertEqual(locate(BASE,[])[1],'unprojectable_box')
        item,reason=locate({**BASE,'_calibration':CAL},[])
        self.assertIsNone(reason)
        self.assertGreater(item['forward_m'],0)
        self.assertLess(item['forward_m'],25)
    def test_level_horizon_agrees_with_legacy(self):
        d={**BASE,'y1':1250,'y2':1400}
        f=1280/(2*math.tan(math.radians(33)))
        y=(1138-f*math.tan(math.radians(8)))/2276
        c={**CAL,'horizon_left':y,'horizon_right':y}
        a=box_geometry(d,c);b=geo.box_to_ground((d['x1'],d['y1'],d['x2'],d['y2']),1280,2276,1.2,8,66)
        for k in a:self.assertAlmostEqual(a[k],b[k],places=8)
    def test_roll_and_horizon_rejection(self):
        self.assertIsNotNone(box_geometry(BASE,{**CAL,'horizon_left':.1,'horizon_right':.2}))
        self.assertIsNone(box_geometry(BASE,{**CAL,'horizon_left':.5,'horizon_right':.5}))
    def test_limits_retained(self):
        self.assertEqual(locate({**BASE,'_calibration':CAL},[],max_distance=.1)[1],'too_far')
        self.assertEqual(locate({**BASE,'_calibration':CAL,'gps_accuracy_m':100},[])[1],'poor_gps')
        self.assertEqual(locate({**BASE,'_calibration':{**CAL,'height_m':float('nan')}},[])[1],'invalid_calibration')
    def test_rotated_geometry_matches_upright(self):
        reference=box_geometry(BASE,CAL)
        for angle in (90,180,270):
            sideways=rotated_detection(BASE,angle)
            # Original saved-width FOV changes if we simulate rotated source pixels.
            f=BASE['img_w']/(2*math.tan(math.radians(CAL['hfov_deg'])/2))
            fov=math.degrees(2*math.atan(sideways['img_w']/(2*f)))
            corrected=box_geometry(sideways,{**CAL,'hfov_deg':fov,'rotation_deg':(360-angle)%360})
            for key in reference:self.assertAlmostEqual(reference[key],corrected[key],places=8)
            restored=rotated_detection(sideways,(360-angle)%360)
            for key in ('img_w','img_h','x1','y1','x2','y2'):self.assertEqual(restored[key],BASE[key])
    def test_old_schema_migration(self):
        from backend.frame_calibration import SCHEMA
        c=sqlite3.connect(':memory:');c.execute(SCHEMA)
        c.execute('INSERT INTO frame_calibration VALUES (1,.1,.1,1.2,66,201,"old")')
        ensure_schema(c);ensure_schema(c)
        self.assertEqual(c.execute('SELECT rotation_deg FROM frame_calibration').fetchone()[0],0)
        c.close()
    def test_backup_and_original_preservation(self):
        with tempfile.TemporaryDirectory() as td:
            path=Path(td)/'pothole.db';c=sqlite3.connect(path)
            cols=','.join(k for k in BASE)
            c.execute('CREATE TABLE detections ('+cols+')')
            c.execute('INSERT INTO detections VALUES ('+','.join('?' for _ in BASE)+')',tuple(BASE.values()))
            assigned={**BASE,'id':2,'processed':1,'pothole_id':8}
            c.execute('INSERT INTO detections VALUES ('+','.join('?' for _ in BASE)+')',tuple(assigned.values()));c.commit();c.close()
            review=Review(path,td)
            with self.assertRaises(ValueError):review.save(1,{**CAL,'horizon_left':.8,'horizon_right':.8})
            self.assertIsNone(review.backup)
            result=review.save(1,CAL);self.assertEqual(result['queued'],1)
            c=review.connect();rows=[dict(r) for r in c.execute('SELECT * FROM detections ORDER BY id')]
            self.assertEqual(rows[0]['camera_tilt_deg'],8)
            self.assertEqual(rows[1],assigned)
            self.assertEqual(attach(c,rows)[0]['_calibration']['horizon_left'],.12)
            self.assertEqual(c.execute('SELECT COUNT(*) FROM frame_calibration').fetchone()[0],1)
            c.close()
            backup=sqlite3.connect(result['backup'])
            self.assertEqual(backup.execute('SELECT process_note FROM detections WHERE id=1').fetchone()[0],'unprojectable_box');backup.close()
            review.save(1,CAL)  # idempotent calibration save; no map inserts

if __name__=='__main__':unittest.main()
