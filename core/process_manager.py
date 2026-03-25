from multiprocessing import Queue, Process
from tqdm import tqdm
import os

class ProgressManager(Process):
    def __init__(self, queue, total_files):
        super().__init__()
        self.queue = queue
        self.total_files = total_files
        self.main_bar =  None
        self.bars = {}

    def run(self):

        self.main_bar = tqdm(total=self.total_files, desc='Files Processed', unit='file', position=0, leave=True)

        while True:
            msg = self.queue.get()
            if msg == 'DONE':
                break
            video_path, progress, total, position = msg

            if video_path not in self.bars:
                self.bars[video_path] = tqdm(
                    total=total, 
                    desc=f"[{position+1:02d}] {os.path.basename(video_path)}", 
                    unit="frame", 
                    dynamic_ncols=True, 
                    position=position+1, 
                    leave=True
                )
            self.bars[video_path].n = progress
            self.bars[video_path].refresh()

            if self.bars[video_path].n >= total:
                self.bars[video_path].n = total
                self.bars[video_path].refresh()
                self.main_bar.update(1)


        for bar in self.bars.values():
            bar.close()
