import argparse
from tqdm import tqdm
from multiprocessing import Process, set_start_method, Queue
from collections import defaultdict
import os
import cv2
import json
import math
import csv
import datetime
from vida import VehicleDetectionTracker
from display_manager import DisplayManager
from process_manager import ProgressManager
import sys

class VideoProcessor(Process):
    def __init__(self, model, output, grace, distance, conf, iou, visible, json, video_path, position, display_queue, progress_queue):
        super().__init__()
        self.model = model
        self.output = output
        self.grace = grace
        self.distance = distance
        self.conf = conf
        self.iou = iou
        self.visible = visible
        self.json = json
        self.video_path = video_path
        self.filename = os.path.splitext(os.path.basename(video_path))[0]
        self.position = position
        self.display_queue = display_queue
        self.progress_queue = progress_queue

        self.output_writer = None
        self.global_vehicle_count = 0
        self.vehicle_tracks = defaultdict(list)
        self.json_results = []
        self.csv_file = None

    def run(self):
        self.process_video()

    def setup_output(self):
        output_video_path = os.path.join(self.output, f"processed_{self.filename}.mp4")
        output_csv_path = os.path.join(self.output, f"processed_{self.filename}.csv")
        output_json_path = os.path.join(self.output, f"processed_{self.filename}.json")
        return output_video_path, output_csv_path, output_json_path

    def setup_callback(self, width, height, fps):
        output_video_path, _, _ = self.setup_output()
        fourcc = cv2.VideoWriter_fourcc(*'avc1')
        self.output_writer = cv2.VideoWriter(output_video_path, fourcc, fps, (int(width), int(height)))

    def frame_callback(self, frame_number, frame_ms, total_frames, frame, result):
        self.progress_queue.put((self.video_path, frame_number, total_frames, self.position))
        if self.visible:
            self.display_queue.put((f"Video {self.video_path}", frame))
        self.process_detected_vehicles(frame_ms, frame_number, total_frames, result)
        if self.output_writer:
            self.output_writer.write(frame)

    def process_detected_vehicles(self, frame_ms, frame_number, total_frames, result):
        vehicles_to_remove = []
        for vehicle in result['detected_vehicles']:
            self.vehicle_tracks[vehicle["vehicle_id"]] = vehicle
        for v_id, vehicle in list(self.vehicle_tracks.items()):
            last_seen = vehicle['location']['end']['timestamp']
            seconds_seen_since = (frame_ms - last_seen) / 1000
            if frame_number >= total_frames or seconds_seen_since > self.grace:
                self.handle_vehicle_exit(v_id, vehicle, frame_ms)

    def handle_vehicle_exit(self, v_id, vehicle, frame_ms):
        start_pos = vehicle['location']['start']
        end_pos = vehicle['location']['end']
        distance = round(math.dist(
            (float(start_pos['x']), float(start_pos['y'])),
            (float(end_pos['x']), float(end_pos['y']))
        ), 2)

        if distance > self.distance:
            self.global_vehicle_count += 1
            for pos in vehicle['positions']:
                x, y, timestamp = float(pos['x']), float(pos['y']), int(pos['timestamp'])
                output = [
                    self.filename,
                    self.global_vehicle_count,
                    str(datetime.timedelta(milliseconds=start_pos['timestamp'])),
                    str(datetime.timedelta(milliseconds=end_pos['timestamp'])),
                    vehicle['vehicle_id'],
                    vehicle['vehicle_type'],
                    round(vehicle['confidence'], 2),
                    str(datetime.timedelta(milliseconds=timestamp)),
                    x,
                    y,
                    timestamp
                ]
                self.csv_writer.writerow(output)
            self.csv_file.flush()

        del self.vehicle_tracks[v_id]

    def process_video(self):
        os.makedirs(self.output, exist_ok=True)
        _, output_csv, output_json = self.setup_output()

        with open(output_csv, 'w', newline='') as self.csv_file:
            self.csv_writer = csv.writer(self.csv_file, quoting=csv.QUOTE_MINIMAL)
            self.csv_writer.writerow([
                'filename', '#', 'start timestamp', 'end timestamp', 'vehicle id', 'vehicle type', 'confidence',
                'position time', 'x', 'y', 'raw timestamp'
            ])

            vehicle_detection = VehicleDetectionTracker(
                model=self.model, conf=self.conf, iou=self.iou, json=self.json
            )

            total_frames = int(cv2.VideoCapture(self.video_path).get(cv2.CAP_PROP_FRAME_COUNT))

            vehicle_detection.process_video(
                self.video_path,
                self.setup_callback,
                self.frame_callback
            )

        if self.output_writer:
            self.output_writer.release()

        if self.visible:
            self.display_queue.put((f"Video {self.video_path}", None))

        if(self.json):
            with open(output_json, "w") as final_json_file:
                json.dump(self.json_results, final_json_file, separators=(',', ':'))

if __name__ == "__main__":
    set_start_method('spawn')

    parser = argparse.ArgumentParser(description='Process multiple videos against a detection model. Outputs the CSV and Video.')
    parser.add_argument('-m', '--model', help='Model to use (default: ../models/best.pt)', default='../models/best.pt')
    parser.add_argument('-o', '--output', help='Output folder. If folder does not exist, it will be created', default='./output/')
    parser.add_argument('-g', '--grace', help='Grace period in seconds before vehicle is counted as disappeared. (default=5)', type=int, default=5)
    parser.add_argument('-d', '--distance', help='Minimum distance in pixels a vehicle must move to be counted. (default=50)', type=int, default=50)
    parser.add_argument('-c', '--conf', help='Minimum confidence threshold for detections. (default=0.25)', type=float, default=0.25)
    parser.add_argument('-i', '--iou', help='IoU threshold for NMS. (default=0.70)', type=float, default=0.70)
    parser.add_argument('-v', '--visible', help='Display the output in a window.', action='store_true')
    parser.add_argument('-t', '--thread', help='How many processes to run.', type=int, default=1)
    parser.add_argument('-j', '--json', help='Output the JSON file', action='store_true')
    parser.add_argument('videos', nargs='+', metavar='videos', help='Video file(s) to process')
    args = parser.parse_args()

    if not os.path.exists(args.model):
        raise FileNotFoundError('Detection Model does not exist')

    for video in args.videos:
        if not os.path.exists(video):
            raise FileNotFoundError(f'Video file "{video}" does not exist')

    processes = []
    max_processes = args.thread

    display_queue = Queue()
    display_manager = DisplayManager(display_queue)
    display_manager.start()

    progress_queue = Queue()
    progress_manager = ProgressManager(progress_queue,len(args.videos))
    progress_manager.start()

    for index, video_path in enumerate(args.videos):
        while len(processes) >= max_processes:
            for p in processes:
                if not p.is_alive():
                    p.join()
                    processes.remove(p)

        processor = VideoProcessor(
            model=args.model,
            output=args.output,
            grace=args.grace,
            distance=args.distance,
            conf=args.conf,
            iou=args.iou,
            visible=args.visible,
            json=args.json,
            video_path=video_path,
            position=index,
            display_queue=display_queue,
            progress_queue=progress_queue
        )
        processor.start()
        processes.append(processor)

    for p in processes:
        p.join()

    display_queue.put((None, None))
    display_manager.join()

    progress_queue.put('DONE')
    progress_manager.join()

    cv2.destroyAllWindows()
