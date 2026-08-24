"""
stream_handler.py — threaded RTSP frame grabber with automatic reconnect,
always exposing only the latest frame.

Note on PTZ cameras (e.g. "AG Gate PTZ"): panning/zooming can cause the
camera's encoder to reset its stream or drop frames momentarily. This is
normal NVR/camera behavior, not a bug in this code. The reconnect loop
below handles it automatically (frame read fails -> release -> reopen),
and the dashboard's per-camera "Reconnect" button (see camera_manager.py
refresh_camera()) lets you force an immediate manual reconnect if a
camera seems stuck instead of waiting for the automatic retry.
"""
import cv2
import time
import threading
import logging

logger = logging.getLogger("ppe.stream")


class RTSPStream:
    def __init__(self, camera_id: str, rtsp_url: str, reconnect_delay: int = 5):
        self.camera_id = camera_id
        self.rtsp_url = rtsp_url
        self.reconnect_delay = reconnect_delay
        self._cap = None
        self._frame = None
        self._lock = threading.Lock()
        self._running = False
        self._thread = None
        self.last_frame_time = 0.0
        self.connected = False

    def start(self):
        self._running = True
        self._thread = threading.Thread(target=self._update_loop, daemon=True)
        self._thread.start()
        return self

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=2)
        if self._cap:
            self._cap.release()

    def _open(self):
        cap = cv2.VideoCapture(self.rtsp_url, cv2.CAP_FFMPEG)
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    def _update_loop(self):
        while self._running:
            if self._cap is None or not self._cap.isOpened():
                logger.info(f"[{self.camera_id}] connecting to {self.rtsp_url}")
                self._cap = self._open()
                if not self._cap.isOpened():
                    self.connected = False
                    logger.warning(f"[{self.camera_id}] connection failed, retrying in {self.reconnect_delay}s")
                    time.sleep(self.reconnect_delay)
                    continue
                self.connected = True
                logger.info(f"[{self.camera_id}] connected")

            try:
                ok, frame = self._cap.read()
            except Exception as e:
                logger.warning(f"[{self.camera_id}] frame read raised {type(e).__name__}: {e}")
                ok, frame = False, None

            if not ok or frame is None:
                logger.warning(f"[{self.camera_id}] frame read failed, reconnecting")
                self.connected = False
                self._cap.release()
                self._cap = None
                time.sleep(self.reconnect_delay)
                continue

            with self._lock:
                self._frame = frame
                self.last_frame_time = time.time()

    def read(self):
        with self._lock:
            return None if self._frame is None else self._frame.copy()

    def is_stale(self, max_age_seconds: float = 10.0) -> bool:
        if self.last_frame_time == 0:
            return True
        return (time.time() - self.last_frame_time) > max_age_seconds
