"""quick_test.py - visually verify PPE detection without the full stack."""
import sys, os
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_PROJECT_ROOT = os.path.dirname(_THIS_DIR)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse, time, cv2
from app.detector import PPEDetector
from app.compliance_engine import ComplianceEngine
from app import config

def draw(frame, statuses):
    for status in statuses:
        x1, y1, x2, y2 = status.box
        color = (0, 0, 255) if status.is_violation else (0, 200, 0)
        cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
        label = f"ID{status.track_id} " + ("MISSING: " + ",".join(sorted(status.missing_ppe)) if status.is_violation else "OK")
        cv2.putText(frame, label, (x1, max(20, y1 - 8)), cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2)
    return frame

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", required=True)
    parser.add_argument("--required-ppe", default="helmet,vest")
    args = parser.parse_args()
    required_ppe = [p.strip() for p in args.required_ppe.split(",") if p.strip()]
    detector = PPEDetector()
    engine = ComplianceEngine("TEST", required_ppe)
    source = args.source
    if source.isdigit():
        source = int(source)
    if isinstance(source, str) and source.lower().endswith((".jpg", ".jpeg", ".png", ".bmp")):
        frame = cv2.imread(source)
        detections = detector.infer(frame)
        for _ in range(config.VIOLATION_CONFIRM_FRAMES):
            statuses = engine.evaluate(detections)
        cv2.imwrite("quick_test_output.jpg", draw(frame.copy(), statuses))
        print("Saved quick_test_output.jpg")
        return
    cap = cv2.VideoCapture(source)
    frame_count = 0
    last_statuses = []
    while True:
        ok, frame = cap.read()
        if not ok: break
        frame_count += 1
        if frame_count % config.FRAME_SKIP == 0:
            last_statuses = engine.evaluate(detector.infer(frame))
        try:
            cv2.imshow("PPE Quick Test", draw(frame.copy(), last_statuses))
            if cv2.waitKey(1) & 0xFF == ord("q"): break
        except cv2.error:
            if frame_count % 30 == 0:
                cv2.imwrite("quick_test_output.jpg", draw(frame.copy(), last_statuses))
    cap.release()

if __name__ == "__main__":
    main()
