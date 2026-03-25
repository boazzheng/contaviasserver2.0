import argparse
from multiprocessing import Process, set_start_method, Queue, Manager
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
import time

class VideoProcessor(Process):
    # CORREÇÃO: Adicionei o parâmetro 'tracker' aqui na inicialização
    def __init__(self, model, output, grace, distance, conf, iou, visible, json_flag, tracker,
                 video_path, position, display_queue, progress_queue, completed_queue):
        super().__init__()
        self.model = model
        self.output = output
        self.grace = grace
        self.distance = distance
        self.conf = conf
        self.iou = iou
        self.visible = visible
        self.json_flag = json_flag
        self.tracker = tracker  # CORREÇÃO: Salvando o tracker
        self.video_path = video_path
        self.filename = os.path.splitext(os.path.basename(video_path))[0]
        self.position = position
        self.display_queue = display_queue
        self.progress_queue = progress_queue
        self.completed_queue = completed_queue

        self.output_writer = None
        self.global_vehicle_count = 0
        self.vehicle_tracks = defaultdict(list)
        self.json_results = []
        self.csv_file = None

    def run(self):
        try:
            self.process_video()
        finally:
            # Notify main process that this video is done
            self.completed_queue.put(self.video_path)

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
            duration_ms = end_pos['timestamp'] - start_pos['timestamp']
            duration = str(datetime.timedelta(milliseconds=duration_ms))
            output = [
                self.filename,
                self.global_vehicle_count,
                str(datetime.timedelta(milliseconds=start_pos['timestamp'])),
                str(datetime.timedelta(milliseconds=end_pos['timestamp'])),
                vehicle['vehicle_id'], vehicle['vehicle_type'], round(vehicle['confidence'], 2),
                duration, distance,
                float(start_pos['x']), float(start_pos['y']),
                float(end_pos['x']), float(end_pos['y']),
                start_pos['timestamp'], end_pos['timestamp']
            ]
            self.csv_writer.writerow(output)
            self.csv_file.flush()
            if self.json_flag:
                self.json_results.append({
                    'id': vehicle['vehicle_id'],
                    'type': vehicle['vehicle_type'],
                    'conf': round(vehicle['confidence'], 2),
                    'pos': vehicle['positions']
                })
        del self.vehicle_tracks[v_id]

    def process_video(self):
        os.makedirs(self.output, exist_ok=True)
        _, output_csv, output_json = self.setup_output()
        with open(output_csv, 'w', newline='') as self.csv_file:
            self.csv_writer = csv.writer(self.csv_file, quoting=csv.QUOTE_MINIMAL)
            self.csv_writer.writerow([
                'filename', '#', 'start timestamp', 'end timestamp', 'vehicle id', 'vehicle type', 'confidence',
                'duration', 'distance', 'start x', 'start y', 'end x', 'end y',
                'raw start timestamp', 'raw end timestamp'
            ])
            vehicle_detection = VehicleDetectionTracker(
                model=self.model, conf=self.conf, iou=self.iou, json=self.json_flag, tracker=self.tracker
            )
            total_frames = int(cv2.VideoCapture(self.video_path).get(cv2.CAP_PROP_FRAME_COUNT))
            vehicle_detection.process_video(
                self.video_path,
                self.setup_callback,
                self.frame_callback,
                # completed_callback=lambda: None  # we notify via completed_queue instead
            )

        if self.output_writer:
            self.output_writer.release()

        if self.visible:
            self.display_queue.put((f"Video {self.video_path}", None))

        if self.json_flag:
            with open(output_json, "w") as final_json_file:
                json.dump(self.json_results, final_json_file, separators=(',', ':'))

# ------------------- MAIN -------------------
if __name__ == "__main__":
    set_start_method('spawn')

    parser = argparse.ArgumentParser(description='Process multiple videos against a detection model.')
    parser.add_argument('-m', '--model', default='../models/yolo11x.pt')
    parser.add_argument('-o', '--output', default='./output/')
    parser.add_argument('-g', '--grace', type=int, default=5)
    parser.add_argument('-d', '--distance', type=int, default=50)
    parser.add_argument('-c', '--conf', type=float, default=0.25)
    parser.add_argument('-i', '--iou', type=float, default=0.7)
    parser.add_argument('-v', '--visible', action='store_true')
    parser.add_argument('-t', '--thread', type=int, default=1)
    parser.add_argument('-j', '--json', action='store_true')

    parser.add_argument('--tracker', default='tracker.yaml', help='Configuração customizada do rastreador')

    parser.add_argument('videos', nargs='+')
    args = parser.parse_args()

    for path in [args.model, *args.videos]:
        if not os.path.exists(path):
            raise FileNotFoundError(f'{path} does not exist')

    max_processes = args.thread
    processes = []

    # CORREÇÃO: Utilizando Manager() para as Queues no Linux/WSL
    manager = Manager()
    display_queue = manager.Queue()
    display_manager = DisplayManager(display_queue)
    display_manager.start()

    progress_queue = manager.Queue()
    progress_manager = ProgressManager(progress_queue, len(args.videos))
    progress_manager.start()

    completed_queue = manager.Queue()
    completed_count = 0

    # Start video processes
    video_index = 0
    while video_index < len(args.videos) or processes:
        # Start new processes if under limit
        while video_index < len(args.videos) and len(processes) < max_processes:
            processor = VideoProcessor(
                model=args.model,
                output=args.output,
                grace=args.grace,
                distance=args.distance,
                conf=args.conf,
                iou=args.iou,
                visible=args.visible,
                json_flag=args.json,
                tracker=args.tracker,
                video_path=args.videos[video_index],
                position=video_index,
                display_queue=display_queue,
                progress_queue=progress_queue,
                completed_queue=completed_queue
            )
            processor.start()
            processes.append(processor)
            video_index += 1

        # Check for completed videos
        while not completed_queue.empty():
            completed_video = completed_queue.get()
            completed_count += 1
            print(f"[{completed_count}/{len(args.videos)}] Completed: {completed_video}")

            # Exit if all videos are done
            if completed_count == len(args.videos):
                # Clean up before exit
                for p in processes:
                    if p.is_alive():
                        p.terminate()
                        p.join()
                display_queue.put((None, None))
                display_manager.join()
                progress_queue.put('DONE')
                progress_manager.join()
                cv2.destroyAllWindows()
                sys.exit(0)

        # Clean up finished processes
        for p in processes[:]:
            if not p.is_alive():
                p.join()
                processes.remove(p)

        # Small sleep to prevent busy loop
        time.sleep(0.1)

    # All videos done, clean up
    display_queue.put((None, None))
    display_manager.join()
    progress_queue.put('DONE')
    progress_manager.join()
    cv2.destroyAllWindows()
    print("All processing complete.")
    sys.exit(0)