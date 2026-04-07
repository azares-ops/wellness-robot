import cv2
import numpy as np
import threading
import time
import base64

from posture_engine import PostureDetector
from emotion_engine import EmotionDetector


class VisionEngine:
    """
    Remote-camera mode: browser sends JPEG frames via SocketIO.
    Runs posture on every frame, emotion on every 2nd frame.
    """

    def __init__(self, on_result=None):
        self.posture = PostureDetector()
        self.emotion = EmotionDetector()

        self._lock          = threading.Lock()
        self._latest_result = {}
        self._running       = False
        self._on_result     = on_result

        self._frame_event   = threading.Event()
        self._pending_frame = None
        self._frame_count   = 0
        self._emotion_every = 2        # run emotion every 2nd frame (was 3)
        self._cached_emotion = []

        print("[VisionEngine] Ready. Waiting for browser camera frames.")

    def push_frame(self, jpeg_b64: str):
        """Called by SocketIO handler when browser sends a camera frame."""
        try:
            data = base64.b64decode(jpeg_b64.split(',')[-1])
            arr  = np.frombuffer(data, np.uint8)
            frame = cv2.imdecode(arr, cv2.IMREAD_COLOR)
            if frame is None:
                return
            with self._lock:
                self._pending_frame = frame
            self._frame_event.set()
        except Exception as e:
            print(f"[VisionEngine] push_frame error: {e}")

    def start(self):
        self._running = True
        t = threading.Thread(target=self._inference_loop, daemon=True)
        t.start()

    def stop(self):
        self._running = False
        self._frame_event.set()

    def _inference_loop(self):
        while self._running:
            triggered = self._frame_event.wait(timeout=1.0)
            if not triggered:
                continue
            self._frame_event.clear()

            with self._lock:
                frame = self._pending_frame
                self._pending_frame = None

            if frame is None:
                continue

            self._frame_count += 1
            try:
                posture_result = self.posture.detect(frame)

                # Run emotion every Nth frame to save CPU
                if self._frame_count % self._emotion_every == 0:
                    detected = self.emotion.detect(frame)
                    if detected:                     # only update if we got something
                        self._cached_emotion = detected

                result = {
                    'posture':     posture_result,
                    'emotion':     self._cached_emotion,
                    'timestamp':   time.time(),
                    'frame_count': self._frame_count,
                }

                with self._lock:
                    self._latest_result = result

                if self._on_result:
                    self._on_result(result)

            except Exception as e:
                print(f"[VisionEngine] Inference error: {e}")
                import traceback; traceback.print_exc()

    def get_latest(self):
        with self._lock:
            return dict(self._latest_result)
