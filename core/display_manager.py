import cv2
from multiprocessing import Process, Queue

class DisplayManager(Process):
    def __init__(self, queue):
        super().__init__()
        self.queue = queue

    def run(self):
        while True:
            window_name, frame = self.queue.get()
            if window_name is None and frame is None:
                break
            elif window_name is not None and frame is not None:
                cv2.imshow(window_name, frame)
            elif window_name is not None and frame is None:
                cv2.destroyWindow(window_name) 
            if cv2.waitKey(1) & 0xFF == ord('q'):
                break
        cv2.destroyAllWindows()

    def stop(self):
        self.queue.put((None, None))
        self.join()
