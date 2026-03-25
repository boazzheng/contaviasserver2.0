from ultralytics import YOLO
import torch
import os
import gc
import shutil
from datetime import datetime
import argparse

torch.cuda.empty_cache()

parser = argparse.ArgumentParser(description='Train detection model based on the images/label provided')
parser.add_argument('-e', '--epochs', help='Number of epoch to run (default=160)', type=int, default=160)
parser.add_argument('-b', '--batch', help='Number of batch (default=32)', type=int, default=64)
parser.add_argument('-w', '--workers', help='Number of workers (default=1)', type=int, default=4)
parser.add_argument('-c', '--config', help='Config file to use (default=generic)', default='generic')
parser.add_argument('-r', '--resume', help='Resume a previous run', type=int, default=0)


# Define the function to resume training
def resume_training(model_path, start_epoch, epochs, batch, workers, config, device):
    model = YOLO(model_path).to(device)
    model.train(
        data=config + ".yaml",
        epochs=epochs - start_epoch,  # Continue from the last epoch
        project="runs/%s" % config,
        batch=batch,  # Adjust batch size
        exist_ok=True,
        device=device,
        workers=workers,
        amp=True
    )

args = parser.parse_args()
epochs = int(args.epochs)
batch = int(args.batch)
workers = int(args.workers)

runtime = datetime.now().strftime('%Y-%m-%d.%H%M%S')
gc.collect()
torch.cuda.empty_cache()
device = torch.device("mps") if torch.backends.mps.is_available() else torch.device('cuda' if torch.cuda.is_available() else 'cpu')


last_model_path = "runs/%s/train/weights/best.pt" % args.config
start_epoch = args.resume


model_path = last_model_path if start_epoch > 0 else 'yolov8l.yaml'
model = YOLO(model_path).to(device)
model.train(
        data=args.config+".yaml",
        epochs=epochs - start_epoch,
        project="runs/%s"%(args.config),
        batch=batch,
        exist_ok=True,
        device=device,
        workers=workers,
        amp=True
    )

dir_path = os.path.dirname(os.path.realpath(__file__))
model_path = os.path.abspath(os.path.join(dir_path, "../models"))
best = os.path.join(dir_path, "runs/%s/train/weights/best.pt"%(args.config))

if os.path.exists(best):
    shutil.copy(best,os.path.join(model_path, args.config+".pt"))
    shutil.copy(best,os.path.join(model_path, "%s.%s.pt"%(args.config,runtime)))

# if os.path.exists('yolov8n.pt'):
#     os.remove('yolov8n.pt')