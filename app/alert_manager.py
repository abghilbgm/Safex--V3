"""
alert_manager.py — dispatches Teams/email alerts for a violation, driven by
whichever alert_rules matched.
"""
import time
import smtplib
import logging
import asyncio
import requests
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from typing import Optional, List

from . import config, db
from .rules_engine import RulesEngine, ViolationEvent, MatchedAlert

logger = logging.getLogger("ppe.alerts")

_VIOLATION_LABELS = {
    "no_helmet": "Missing Helmet", "no_vest": "Missing Safety Vest",
    "no_gloves": "Missing Gloves", "no_boots": "Missing Safety Boots",
    "no_goggles": "Missing Goggles", "no_mask": "Missing Mask",
}


class AlertManager:
    def __init__(self):
        self.rules_engine = RulesEngine()

    async def handle_violation(self, violation_id: int, camera_id: str, camera_name: str,
                                zone: str, track_id: int, violation_type: str,
                                snapshot_path: Optional[str] = None) -> List[MatchedAlert]:
        if not config.ALERTS_ENABLED:
            return []

        event = ViolationEvent(camera_id, camera_name, zone, track_id, violation_type)
        matches = await self.rules_engine.evaluate(event)
        if not matches:
            return []

        label = _VIOLATION_LABELS.get(violation_type, violation_type)
        for match in matches:
            for channel in match.channels:
                success = await self._dispatch(channel, camera_name, zone, label,
                                                 match.email_recipients, snapshot_path)
                await db.log_alert_dispatch(violation_id, match.rule_id, channel, success)

        await db.mark_alert_dispatched(violation_id)
        return matches

    async def _dispatch(self, channel, camera_name, zone, label, email_recipients, snapshot_path) -> bool:
        if channel == "teams":
            return await asyncio.to_thread(self._send_teams, camera_name, zone, label)
        elif channel == "email":
            recipients = email_recipients or config.ALERT_EMAIL_TO_DEFAULT
            if not recipients:
                logger.warning("Email channel matched but no recipients configured")
                return False
            body = (f"PPE Violation Detected\nCamera: {camera_name}\nZone: {zone}\n"
                    f"Violation: {label}\nTime: {time.strftime('%Y-%m-%d %H:%M:%S')}")
            return await asyncio.to_thread(self._send_email, recipients, body, snapshot_path)
        else:
            logger.warning(f"Unknown alert channel '{channel}'")
            return False

    def _send_teams(self, camera_name: str, zone: str, label: str) -> bool:
        if not config.TEAMS_WEBHOOK_URL:
            logger.warning("Teams channel matched but PPE_TEAMS_WEBHOOK not configured")
            return False
        card = {
            "@type": "MessageCard", "@context": "http://schema.org/extensions",
            "themeColor": "D93025", "summary": "PPE Violation Detected",
            "title": f"PPE Violation: {label}",
            "sections": [{"facts": [
                {"name": "Camera", "value": camera_name}, {"name": "Zone", "value": zone},
                {"name": "Violation", "value": label},
                {"name": "Time", "value": time.strftime("%Y-%m-%d %H:%M:%S")},
            ], "markdown": True}],
        }
        try:
            resp = requests.post(config.TEAMS_WEBHOOK_URL, json=card, timeout=8)
            resp.raise_for_status()
            return True
        except Exception as e:
            logger.error(f"Teams alert failed: {e}")
            return False

    def _send_email(self, recipients: List[str], body: str, snapshot_path: Optional[str]) -> bool:
        if not config.SMTP_HOST:
            logger.warning("Email channel matched but PPE_SMTP_HOST not configured")
            return False
        try:
            msg = MIMEMultipart()
            msg["From"] = config.ALERT_EMAIL_FROM
            msg["To"] = ", ".join(recipients)
            msg["Subject"] = "PPE Compliance Violation Alert"
            msg.attach(MIMEText(body, "plain"))
            if snapshot_path:
                try:
                    with open(snapshot_path, "rb") as f:
                        img = MIMEImage(f.read())
                        img.add_header("Content-Disposition", "attachment", filename="violation.jpg")
                        msg.attach(img)
                except FileNotFoundError:
                    pass
            with smtplib.SMTP(config.SMTP_HOST, config.SMTP_PORT, timeout=10) as server:
                server.starttls()
                if config.SMTP_USER:
                    server.login(config.SMTP_USER, config.SMTP_PASSWORD)
                server.sendmail(config.ALERT_EMAIL_FROM, recipients, msg.as_string())
            return True
        except Exception as e:
            logger.error(f"Email alert failed: {e}")
            return False
