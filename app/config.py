"""
config.py
---------
Central configuration. Cameras and Area Groups are now DYNAMIC - managed
via the dashboard's Cameras tab and stored in PostgreSQL (`cameras` and
`area_groups` tables), NOT hardcoded here anymore.

SEED_CAMERAS below is used ONLY on first startup, if the `cameras` table is
empty, to bootstrap something to work with. After that, all camera
add/edit/delete/refresh operations go through the dashboard or /api/cameras
- this file is no longer read for camera config after the first boot.
"""
import os
from typing import List, Dict

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _env_bool(key: str, default: bool) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# 1. SEED DATA (first-boot only, if `cameras`/`area_groups` tables are empty)
# ---------------------------------------------------------------------------
SEED_AREA_GROUPS: List[Dict] = [
    {"name": "Substation", "description": "High-voltage electrical zones"},
    {"name": "MCC Rooms", "description": "Motor control center rooms"},
]

SEED_CAMERAS: List[Dict] = [
    {
        "camera_id": "CAM01",
        "name": "Substation Entry Gate",
        "rtsp_url": _env("CAM01_RTSP", "rtsp://admin:password@192.168.1.51:554/stream1"),
        "area_group_name": "Substation",
        "required_ppe": ["helmet", "vest"],
    },
    {
        "camera_id": "CAM02",
        "name": "MCC Room Entry",
        "rtsp_url": _env("CAM02_RTSP", "rtsp://admin:password@192.168.1.52:554/stream1"),
        "area_group_name": "MCC Rooms",
        "required_ppe": ["helmet", "vest"],
    },
]

# ---------------------------------------------------------------------------
# 2. MODEL SETTINGS
# ---------------------------------------------------------------------------
MODEL_PATH: str = _env("PPE_MODEL_PATH", "models/best.pt")
DEVICE: str = _env("PPE_DEVICE", "cpu")
CONFIDENCE_THRESHOLD: float = float(_env("PPE_CONF_THRESHOLD", "0.45"))
IOU_THRESHOLD: float = float(_env("PPE_IOU_THRESHOLD", "0.45"))
INFERENCE_IMG_SIZE: int = int(_env("PPE_IMG_SIZE", "640"))
FRAME_SKIP: int = int(_env("PPE_FRAME_SKIP", "2"))

# ---------------------------------------------------------------------------
# 3. CLASS MAPPING
# ---------------------------------------------------------------------------
CLASS_MAP: Dict[str, str] = {
    "person": "person", "Person": "person",
    "helmet": "helmet", "Helmet": "helmet", "Hardhat": "helmet", "hardhat": "helmet",
    "no-helmet": "no_helmet", "No-Helmet": "no_helmet", "NO-Hardhat": "no_helmet", "no_hardhat": "no_helmet",
    "vest": "vest", "Vest": "vest", "Safety Vest": "vest", "safety_vest": "vest",
    "no-vest": "no_vest", "No-Vest": "no_vest", "NO-Safety Vest": "no_vest",
    "gloves": "gloves", "Gloves": "gloves", "no-gloves": "no_gloves",
    "boots": "boots", "Safety Boots": "boots", "safety_shoe": "boots", "no-boots": "no_boots",
    "goggles": "goggles", "Goggles": "goggles", "no-goggle": "no_goggles",
    "mask": "mask", "Mask": "mask", "no-mask": "no_mask", "NO-Mask": "no_mask",
}

POSITIVE_PPE_CLASSES = {"helmet", "vest", "gloves", "boots", "goggles", "mask"}
NEGATIVE_PPE_CLASSES = {
    "helmet": "no_helmet", "vest": "no_vest", "gloves": "no_gloves",
    "boots": "no_boots", "goggles": "no_goggles", "mask": "no_mask",
}

# ---------------------------------------------------------------------------
# 4. COMPLIANCE LOGIC
# ---------------------------------------------------------------------------
MATCH_OVERLAP_THRESHOLD: float = 0.30
VIOLATION_CONFIRM_FRAMES: int = int(_env("PPE_VIOLATION_CONFIRM_FRAMES", "5"))

# ---------------------------------------------------------------------------
# 5. ALERTING (channel credentials only - conditions live in alert_rules)
# ---------------------------------------------------------------------------
ALERTS_ENABLED: bool = _env_bool("PPE_ALERTS_ENABLED", True)
TEAMS_WEBHOOK_URL: str = _env("PPE_TEAMS_WEBHOOK", "")
SMTP_HOST: str = _env("PPE_SMTP_HOST", "")
SMTP_PORT: int = int(_env("PPE_SMTP_PORT", "587"))
SMTP_USER: str = _env("PPE_SMTP_USER", "")
SMTP_PASSWORD: str = _env("PPE_SMTP_PASSWORD", "")
ALERT_EMAIL_FROM: str = _env("PPE_ALERT_EMAIL_FROM", SMTP_USER)
ALERT_EMAIL_TO_DEFAULT: List[str] = [e.strip() for e in _env("PPE_ALERT_EMAIL_TO", "").split(",") if e.strip()]

# ---------------------------------------------------------------------------
# 6. POSTGRESQL
# ---------------------------------------------------------------------------
PG_HOST: str = _env("POSTGRES_HOST", "localhost")
PG_PORT: int = int(_env("POSTGRES_PORT", "5432"))
PG_DB: str = _env("POSTGRES_DB", "ppe_compliance")
PG_USER: str = _env("POSTGRES_USER", "ppe_user")
PG_PASSWORD: str = _env("POSTGRES_PASSWORD", "ppe_password")
PG_POOL_MIN: int = int(_env("POSTGRES_POOL_MIN", "2"))
PG_POOL_MAX: int = int(_env("POSTGRES_POOL_MAX", "10"))

SNAPSHOT_DIR: str = _env("PPE_SNAPSHOT_DIR", "snapshots")

# ---------------------------------------------------------------------------
# 7. DASHBOARD / API
# ---------------------------------------------------------------------------
API_HOST: str = _env("PPE_API_HOST", "0.0.0.0")
API_PORT: int = int(_env("PPE_API_PORT", "8080"))
JPEG_QUALITY: int = int(_env("PPE_JPEG_QUALITY", "82"))
BROADCAST_FPS: int = int(_env("PPE_BROADCAST_FPS", "12"))
