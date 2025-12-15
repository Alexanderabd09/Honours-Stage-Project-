import time
from collections import deque

class DecisionEngine:
    def __init__(self, confirm_frames: int, temporary_gap_mph: float,
                 overspeed_tolerance_mph: float, overspeed_hold_seconds: float,
                 gps_min_moving_mps: float, logger):
        self.confirm_frames = confirm_frames
        self.temporary_gap_mph = temporary_gap_mph
        self.overspeed_tolerance_mph = overspeed_tolerance_mph
        self.overspeed_hold_seconds = overspeed_hold_seconds
        self.gps_min_moving_mps = gps_min_moving_mps
        self.logger = logger

        self._recent_speeds = deque(maxlen=confirm_frames)
        self._overspeed_start_ts = None

        self.current_sign_mph = None
        self.last_event = None  # dict describing last decision

    @staticmethod
    def mps_to_mph(v_mps: float) -> float:
        return v_mps * 2.236936

    def update(self, top_detected_mph: int | None, gps_speed_mps: float | None, map_speed_mph: int | None):
        """
        Returns an event dict with keys:
          sign_confirmed_mph, is_temporary, is_overspeed, gps_mph, map_mph
        or None if insufficient data.
        """
        now = time.time()

        # GPS sanity
        gps_mph = None
        moving = False
        if gps_speed_mps is not None:
            gps_mph = self.mps_to_mph(gps_speed_mps)
            moving = gps_speed_mps >= self.gps_min_moving_mps

        # Update stable detection buffer
        if top_detected_mph is not None:
            self._recent_speeds.append(top_detected_mph)
        else:
            self._recent_speeds.clear()
            self.current_sign_mph = None
            self._overspeed_start_ts = None
            return None

        # Confirm if last N detections are identical
        if len(self._recent_speeds) < self.confirm_frames:
            return None

        if len(set(self._recent_speeds)) == 1:
            confirmed = self._recent_speeds[-1]
        else:
            return None

        self.current_sign_mph = confirmed

        # Temporary classification
        is_temporary = False
        map_known = map_speed_mph is not None
        if map_known:
            if confirmed <= (map_speed_mph - self.temporary_gap_mph):
                is_temporary = True

        # Overspeed logic (requires moving + gps)
        is_overspeed = False
        if moving and gps_mph is not None:
            if gps_mph >= confirmed + self.overspeed_tolerance_mph:
                if self._overspeed_start_ts is None:
                    self._overspeed_start_ts = now
                elif (now - self._overspeed_start_ts) >= self.overspeed_hold_seconds:
                    is_overspeed = True
            else:
                self._overspeed_start_ts = None

        event = {
            "sign_confirmed_mph": confirmed,
            "map_mph": map_speed_mph,
            "gps_mph": gps_mph,
            "is_temporary": is_temporary,
            "is_overspeed": is_overspeed,
            "map_known": map_known,
            "ts": now
        }
        self.last_event = event
        return event
