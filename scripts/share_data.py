"""Export data consistently or import into a NEW destination; never overwrite live data."""
import argparse,pathlib,sqlite3,tempfile,zipfile,shutil
p=argparse.ArgumentParser();p.add_argument('action',choices=['export','import']);p.add_argument('archive');p.add_argument('--directory',default='data');a=p.parse_args();root=pathlib.Path(a.directory)
if a.action=='export':
 with tempfile.TemporaryDirectory() as tmp:
  snapshot=pathlib.Path(tmp)/'pothole.db'
  with sqlite3.connect(root/'pothole.db') as src,sqlite3.connect(snapshot) as dst:src.backup(dst)
  with zipfile.ZipFile(a.archive,'w',zipfile.ZIP_DEFLATED) as z:
   z.write(snapshot,'pothole.db')
   for f in (root/'photos').rglob('*'):
    if f.is_file():z.write(f,f.relative_to(root))
else:
 if root.exists():raise SystemExit('Choose a new --directory; existing folders are never overwritten.')
 with zipfile.ZipFile(a.archive) as z:
  for item in z.infolist():
   target=(root/item.filename).resolve()
   if not target.is_relative_to(root.resolve()):raise SystemExit('Unsafe archive path')
   if item.file_size>2**30:raise SystemExit('Archive member too large')
  if sum(i.file_size for i in z.infolist())>20*2**30:raise SystemExit('Archive too large')
  z.extractall(root)
print('Done')
