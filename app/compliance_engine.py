"""
compliance_engine.py — matches PPE detections to persons, tracks violation
streaks so momentary occlusion/bad angle doesn't trigger false alerts.
"""
from dataclasses import dataclass, field
from typing import List, Dict, Set, Tuple

from . import config
from .detector import Detection


def _overlap_fraction_of_b(box_a, box_b) -> float:
    ax1, ay1, ax2, ay2 = box_a
    bx1, by1, bx2, by2 = box_b
    ix1, iy1 = max(ax1, bx1), max(ay1, by1)
    ix2, iy2 = min(ax2, bx2), min(ay2, by2)
    iw, ih = max(0, ix2 - ix1), max(0, iy2 - iy1)
    inter = iw * ih
    area_b = max(1, (bx2 - bx1) * (by2 - by1))
    return inter / area_b


@dataclass
class PersonStatus:
    track_id: int
    box: Tuple[int, int, int, int]
    present_ppe: Set[str] = field(default_factory=set)
    missing_ppe: Set[str] = field(default_factory=set)
    is_violation: bool = False


class _SimpleTracker:
    def __init__(self, max_distance: int = 80, max_missed: int = 15):
        self.max_distance = max_distance
        self.max_missed = max_missed
        self._next_id = 1
        self.tracks: Dict[int, Dict] = {}

    def update(self, person_boxes):
        centroids = [((b[0] + b[2]) // 2, (b[1] + b[3]) // 2) for b in person_boxes]
        assigned = {}
        used = set()
        for box, centroid in zip(person_boxes, centroids):
            best_id, best_dist = None, float("inf")
            for tid, t in self.tracks.items():
                if tid in used:
                    continue
                d = ((t["centroid"][0] - centroid[0]) ** 2 + (t["centroid"][1] - centroid[1]) ** 2) ** 0.5
                if d < self.max_distance and d < best_dist:
                    best_id, best_dist = tid, d
            if best_id is None:
                best_id = self._next_id
                self._next_id += 1
                self.tracks[best_id] = {"centroid": centroid, "missed": 0, "streaks": {}}
            else:
                self.tracks[best_id]["centroid"] = centroid
                self.tracks[best_id]["missed"] = 0
            used.add(best_id)
            assigned[best_id] = box

        for tid in list(self.tracks.keys()):
            if tid not in used:
                self.tracks[tid]["missed"] += 1
                if self.tracks[tid]["missed"] > self.max_missed:
                    del self.tracks[tid]
        return assigned

    def bump_streak(self, track_id, ppe_type) -> int:
        streaks = self.tracks[track_id]["streaks"]
        streaks[ppe_type] = streaks.get(ppe_type, 0) + 1
        return streaks[ppe_type]

    def reset_streak(self, track_id, ppe_type):
        self.tracks[track_id]["streaks"][ppe_type] = 0


class ComplianceEngine:
    def __init__(self, camera_id: str, required_ppe: List[str]):
        self.camera_id = camera_id
        self.required_ppe = required_ppe
        self.tracker = _SimpleTracker()

    def evaluate(self, detections: List[Detection]) -> List[PersonStatus]:
        persons = [d for d in detections if d.cls_norm == "person"]
        ppe_items = [d for d in detections if d.cls_norm != "person"]
        tracked = self.tracker.update([p.box for p in persons])

        results = []
        for track_id, box in tracked.items():
            present, missing = set(), set()
            for req in self.required_ppe:
                neg_cls = config.NEGATIVE_PPE_CLASSES.get(req)
                explicit_negative = any(
                    item.cls_norm == neg_cls and _overlap_fraction_of_b(box, item.box) >= config.MATCH_OVERLAP_THRESHOLD
                    for item in ppe_items
                ) if neg_cls else False
                has_positive = any(
                    item.cls_norm == req and _overlap_fraction_of_b(box, item.box) >= config.MATCH_OVERLAP_THRESHOLD
                    for item in ppe_items
                )
                if explicit_negative or not has_positive:
                    missing.add(req)
                else:
                    present.add(req)

            confirmed_missing = set()
            for ppe_type in missing:
                if self.tracker.bump_streak(track_id, ppe_type) >= config.VIOLATION_CONFIRM_FRAMES:
                    confirmed_missing.add(ppe_type)
            for ppe_type in present:
                self.tracker.reset_streak(track_id, ppe_type)

            results.append(PersonStatus(track_id=track_id, box=box, present_ppe=present,
                                         missing_ppe=confirmed_missing, is_violation=len(confirmed_missing) > 0))
        return results
