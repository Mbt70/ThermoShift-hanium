import math
from typing import Dict, Any, List, Tuple
from datetime import datetime, timezone
from app.config import get_config
from app.storage import get_storage
import logging

logger = logging.getLogger(__name__)

S_EMPTY = 0
S_TRANSITION = 1
S_OCCUPIED = 2

class OccupancyHMM:
    def __init__(self):
        self.config = get_config()
        self.storage = get_storage()
        self.transition_matrix = self.config.hmm.transition_matrix_30s
        
        self.probs = [0.333, 0.334, 0.333]
        self.state = "UNKNOWN"
        self.consecutive_occupied_prob_high = 0
        self.last_update = datetime.now(timezone.utc)
        self.reasons: List[str] = []

    def _get_observation_likelihoods(self, features: Dict[str, Any]) -> List[float]:
        L = [1.0, 1.0, 1.0]

        if features["pir_recent"]:
            L[S_EMPTY] *= 0.03
            L[S_TRANSITION] *= 0.55
            L[S_OCCUPIED] *= 0.95
            self.reasons.append(f"PIR detected {int(features['pir_age_sec'])} seconds ago")
        else:
            L[S_EMPTY] *= 0.90
            L[S_TRANSITION] *= 0.55
            L[S_OCCUPIED] *= 0.45

        if features["door_recent"]:
            L[S_EMPTY] *= 0.25
            L[S_TRANSITION] *= 0.95
            L[S_OCCUPIED] *= 0.45
            self.reasons.append(f"door event detected {int(features['door_age_sec'])} seconds ago")

        if features["co2_slope_5m"] > 6.0:
            L[S_EMPTY] *= 0.08
            L[S_TRANSITION] *= 0.55
            L[S_OCCUPIED] *= 0.90
            self.reasons.append(f"CO2 rising at {features['co2_slope_5m']:.1f} ppm/min")
        elif features["co2_slope_5m"] < -3.0:
            L[S_EMPTY] *= 0.90
            L[S_TRANSITION] *= 0.55
            L[S_OCCUPIED] *= 0.25
            self.reasons.append(f"CO2 falling at {features['co2_slope_5m']:.1f} ppm/min")

        if features["co2_delta_baseline"] > 250.0:
            L[S_EMPTY] *= 0.20
            L[S_TRANSITION] *= 0.65
            L[S_OCCUPIED] *= 0.85
            self.reasons.append(f"CO2 delta baseline high ({features['co2_delta_baseline']:.1f} ppm)")

        return L

    def update(self, features: Dict[str, Any]) -> Tuple[str, List[float], List[str]]:
        self.reasons = []
        
        prior = [0.0, 0.0, 0.0]
        for i in range(3):
            for j in range(3):
                prior[j] += self.probs[i] * self.transition_matrix[i][j]

        likelihoods = self._get_observation_likelihoods(features)
        
        posterior = [prior[i] * likelihoods[i] for i in range(3)]
        
        total = sum(posterior)
        if total > 0:
            self.probs = [p / total for p in posterior]
        else:
            self.probs = [0.333, 0.334, 0.333]

        if features["pir_recent"]:
            self.probs = [0.01, 0.04, 0.95] # strong correction but avoid absolute 1.0 to prevent zeroing
        
        p_emp, p_trans, p_occ = self.probs

        self.reasons.append(f"occupancy probability updated to {p_occ:.2f}")

        if p_occ >= 0.65:
            self.consecutive_occupied_prob_high += 1
        else:
            self.consecutive_occupied_prob_high = 0

        new_state = "TRANSITION"
        
        if self.consecutive_occupied_prob_high >= 2 or features["pir_recent"]:
            new_state = "OCCUPIED"
        elif p_emp >= 0.85 \
             and features["pir_age_sec"] >= 900 \
             and features["door_age_sec"] >= 300 \
             and features["co2_slope_5m"] <= 0:
            new_state = "EMPTY"

        if not features["occ_fresh"]:
            if new_state == "EMPTY":
                new_state = "TRANSITION"
                self.reasons.append("OCC data stale, preventing EMPTY state")

        self.state = new_state
        self.last_update = datetime.now(timezone.utc)
        
        self.storage.insert_occupancy_estimate(
            self.last_update.isoformat(),
            self.probs[S_EMPTY], self.probs[S_TRANSITION], self.probs[S_OCCUPIED],
            self.state, "OK" if features["occ_fresh"] else "STALE", self.reasons
        )

        return self.state, self.probs, self.reasons

_hmm_instance = None
def get_occupancy_hmm() -> OccupancyHMM:
    global _hmm_instance
    if _hmm_instance is None:
        _hmm_instance = OccupancyHMM()
    return _hmm_instance
