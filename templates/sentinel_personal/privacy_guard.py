import re
import xml.etree.ElementTree as ET
from typing import Any, Dict, List, Set

SAFE_CONTROL_LABELS: Set[str] = {
    "ok", "cancel", "submit", "next", "back", "done", "search", "settings",
    "save", "delete", "open", "close", "yes", "no", "continue", "confirm",
    "home", "menu", "send", "allow", "deny", "install", "update"
}
ALLOWED_NOTIFICATION_KEYS: Set[str] = {"id", "packageName", "postTime", "tag"}


class StructuralPrivacyGuard:
    """Enforces schema-driven allow-listing. Drops raw screen text and PII."""

    @staticmethod
    def filter_ui_hierarchy(raw_xml: str) -> List[Dict[str, Any]]:
        if not raw_xml or not raw_xml.strip():
            return []
        try:
            root = ET.fromstring(raw_xml)
        except Exception:
            return []

        interactive_nodes: List[Dict[str, Any]] = []
        for node in root.iter("node"):
            attrib = node.attrib
            clickable = attrib.get("clickable") == "true"
            checkable = attrib.get("checkable") == "true"
            resource_id = attrib.get("resource-id", "")
            class_name = attrib.get("class", "").split(".")[-1]
            bounds = attrib.get("bounds", "")
            raw_text = attrib.get("text", "").strip()

            if clickable or checkable or "button" in class_name.lower() or "edittext" in class_name.lower():
                safe_text = raw_text if raw_text.lower() in SAFE_CONTROL_LABELS else "[CONTENT_HIDDEN]"
                center_coords = None
                coords = re.findall(r"\[(\d+),(\d+)\]", bounds)
                if len(coords) == 2:
                    x1, y1 = int(coords[0][0]), int(coords[0][1])
                    x2, y2 = int(coords[1][0]), int(coords[1][1])
                    center_coords = {"x": (x1 + x2) // 2, "y": (y1 + y2) // 2}

                interactive_nodes.append({
                    "class": class_name,
                    "resource_id": resource_id if resource_id else "none",
                    "control_label": safe_text,
                    "center": center_coords,
                    "clickable": clickable,
                })
        return interactive_nodes

    @staticmethod
    def filter_notifications(raw_notifications: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        sanitized = []
        for item in raw_notifications:
            filtered_item = {k: item[k] for k in ALLOWED_NOTIFICATION_KEYS if k in item}
            filtered_item["title"] = "[NOTIFICATION_RECEIVED]"
            sanitized.append(filtered_item)
        return sanitized
