import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional
from app.config import get_config
from app.storage import get_storage
from app.ir_adapter import IRAdapter
from app.data_quality import get_data_quality
from app.feature_engine import get_feature_engine
from app.occupancy_hmm import get_occupancy_hmm

logger = logging.getLogger(__name__)

class HVACController:
    def __init__(self, ir_adapter: IRAdapter):
        self.config = get_config()
        self.storage = get_storage()
        self.ir = ir_adapter
        
        self.last_on_time: Optional[datetime] = None
        self.last_off_time: Optional[datetime] = None
        self.current_action: str = "POWER_OFF"
        self.last_decision_time: Optional[datetime] = None

    def _check_sustained_temp(self, history, threshold, over, duration_sec, now):
        cutoff = now - timedelta(seconds=duration_sec)
        window = [x for x in history if x[0] >= cutoff]
        if not window:
            return False
        # Ensure we have data covering at least the duration
        if (now - window[0][0]).total_seconds() < duration_sec * 0.8:
            return False
        
        if over:
            return all(x[1] >= threshold for x in window)
        else:
            return all(x[1] <= threshold for x in window)

    def decide(self, features: Dict[str, Any], occupancy_state: str, p_occ: Dict[str, float]) -> dict:
        now = datetime.now(timezone.utc)
        self.last_decision_time = now
        
        reasons = []
        proposed_action = self.current_action
        executed = False
        
        temp_c = None
        co2_ppm = None
        
        dq = get_data_quality()
        fe = get_feature_engine()
        
        env_data = next(iter(dq.latest_env.values()), None)
        if env_data:
            temp_c = env_data.temperature_c
            co2_ppm = env_data.co2_ppm

        c = self.config.control
        
        min_off_satisfied = True
        if self.last_off_time:
            if (now - self.last_off_time).total_seconds() < c.minimum_off_time_sec:
                min_off_satisfied = False

        min_on_satisfied = True
        if self.last_on_time:
            if (now - self.last_on_time).total_seconds() < c.minimum_on_time_sec:
                min_on_satisfied = False

        failsafe = False
        if not features["env_fresh"]:
            reasons.append("ENV_STALE")
            failsafe = True
            
        locked_out = self.ir.is_locked_out()
        if locked_out:
            reasons.append("MANUAL_LOCKOUT")
            
        if co2_ppm and co2_ppm >= c.co2_critical_ppm:
            reasons.append("CO2_CRITICAL")
            self.storage.insert_system_event(now.isoformat(), "CRITICAL", "CO2_ALERT", f"CO2 reached {co2_ppm} ppm")
        elif co2_ppm and co2_ppm >= c.co2_ventilation_warning_ppm:
            # We don't have ventilation actuator, just log
            reasons.append("VENTILATE_RECOMMENDED")

        temp_high_sustained = self._check_sustained_temp(fe.temp_history, c.cooling_on_temperature_c, True, c.cooling_on_duration_sec, now)
        temp_low_sustained = self._check_sustained_temp(fe.temp_history, c.cooling_off_temperature_c, False, c.cooling_off_duration_sec, now)

        if failsafe:
            pass # Keep current_action
        elif occupancy_state == "OCCUPIED":
            reasons.append("OCCUPIED_CONFIRMED")
            if temp_high_sustained:
                reasons.append("TEMPERATURE_HIGH_3MIN")
                if min_off_satisfied and not locked_out:
                    reasons.append("MIN_OFF_TIME_SATISFIED")
                    proposed_action = f"COOL_{int(c.target_temperature_c)}_AUTO"
            elif temp_low_sustained:
                reasons.append("TEMPERATURE_LOW_5MIN")
                if min_on_satisfied:
                    reasons.append("MIN_ON_TIME_SATISFIED")
                    proposed_action = "POWER_OFF"
        
        elif occupancy_state == "EMPTY":
            reasons.append("EMPTY_CONFIRMED")
            proposed_action = "POWER_OFF"
            
        elif occupancy_state == "TRANSITION":
            reasons.append("TRANSITION_MAINTAIN_STATE")

        if proposed_action != self.current_action:
            if self.config.app.control_mode == "active" and not locked_out:
                self.ir.send_command(proposed_action)
                executed = True
                self.current_action = proposed_action
                if proposed_action == "POWER_OFF":
                    self.last_off_time = now
                else:
                    self.last_on_time = now
            else:
                reasons.append("SHADOW_MODE_NO_TRANSMIT" if not locked_out else "LOCKOUT_NO_TRANSMIT")
        
        decision = {
            "timestamp": now.isoformat(),
            "control_mode": self.config.app.control_mode,
            "occupancy_state": occupancy_state,
            "occupancy_probabilities": p_occ,
            "temperature_c": temp_c,
            "co2_ppm": co2_ppm,
            "proposed_action": proposed_action,
            "executed": executed,
            "reason_codes": reasons
        }
        
        self.storage.insert_control_decision(
            now.isoformat(),
            self.config.app.control_mode,
            proposed_action,
            executed,
            occupancy_state,
            temp_c,
            co2_ppm,
            reasons,
            estimate_id=get_occupancy_hmm().last_estimate_id,
        )
        
        return decision
