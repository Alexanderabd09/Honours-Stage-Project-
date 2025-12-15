import time
import serial
import pynmea2

class GPSReader:
    def __init__(self, port: str, baud: int, ema_alpha: float, logger):
        self.ser = serial.Serial(port, baudrate=baud, timeout=1)
        self.alpha = ema_alpha
        self.logger = logger

        self.last_fix = None  # dict: {lat, lon, speed_mps, ts}
        self._ema_speed = None

    def close(self):
        try:
            self.ser.close()
        except Exception:
            pass

    def _ema(self, x):
        if x is None:
            return self._ema_speed
        if self._ema_speed is None:
            self._ema_speed = x
        else:
            self._ema_speed = self.alpha * x + (1 - self.alpha) * self._ema_speed
        return self._ema_speed

    def read_fix(self, max_lines=30):
        """
        Tries to read a fix. Returns dict or None.
        """
        for _ in range(max_lines):
            line = self.ser.readline().decode(errors="ignore").strip()
            if not line.startswith("$"):
                continue
            try:
                msg = pynmea2.parse(line)
            except pynmea2.ParseError:
                continue

            # RMC often contains speed over ground (knots) and lat/lon
            if msg.sentence_type == "RMC" and msg.status == "A":
                lat = msg.latitude
                lon = msg.longitude
                # speed in knots -> m/s
                try:
                    speed_knots = float(msg.spd_over_grnd) if msg.spd_over_grnd else 0.0
                except ValueError:
                    speed_knots = 0.0
                speed_mps = speed_knots * 0.514444

                speed_f = self._ema(speed_mps)
                fix = {"lat": lat, "lon": lon, "speed_mps": speed_f, "ts": time.time()}
                self.last_fix = fix
                return fix

        return None
