from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List
from app.data_quality import get_data_quality
from app.storage import get_storage
import logging

logger = logging.getLogger(__name__)

class FeatureEngine:
    def __init__(self):
        self.data_quality = get_data_quality()
        self.storage = get_storage()
        
        self.last_pir_time: datetime = None
        self.last_door_time: datetime = None
        
        self.co2_history: List[tuple] = []
        self.temp_history: List[tuple] = []
        
    def _update_histories(self, now: datetime):
        # We need to add latest env/occ if they changed, or just rely on data_quality callbacks.
        # It's better to just read the latest state from data_quality.
        
        for dev_id, env in self.data_quality.latest_env.items():
            if env.co2_ppm is not None:
                # Add if not duplicate timestamp
                if not self.co2_history or self.co2_history[-1][0] < env.timestamp:
                    self.co2_history.append((env.timestamp, env.co2_ppm))
            if env.temperature_c is not None:
                if not self.temp_history or self.temp_history[-1][0] < env.timestamp:
                    self.temp_history.append((env.timestamp, env.temperature_c))
        
        for dev_id, occ in self.data_quality.latest_occ.items():
            if occ.pir:
                if not self.last_pir_time or self.last_pir_time < occ.timestamp:
                    self.last_pir_time = occ.timestamp
            if occ.door_event:
                if not self.last_door_time or self.last_door_time < occ.timestamp:
                    self.last_door_time = occ.timestamp

        # clear processed occ events so we don't count them again incorrectly
        for dev_id, occ in self.data_quality.latest_occ.items():
            occ.door_event = False

        cutoff = now - timedelta(minutes=10)
        self.co2_history = [x for x in self.co2_history if x[0] >= cutoff]
        self.temp_history = [x for x in self.temp_history if x[0] >= cutoff]

    def _calculate_slope(self, history: List[tuple], minutes: int, now: datetime) -> float:
        cutoff = now - timedelta(minutes=minutes)
        window = [x for x in history if x[0] >= cutoff]
        if len(window) < 2:
            return 0.0
        
        x0 = window[0][0]
        x_vals = [(p[0] - x0).total_seconds() / 60.0 for p in window]
        y_vals = [p[1] for p in window]
        
        n = len(window)
        sum_x = sum(x_vals)
        sum_y = sum(y_vals)
        sum_xy = sum(x*y for x, y in zip(x_vals, y_vals))
        sum_xx = sum(x*x for x in x_vals)
        
        denominator = (n * sum_xx - sum_x * sum_x)
        if denominator == 0:
            return 0.0
            
        slope = (n * sum_xy - sum_x * sum_y) / denominator
        return slope

    def _get_co2_baseline(self) -> float:
        # In a full implementation, this would query sqlite for recent 24h empty periods
        # For now we use a default of 500.0 as requested if data is insufficient.
        return 500.0

    def compute_features(self) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        self._update_histories(now)

        pir_age_sec = (now - self.last_pir_time).total_seconds() if self.last_pir_time else 999999.0
        door_age_sec = (now - self.last_door_time).total_seconds() if self.last_door_time else 999999.0
        
        co2_slope_5m = self._calculate_slope(self.co2_history, 5, now)
        temp_slope_5m = self._calculate_slope(self.temp_history, 5, now)
        
        current_co2 = self.co2_history[-1][1] if self.co2_history else 500.0
        co2_delta_baseline = current_co2 - self._get_co2_baseline()
        co2_delta_baseline = max(0, min(co2_delta_baseline, 10000)) # clamp reasonably
        
        return {
            "pir_recent": pir_age_sec <= 120,
            "pir_age_sec": pir_age_sec,
            "door_recent": door_age_sec <= 120,
            "door_age_sec": door_age_sec,
            "co2_slope_5m": co2_slope_5m,
            "co2_delta_baseline": co2_delta_baseline,
            "temperature_slope_5m": temp_slope_5m,
            "env_fresh": not self.data_quality.is_env_stale(),
            "occ_fresh": not self.data_quality.is_occ_stale()
        }

_feature_engine_instance = None
def get_feature_engine() -> FeatureEngine:
    global _feature_engine_instance
    if _feature_engine_instance is None:
        _feature_engine_instance = FeatureEngine()
    return _feature_engine_instance
