"""
config.py — central configuration. Cameras/Area Groups are DB-backed after
first boot; SEED_CAMERAS/SEED_AREA_GROUPS are used to TOP UP any missing
entries EVERY time the app starts (see db.py sync_seed_data()) - so even
if a previous run only partially seeded (e.g. crashed halfway through, or
only 1 of 16 cameras made it in), the missing ones get added automatically
on the next start, instead of being permanently skipped.
"""
import os
from typing import List, Dict

def _env(key: str, default: str = "") -> str:
    return os.environ.get(key, default)

def _env_bool(key: str, default: bool) -> bool:
    return _env(key, str(default)).lower() in ("1", "true", "yes")

# ---------------------------------------------------------------------------
# 1. SEED DATA - synced (topped up) on every startup AND via the dashboard's
#    "Sync Default Cameras" button / POST /api/cameras/sync-seed
# ---------------------------------------------------------------------------
SEED_AREA_GROUPS: List[Dict] = [
    {"name": "Substation",        "description": "High-voltage electrical substation"},
    {"name": "MCC",                "description": "Motor control center rooms"},
    {"name": "SYLOC",               "description": "SYLOC processing area"},
    {"name": "Pumphouse",            "description": "Pumphouse and pumphouse MCC"},
    {"name": "Yard",                  "description": "Container yard and scrap yard"},
    {"name": "Gates & Security",       "description": "Plant entry/exit gates and security posts"},
    {"name": "Safety",                  "description": "Designated safety zones"},
    {"name": "Facilities",               "description": "Canteen / non-process facilities"},
    {"name": "Process",                   "description": "Chemical process areas (e.g. Caustic)"},
]

SEED_CAMERAS: List[Dict] = [
    {"camera_id": "CAM01", "name": "CAM01", "rtsp_url": "rtsp://admin:mngr%402025@192.169.0.65:554/Streaming/Channels/101",
     "area_group_name": "Substation", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM02", "name": "CAM02", "rtsp_url": "rtsp://admin:mngr%402025@192.169.0.65:554/Streaming/Channels/201",
     "area_group_name": "MCC", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM03", "name": "SYLOC 2", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/501",
     "area_group_name": "SYLOC", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM04", "name": "SYLOC 1", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/601",
     "area_group_name": "SYLOC", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM05", "name": "Pumphouse MCC Inside", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/701",
     "area_group_name": "Pumphouse", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM06", "name": "Pumphouse 1", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/801",
     "area_group_name": "Pumphouse", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM07", "name": "Pumphouse MCC Outside", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/901",
     "area_group_name": "Pumphouse", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM08", "name": "Container Yard", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/201",
     "area_group_name": "Yard", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM09", "name": "AG Gate PTZ", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/302",
     "area_group_name": "Gates & Security", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM10", "name": "Safety Corner", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/601",
     "area_group_name": "Safety", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM11", "name": "Ahara Bhuvan", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1001",
     "area_group_name": "Facilities", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM12", "name": "Caustic", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1101",
     "area_group_name": "Process", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM13", "name": "Admin Gate", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1201",
     "area_group_name": "Gates & Security", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM14", "name": "Admin Entrance", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1301",
     "area_group_name": "Gates & Security", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM15", "name": "AG Security", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1401",
     "area_group_name": "Gates & Security", "required_ppe": ["helmet", "vest"]},
    {"camera_id": "CAM16", "name": "Scrap Yard", "rtsp_url": "rtsp://admin:mngr1234@192.168.100.65:554/Streaming/Channels/1502",
     "area_group_name": "Yard", "required_ppe": ["helmet", "vest"]},
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
# 5. ALERTING
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
PG_POOL_MIN: int = int(_env("POSTGRES_POOL_MIN", "4"))
PG_POOL_MAX: int = int(_env("POSTGRES_POOL_MAX", "30"))
PG_CONNECT_RETRY_SECONDS: int = int(_env("POSTGRES_CONNECT_RETRY_SECONDS", "60"))

SNAPSHOT_DIR: str = _env("PPE_SNAPSHOT_DIR", "snapshots")

# ---------------------------------------------------------------------------
# 7. DASHBOARD / API
# ---------------------------------------------------------------------------
API_HOST: str = _env("PPE_API_HOST", "0.0.0.0")
API_PORT: int = int(_env("PPE_API_PORT", "8080"))
JPEG_QUALITY: int = int(_env("PPE_JPEG_QUALITY", "82"))
BROADCAST_FPS: int = int(_env("PPE_BROADCAST_FPS", "12"))
CAMERA_STATUS_UPDATE_INTERVAL: float = float(_env("PPE_STATUS_UPDATE_INTERVAL", "4"))
