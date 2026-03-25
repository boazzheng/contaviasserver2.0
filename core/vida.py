import cv2
from collections import defaultdict, Counter
from ultralytics import YOLO
import numpy as np
import torch
import os
import warnings

# Suppress warnings
warnings.filterwarnings("ignore")

# Set up the device for model processing
device = torch.device("mps" if torch.backends.mps.is_available() else 'cuda' if torch.cuda.is_available() else 'cpu')

# Load the font for annotation.
# Currently not used anymore.
ft = cv2.freetype.createFreeType2()
ft.loadFontData("Roboto-Regular.ttf", 0)

def hex_to_bgr(hex_color):
    """Convert a hex color string to a BGR tuple."""
    hex_color = hex_color.lstrip('#')
    return tuple(int(hex_color[i:i+2], 16) for i in (4, 2, 0))

# Predefined colors for bounding boxes
rgb_colors = [hex_to_bgr(color) for color in ['#00ccff', '#D7263D', '#F9E900', '#ffc6ff', '#bdb2ff']]

class VehicleDetectionTracker:
    def __init__(self, model, conf=0.25, iou=0.7, max_det=100, json=True, annotation=True, gpu_annotation=True, show_path=False, tracker="tracker.yaml"):
        if not model or not os.path.exists(model):
            raise FileNotFoundError('Model does not exist')

        self.json=json

        self.config = {
            "conf": conf,
            "iou": iou,
            "max_det": max_det,
            "gpu_annotation": gpu_annotation,
            "annotation": annotation,
            "show_path": show_path,
            "tracker": tracker
        }
        self.vehicle_tracks = defaultdict(lambda: {
            "timestamps": [], "positions": [], "labels": [], "frames": 0,
            "start_position": None, "end_position": None
        })
        self.model = YOLO(model).to(device)
        self.detected_vehicles = set()
        self.class_names = self.model.names

    def weighted_most_likely(self, labels):
        """Calculate the most likely label based on weighted confidence."""
        weighted_scores = defaultdict(float)
        counts = Counter([label for label, _ in labels])

        for label, conf in labels:
            weighted_scores[label] += conf
        for label in weighted_scores:
            weighted_scores[label] *= counts[label]

        return max(weighted_scores, key=weighted_scores.get)

    def get_label_index(self, label):
        """Find the index of the label in the model's names dictionary."""
        for idx, name in self.class_names.items():
            if name == label:
                return idx
        raise ValueError(f"Label '{label}' not found in model names.")

    def process_frame(self, frame_number, frame, frame_timestamp):
        """Process a single frame to detect and track vehicles."""
        response = {"number_of_vehicles_detected": 0, "detected_vehicles": []}

        results = self.model.track(
            frame, conf=self.config['conf'], iou=self.config['iou'], max_det=self.config['max_det'],
            augment=False, agnostic_nms=True, persist=True, verbose=False, device=device, imgsz=1280, tracker=self.config['tracker']
        )

        if results and results[0].boxes and results[0].boxes.id is not None:
            boxes = results[0].boxes.xywh.cpu().numpy()
            conf_list = results[0].boxes.conf.cpu().numpy()
            track_ids = results[0].boxes.id.int().cpu().tolist()
            clss = results[0].boxes.cls.cpu().tolist()

            for box, track_id, cls, conf in zip(boxes, track_ids, clss, conf_list):
                x, y, w, h = box
                label = self.class_names[cls]  # Get the label from class index

                vehicle_track = self.vehicle_tracks[track_id]
                self.update_vehicle_track(vehicle_track, frame_number, frame_timestamp, label, conf, x, y, w, h)

                most_likely_label = self.weighted_most_likely(vehicle_track['labels'])
                label_index = self.get_label_index(most_likely_label)
                bbox_color = rgb_colors[label_index % len(rgb_colors)]

                if self.config['annotation']:
                    self.annotate_frame(frame, x, y, w, h, bbox_color, track_id, vehicle_track)

                self.detected_vehicles.add(track_id)
                response["number_of_vehicles_detected"] += 1
                response["detected_vehicles"].append({
                    "vehicle_id": track_id,
                    "vehicle_type": most_likely_label,
                    "confidence": conf.item(),
                    "frames": vehicle_track['frames'],
                    "positions": vehicle_track['positions'],
                    "location": {
                        "start": vehicle_track['start_position'],
                        "end": vehicle_track['end_position']
                    }
                })

        self.cleanup_tracks(frame_timestamp)
        return frame, response

    def update_vehicle_track(self, vehicle_track, frame_number, frame_timestamp, label, conf, x, y, w, h):
        """Update vehicle tracking information."""
        vehicle_track['frames'] += 1
        vehicle_track['labels'].append((label, conf))
        vehicle_track['end_position'] = {"timestamp": frame_timestamp, "frame": frame_number, "x": float(x), "y": float(y)}
        
        if(self.json):
            vehicle_track['timestamps'].append(frame_timestamp) # this one really isnt used but its kept just in case
            vehicle_track['positions'].append((frame_number, int(x), int(y), int(w), int(h)))
        
        # if first frame
        if not vehicle_track['start_position']:
            vehicle_track['start_position'] = {"timestamp": frame_timestamp, "frame": frame_number, "x": float(x), "y": float(y)}

    def annotate_frame(self, frame, x, y, w, h, bbox_color, track_id, vehicle_track):
        """Annotate the frame with bounding boxes and paths."""
        x1, y1, x2, y2 = int(x - w / 2), int(y - h / 2), int(x + w / 2), int(y + h / 2)
        alpha = 0.25

        if self.config['gpu_annotation'] and torch.cuda.is_available():
            self.gpu_annotate(frame, x1, y1, x2, y2, bbox_color, alpha)
        else:
            self.cpu_annotate(frame, x1, y1, x2, y2, bbox_color, alpha)

        cv2.putText(frame, f"ID: {track_id}", (x1, y1 - 4), cv2.FONT_HERSHEY_SIMPLEX, 0.5, bbox_color, 1, cv2.LINE_AA)

        if self.config['show_path']:
            points = np.array(vehicle_track['positions'])[:, 1:3].astype(np.int32).reshape((-1, 1, 2))
            cv2.polylines(frame, [points], isClosed=False, color=bbox_color, thickness=1)

    def gpu_annotate(self, frame, x1, y1, x2, y2, bbox_color, alpha):
        """Annotate the frame using GPU for acceleration."""
        bbox_color_scalar = (int(bbox_color[0]), int(bbox_color[1]), int(bbox_color[2]))
        roi_gpu = cv2.cuda_GpuMat()
        roi_gpu.upload(frame[y1:y2, x1:x2])
        overlay_gpu = cv2.cuda_GpuMat(roi_gpu.size(), roi_gpu.type())
        overlay_gpu.setTo(bbox_color_scalar)
        blended_gpu = cv2.cuda.addWeighted(overlay_gpu, alpha, roi_gpu, 1 - alpha, 0)

        cols,rows = roi_gpu.size()
        thickness=1
        if rows >= thickness and cols >= thickness:
            blended_gpu.rowRange(0, thickness).colRange(0, cols).setTo(bbox_color_scalar)
            blended_gpu.rowRange(rows - thickness, rows).colRange(0, cols).setTo(bbox_color_scalar)
            blended_gpu.rowRange(0, rows).colRange(0, thickness).setTo(bbox_color_scalar)
            blended_gpu.rowRange(0, rows).colRange(cols - thickness, cols).setTo(bbox_color_scalar)

        frame[y1:y2, x1:x2] = blended_gpu.download()

    def cpu_annotate(self, frame, x1, y1, x2, y2, bbox_color, alpha):
        """Annotate the frame using CPU."""
        roi = frame[y1:y2, x1:x2]
        overlay = roi.copy()
        cv2.rectangle(overlay, (0, 0), (x2 - x1, y2 - y1), bbox_color, -1)
        cv2.addWeighted(overlay, alpha, roi, 1 - alpha, 0, roi)
        frame[y1:y2, x1:x2] = roi

    def cleanup_tracks(self, current_timestamp):
        """Clean up tracks that have not been updated for a specified duration."""
        for track_id in list(self.detected_vehicles):
            elapsed = (current_timestamp - self.vehicle_tracks[track_id]['end_position']['timestamp']) / 1000
            if elapsed > 1 * 60:
                del self.vehicle_tracks[track_id]
                self.detected_vehicles.remove(track_id)

    def process_video(self, video_path, setup_callback, result_callback):
        """Process the video, frame by frame, to track vehicles."""
        cap = cv2.VideoCapture(video_path)

        if not cap.isOpened():
            raise IOError(f"Cannot open video file {video_path}")

        width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        fps = int(cap.get(cv2.CAP_PROP_FPS))
        length = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))

        setup_callback(width, height, fps)

        while cap.isOpened():
            success, frame = cap.read()
            if not success:
                break

            frame_ms = int(cap.get(cv2.CAP_PROP_POS_MSEC))
            frame_number = int(cap.get(cv2.CAP_PROP_POS_FRAMES))

            frame, result = self.process_frame(frame_number, frame, frame_ms)
            result_callback(frame_number, frame_ms, length, frame, result)

        cap.release()
