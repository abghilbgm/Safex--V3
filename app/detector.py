"""
detector.py — wraps Ultralytics YOLO, normalizes class names via config.CLASS_MAP.
"""
import logging
from dataclasses import dataclass
from typing import List

from ultralytics import YOLO

from . import config

logger = logging.getLogger("ppe.detector")


@dataclass
class Detection:
    cls_raw: str
    cls_norm: str
    confidence: float
    x1: int
    y1: int
    x2: int
    y2: int

    @property
    def box(self):
        return (self.x1, self.y1, self.x2, self.y2)


class PPEDetector:
    def __init__(self, model_path: str = config.MODEL_PATH, device: str = config.DEVICE):
        logger.info(f"Loading PPE model from {model_path} on device={device}")
        self.model = YOLO(model_path)
        self.device = device
        self.names = self.model.names

    def infer(self, frame) -> List[Detection]:
        results = self.model.predict(
            source=frame, conf=config.CONFIDENCE_THRESHOLD, iou=config.IOU_THRESHOLD,
            imgsz=config.INFERENCE_IMG_SIZE, device=self.device, verbose=False,
        )
        detections: List[Detection] = []
        if not results:
            return detections
        r = results[0]
        if r.boxes is None:
            return detections
        for box in r.boxes:
            cls_id = int(box.cls[0].item())
            raw_name = self.names.get(cls_id, str(cls_id))
            norm_name = config.CLASS_MAP.get(raw_name, raw_name.lower())
            conf = float(box.conf[0].item())
            x1, y1, x2, y2 = [int(v) for v in box.xyxy[0].tolist()]
            detections.append(Detection(cls_raw=raw_name, cls_norm=norm_name, confidence=conf,
                                         x1=x1, y1=y1, x2=x2, y2=y2))
        return detections
