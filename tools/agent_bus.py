import time
from typing import Any, Dict, List, Optional
from tools.dashboard import dashboard

class AgentBlackboard:
    """
    Structured Hub-and-Spoke communication ledger.
    Subagents publish typed artifacts here, and peer agents read them
    without polluting context windows with raw conversational back-and-forth.
    """

    def __init__(self):
        self._artifacts: List[Dict[str, Any]] = []

    def publish(self, sender: str, artifact_type: str, payload: Any, metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Publishes a typed artifact to the board.
        Types: PLAN, CODE_PATCH, SECURITY_AUDIT, REVIEW_DECISION
        """
        entry = {
            "id": len(self._artifacts) + 1,
            "sender": sender,
            "type": artifact_type,
            "payload": payload,
            "metadata": metadata or {},
            "timestamp": time.time(),
        }
        self._artifacts.append(entry)

        dashboard.emit("LOG_STREAM", {
            "message": f"[Blackboard] {sender} published {artifact_type} (#{entry['id']})"
        })
        return entry

    def get_latest(self, artifact_type: str) -> Optional[Dict[str, Any]]:
        for entry in reversed(self._artifacts):
            if entry["type"] == artifact_type:
                return entry
        return None

    def get_all(self, artifact_type: Optional[str] = None) -> List[Dict[str, Any]]:
        if artifact_type:
            return [e for e in self._artifacts if e["type"] == artifact_type]
        return list(self._artifacts)

    def clear(self) -> None:
        self._artifacts.clear()

# Global blackboard instance for current run
blackboard = AgentBlackboard()
