import math
import time
import json
import hashlib
from typing import Dict, Any, List, Optional, Tuple
from agent.pa_scaffolder.graph_brain import GraphBrainDB, FeatureVectorEngine


class BiometricVisionIdentity:
    """
    Biometric Face Verification & Ambient Presence Engine.
    Secures sensitive agent tasks and monitors operator presence
    using local vector geometry linked to GraphBrainDB.
    """

    DEFAULT_THRESHOLD = 0.82

    def __init__(self, brain: Optional[GraphBrainDB] = None):
        self.brain = brain or GraphBrainDB()
        self.master_node_name = "Host_Streamer"
        self.last_seen_epoch = time.time()
        self.is_present = False

    def enroll_master_face(self, feature_vector: List[float]) -> Tuple[bool, str]:
        """
        Enrolls or updates the primary operator's facial feature vector
        inside the GraphBrainDB Host_Streamer entity node.
        """
        if not feature_vector or len(feature_vector) == 0:
            return False, "Feature vector cannot be empty."

        # Normalize vector
        norm = math.sqrt(sum(x * x for x in feature_vector))
        if norm > 0:
            normalized_vec = [round(x / norm, 4) for x in feature_vector]
        else:
            return False, "Zero-magnitude feature vector provided."

        node_id = self.brain.add_or_update_node(
            name=self.master_node_name,
            category="PERSON",
            spatial_anchor="Desk_Cam",
            properties={"enrolled_at": time.time(), "biometric_vector": normalized_vec}
        )
        return True, f"Operator face enrolled successfully into node: {node_id}"

    def get_enrolled_face(self) -> Optional[List[float]]:
        """Fetches the enrolled reference vector from GraphBrainDB."""
        with self.brain._get_connection() as conn:
            cur = conn.cursor()
            cur.execute("SELECT properties FROM graph_nodes WHERE name = ? AND category = 'PERSON'", (self.master_node_name,))
            row = cur.fetchone()
            if row and row["properties"]:
                props = json.loads(row["properties"])
                return props.get("biometric_vector")
        return None

    def verify_operator_identity(self, incoming_vector: List[float], threshold: float = DEFAULT_THRESHOLD) -> Tuple[bool, float, str]:
        """
        Authenticates an incoming face against the enrolled operator.
        Returns: (is_authenticated, confidence_score, status_message)
        """
        master_vec = self.get_enrolled_face()
        if not master_vec:
            return False, 0.0, "No enrolled master face found in memory graph."

        sim = FeatureVectorEngine.cosine_similarity(incoming_vector, master_vec)
        self.last_seen_epoch = time.time()

        if sim >= threshold:
            self.is_present = True
            return True, round(sim, 3), f"Operator authenticated (Confidence: {round(sim * 100, 1)}%)"
        else:
            return False, round(sim, 3), f"Authentication rejected: Unrecognized face (Confidence: {round(sim * 100, 1)}%)"

    def evaluate_presence(self, detected_faces_count: int, primary_vector: Optional[List[float]]) -> Dict[str, Any]:
        """
        Tracks operator gaze and anti-dox presence:
        - Alerts if operator left desk
        - Alerts if an unauthorized secondary face is behind the operator
        """
        now = time.time()
        status = {
            "operator_present": False,
            "shoulder_surfer_alert": False,
            "privacy_guard_recommended": False,
            "status_whisper": None
        }

        if detected_faces_count == 0:
            self.is_present = False
            status["status_whisper"] = "Operator stepped away. Holding private notifications."
            return status

        if primary_vector:
            is_auth, score, _ = self.verify_operator_identity(primary_vector)
            status["operator_present"] = is_auth

        if detected_faces_count > 1:
            status["shoulder_surfer_alert"] = True
            status["privacy_guard_recommended"] = True
            status["status_whisper"] = "Unrecognized face detected behind you. Masking private display."

        return status
