"""Hardware inventory and explicit model downloads."""
import platform,shutil,subprocess,sys,threading
import psutil,httpx
from fastapi import APIRouter,HTTPException,UploadFile,File,Form
from fastapi.responses import FileResponse
from .config import settings
router=APIRouter(); job={'state':'idle'};lock=threading.Lock()
@router.get('/system')
def page(): return FileResponse(settings.WEB_DIR/'system.html')
@router.get('/api/system')
def status():
 import torch
 gpu= torch.cuda.get_device_name(0) if torch.cuda.is_available() else None
 runtime='cuda:0' if gpu else ('mps' if torch.backends.mps.is_available() else 'cpu')
 try:
  r=httpx.get(settings.OLLAMA_URL+'/api/tags',timeout=3);r.raise_for_status(); installed=[m['name'] for m in r.json()['models']];ollama=True
 except Exception: installed=[];ollama=False
 from .inference import get_detector
 from .damage_labels import canonical, LABELS
 det=get_detector()
 supported=sorted({LABELS[canonical(n)] for n in det.class_names.values() if canonical(n)})
 return dict(supported_damage_types=supported,model_note='HRP4K weights detect potholes only. Load a multi-class road-damage model for cracks.',os=platform.platform(),cpu=platform.processor(),ram_gb=round(psutil.virtual_memory().total/2**30,1),gpu=gpu,runtime=runtime,detector=str(settings.model_path.name) if settings.model_path else 'No installed weights',detector_available=settings.model_path is not None,qwen=settings.SLM_MODEL,qwen_available=settings.SLM_MODEL in installed,ollama_available=ollama,installed=installed,job=job)
@router.post('/api/models/download/{kind}')
def download(kind:str):
 if kind not in ('yolo','qwen','road-damage','road-damage-26s','road-damage-26n'):raise HTTPException(400,'Unknown model')
 with lock:
  if job['state']=='running': raise HTTPException(409,'A download is running')
  job.update(state='running',error=None)
 qwen_to_download=settings.SLM_MODEL
 def work():
  try:
   if kind in ('road-damage-26s','road-damage-26n'):
    from huggingface_hub import hf_hub_download, list_repo_files
    import os
    repo=('TamAko783/YOLO26s_RDD_FRDC_Distilled_v2' if kind.endswith('26s') else 'TamAko783/YOLO26n_RDD_FRDC_Distilled')
    files=[name for name in list_repo_files(repo) if name.endswith('.pt')]
    if len(files)!=1:raise RuntimeError('Expected one model weights file; source needs review: '+str(files))
    source=hf_hub_download(repo_id=repo,filename=files[0])
    folder=settings.WEB_DIR.parent/'models';folder.mkdir(exist_ok=True)
    name='road_damage_'+kind.rsplit('-',1)[1]+'.pt'
    temporary=folder/(name+'.download');shutil.copy2(source,temporary)
    os.replace(temporary,folder/name)
    (folder/'active_model.txt').write_text(name)
   elif kind=='road-damage':
    from huggingface_hub import hf_hub_download
    from pathlib import Path
    import os
    source=hf_hub_download(repo_id='SreekarAditya/yolo-rdd2022-benchmark', filename='yolo-rdd2022-benchmark/yolov8s_seed0_best.pt')
    folder=settings.WEB_DIR.parent/'models';folder.mkdir(exist_ok=True)
    temporary=folder/'road_damage.download';shutil.copy2(source,temporary)
    os.replace(temporary,folder/'road_damage.pt')
    (folder/'active_model.txt').write_text('road_damage.pt')
   elif kind=='yolo':
    subprocess.run([sys.executable,str(settings.WEB_DIR.parent/'scripts/download_pretrained.py'),'--preset','hrp4k-yolo26m','--no-coreml'],check=True)
   else:
    with httpx.stream('POST',settings.OLLAMA_URL+'/api/pull',json={'name':qwen_to_download},timeout=None) as response:
     response.raise_for_status()
     import json
     for line in response.iter_lines():
      if line:
       progress=json.loads(line)
       if 'error' in progress:raise RuntimeError(progress['error'])
       job['progress']=progress
   job.update(state='done',message='Restart the application after downloading YOLO.')
  except Exception as e:job.update(state='failed',error=str(e))
 threading.Thread(target=work,daemon=True).start()
 return job

@router.get('/api/models/local')
def local_models():
 folder=settings.WEB_DIR.parent/'models'
 return {'models':sorted(p.name for p in folder.glob('*.pt')), 'selected':settings.model_path.name if settings.model_path else None}

@router.post('/api/models/select')
def select_model(name: str = Form(...)):
 from pathlib import Path
 folder=settings.WEB_DIR.parent/'models'
 if Path(name).name != name or not name.endswith('.pt') or not (folder/name).is_file():
  raise HTTPException(400,'Select an installed .pt model')
 (folder/'active_model.txt').write_text(name)
 return {'message':'Selected. Restart the server to load this model safely.', 'name':name}

@router.post('/api/models/upload')
async def upload_model(file: UploadFile = File(...), trusted: bool = Form(False)):
 import uuid,os
 from pathlib import Path
 if not trusted:raise HTTPException(400,'Confirm that you trust the source of this PyTorch model.')
 name=Path(file.filename or '').name
 if not name.endswith('.pt') or len(name)>100:raise HTTPException(400,'Upload a .pt weights file')
 folder=settings.WEB_DIR.parent/'models';folder.mkdir(exist_ok=True)
 name='custom_'+uuid.uuid4().hex[:8]+'_'+name
 temporary=folder/(name+'.part');size=0
 try:
  with temporary.open('wb') as out:
   while chunk:=await file.read(1024*1024):
    size+=len(chunk)
    if size>512*1024*1024:raise HTTPException(413,'Maximum model size is 512 MB')
    out.write(chunk)
  if size==0:raise HTTPException(400,'Empty file')
  os.replace(temporary,folder/name)
  return {'message':'Uploaded. Select it below and restart to load.', 'name':name}
 finally:
  temporary.unlink(missing_ok=True)
  await file.close()

QWEN_CHOICES = {
 'qwen3.5:2b': 'Qwen3.5 2B — lighter option',
 'qwen3.5:4b-q4_K_M': 'Qwen3.5 4B Q4_K_M — larger option',
}
@router.get('/api/models/choices')
def model_choices():
 import os
 folder=settings.WEB_DIR.parent/'models'
 saved=(folder/'active_model.txt').read_text().strip() if (folder/'active_model.txt').exists() else None
 return {'qwen_choices':QWEN_CHOICES,'qwen_current':settings.SLM_MODEL,
         'yolo_saved':saved,'restart_required':True,
         'environment_override':bool(os.environ.get('POTHOLE_MODEL_PATH') or os.environ.get('POTHOLE_SLM_MODEL'))}

@router.post('/api/models/select-qwen')
def select_qwen(name: str = Form(...)):
 if name not in QWEN_CHOICES:raise HTTPException(400,'Select a listed Qwen model')
 folder=settings.WEB_DIR.parent/'models';folder.mkdir(exist_ok=True)
 (folder/'active_qwen.txt').write_text(name)
 settings.SLM_MODEL=name
 return {'message':'Qwen choice saved. Download it if missing. Applies to the next post-processing job; existing jobs keep their current model.', 'name':name}
