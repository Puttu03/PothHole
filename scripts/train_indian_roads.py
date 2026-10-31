"""Fine-tune using a reviewed YOLO dataset YAML; best.pt is portable."""
import argparse
from ultralytics import YOLO
p=argparse.ArgumentParser();p.add_argument('--data',required=True);p.add_argument('--weights',default='models/pothole.pt');p.add_argument('--device',default='cpu');p.add_argument('--epochs',type=int,default=50);a=p.parse_args()
YOLO(a.weights).train(data=a.data,epochs=a.epochs,imgsz=768,batch=1,device=a.device,project='training_runs',name='indian_roads')
