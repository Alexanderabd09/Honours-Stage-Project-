"""
main_webots.py — Webots-Integrated Speed Sign Detection
=========================================================
Replaces main_hybrid.py when running with Webots simulation.

What changed vs main_hybrid.py:
  - Vehicle speed comes from Webots (real physics) via TCP socket,
    NOT from keyboard W/S.
  - Map speed limit is still adjustable via keyboard (M key).
  - Keyboard speed override is still available for testing (T key).
  - Buzzer alert plays an audible beep on temporary sign detection.
  - detector.py, decision.py, config.py are COMPLETELY UNCHANGED.

Architecture:
    ┌─────────────────────────────────┐
    │           WEBOTS                │
    │  ┌──────────────────────────┐   │
    │  │  Road World + Model Car  │   │
    │  │  (real physics speed)    │   │
    │  └────────────┬─────────────┘   │
    └───────────────│─────────────────┘
                    │ TCP :65432 (JSON speed packets)
                    ▼
    ┌───────────────────────────────────────┐
    │           main_webots.py              │
    │                                       │
    │  WebotsBridge ──► VehicleState        │
    │       (speed from Webots)             │
    │                                       │
    │  Webcam ──► YoloSpeedDetector         │
    │       (real printed signs)   ──────►  │
    │                               DecisionEngine
    │                                       │
    │                               is_temporary?
    │                                       │
    │                               ┌───────┴──────┐
    │                            YES│              │NO
    │                               ▼              ▼
    │                          BUZZER!         Log only
    └───────────────────────────────────────────────┘

Usage:
    # Start Webots first, then run:
    python main_webots.py

    # External camera:
    python main_webots.py --camera 1

    # If Webots not running yet, use fallback speed:
    python main_webots.py --fallback_speed 30

Controls (in OpenCV window):
    M       : Cycle map speed limit (20/30/40/50/60/70 mph)
    T       : Toggle manual speed override (for testing without Webots)
    W / S   : Adjust override speed (only when override active)
    Q       : Quit
"""

import argparse
import time
import socket
import threading
import json
import os
import sys
import cv2
import csv
from datetime import datetime
from typing import Optional

# ── Import your UNCHANGED modules ──────────────────────────
sys.path.insert(0, os.path.dirname(__file__))
from detector import YoloSpeedDetector
from decision import DecisionEngine
from config import Config


# ============================================================
# WEBOTS BRIDGE — replaces SimulatedVehicle keyboard control
# ============================================================

class WebotsVehicleState:
    """
    Holds the latest vehicle state received from the Webots controller.
    Thread-safe: updated by the socket listener thread,
    read by the main detection loop.
    """
    def __init__(self, fallback_speed_mph: float = 30.0):
        self.speed_mps: float = fallback_speed_mph / 2.237
        self.speed_mph: float = fallback_speed_mph
        self.pos_x: float = 0.0
        self.pos_z: float = 0.0
        self.map_speed_mph: float = 30.0
        self.connected: bool = False
        self._lock = threading.Lock()

    def update_from_webots(self, data: dict):
        with self._lock:
            self.speed_mps = data.get("speed_mps", self.speed_mps)
            self.speed_mph = data.get("speed_mph", self.speed_mph)
            self.pos_x    = data.get("pos_x", self.pos_x)
            self.pos_z    = data.get("pos_z", self.pos_z)
            self.connected = True

    def get_speed_mps(self) -> float:
        with self._lock:
            return self.speed_mps

    def get_snapshot(self) -> dict:
        with self._lock:
            return {
                "speed_mph": self.speed_mph,
                "speed_mps": self.speed_mps,
                "pos_x": self.pos_x,
                "pos_z": self.pos_z,
                "map_speed_mph": self.map_speed_mph,
                "connected": self.connected
            }


class WebotsBridge:
    """
    Background thread that connects to the Webots controller socket
    and continuously reads speed packets.
    """
    def __init__(self, vehicle: WebotsVehicleState,
                 host: str = "127.0.0.1", port: int = 65432,
                 retry_interval: float = 2.0):
        self.vehicle = vehicle
        self.host = host
        self.port = port
        self.retry_interval = retry_interval
        self._running = True
        self._thread = threading.Thread(target=self._listen, daemon=True)
        self._thread.start()

    def _listen(self):
        while self._running:
            try:
                print(f"[Bridge] Connecting to Webots on {self.host}:{self.port}...")
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                sock.settimeout(5.0)
                sock.connect((self.host, self.port))
                sock.settimeout(2.0)
                print("[Bridge] ✓ Connected to Webots controller!")

                buf = ""
                while self._running:
                    try:
                        chunk = sock.recv(1024).decode()
                        if not chunk:
                            break
                        buf += chunk
                        while "\n" in buf:
                            line, buf = buf.split("\n", 1)
                            line = line.strip()
                            if line:
                                data = json.loads(line)
                                self.vehicle.update_from_webots(data)
                    except socket.timeout:
                        pass
                sock.close()
            except (ConnectionRefusedError, OSError):
                print(f"[Bridge] Webots not reachable — retrying in "
                      f"{self.retry_interval}s (using fallback speed)")
                self.vehicle.connected = False
                time.sleep(self.retry_interval)
            except Exception as e:
                print(f"[Bridge] Error: {e} — reconnecting...")
                self.vehicle.connected = False
                time.sleep(self.retry_interval)

    def stop(self):
        self._running = False


# ============================================================
# BUZZER — replaces GPIO buzzer; works on laptop
# ============================================================

class Buzzer:
    """
    Software buzzer.
    - Tries to play a system beep / sound file.
    - Works cross-platform (Linux, macOS, Windows).
    - Designed to signal TEMPORARY sign detection (your brief).
    """

    def __init__(self, cooldown_seconds: float = 5.0):
        self.cooldown = cooldown_seconds
        self._last_buzz = 0.0

    def buzz(self, reason: str = "TEMPORARY SIGN"):
        """Trigger a buzzer alert with cooldown."""
        now = time.time()
        if now - self._last_buzz < self.cooldown:
            return   # still cooling down

        self._last_buzz = now
        self._play_sound(reason)
        self._print_alert(reason)

    def _print_alert(self, reason: str):
        ts = datetime.now().strftime("%H:%M:%S")
        print("\n" + "\033[93m" + "=" * 60)
        print(f"  🔔 BUZZER  [{ts}]")
        print(f"  {reason}")
        print("=" * 60 + "\033[0m\n")

    def _play_sound(self, reason: str):
        """Best-effort audio alert."""
        try:
            if sys.platform == "darwin":          # macOS
                os.system("afplay /System/Library/Sounds/Funk.aiff &")
            elif sys.platform.startswith("linux"):
                # Try paplay, then aplay, then terminal bell
                r = os.system("paplay /usr/share/sounds/freedesktop/stereo/bell.oga "
                               ">/dev/null 2>&1")
                if r != 0:
                    os.system("aplay /usr/share/sounds/alsa/Front_Center.wav "
                              ">/dev/null 2>&1 || echo -e '\\a'")
            elif sys.platform == "win32":
                import winsound
                # 880 Hz for 500ms — like a real buzzer
                winsound.Beep(880, 500)
        except Exception:
            # Last resort: terminal bell
            print("\a", end="", flush=True)


# ============================================================
# ALERT MANAGER (carries over from main_hybrid.py)
# ============================================================

class AlertManager:
    """
    Handles console alerts with colour coding.
    Triggers the Buzzer on TEMPORARY sign events.
    """

    def __init__(self, buzzer: Buzzer,
                 cooldown_seconds: float = 5.0):
        self.buzzer = buzzer
        self.cooldown = cooldown_seconds
        self._last_alert: dict[str, float] = {}
        self.alerts_log = []

    def alert(self, message: str, alert_type: str = "INFO"):
        now = time.time()
        last = self._last_alert.get(alert_type, 0)
        if now - last < self.cooldown:
            return
        self._last_alert[alert_type] = now

        colors = {
            "OVERSPEED": "\033[91m",
            "TEMPORARY": "\033[93m",
            "INFO":      "\033[92m",
            "WARNING":   "\033[95m",
        }
        symbols = {
            "OVERSPEED": "🚨 OVERSPEED!",
            "TEMPORARY": "⚠️  TEMPORARY SIGN",
            "INFO":      "✓  INFO",
            "WARNING":   "⚠️  WARNING",
        }
        color  = colors.get(alert_type, "")
        symbol = symbols.get(alert_type, "")
        reset  = "\033[0m"
        ts     = datetime.now().strftime("%H:%M:%S.%f")[:-3]

        print(f"\n{color}{'='*60}")
        print(f"[{ts}] {symbol}")
        print(message)
        print(f"{'='*60}{reset}\n")

        # ── BUZZER for temporary sign ──────────────────────────
        if alert_type == "TEMPORARY":
            self.buzzer.buzz(f"Temporary limit detected!\n  {message}")

        self.alerts_log.append({
            "timestamp": ts,
            "type":      alert_type,
            "message":   message
        })


# ============================================================
# DATA LOGGER (unchanged from main_hybrid.py)
# ============================================================

class DataLogger:
    def __init__(self, filename: str = "detection_log_webots.csv"):
        self.filename = filename
        self.data = []
        self.start_time = time.time()

    def log(self, snap: dict, detected_speed: Optional[int],
            confirmed_speed: Optional[int], confidence: float,
            is_overspeed: bool, is_temporary: bool):
        self.data.append({
            "timestamp":       round(time.time() - self.start_time, 3),
            "vehicle_speed_mph": snap["speed_mph"],
            "map_speed_mph":     snap["map_speed_mph"],
            "pos_x":             snap["pos_x"],
            "pos_z":             snap["pos_z"],
            "webots_connected":  int(snap["connected"]),
            "detected_speed":    detected_speed or 0,
            "confirmed_speed":   confirmed_speed or 0,
            "confidence":        round(confidence, 3),
            "is_overspeed":      int(is_overspeed),
            "is_temporary":      int(is_temporary),
        })

    def save(self):
        if not self.data:
            print("No data to save.")
            return
        with open(self.filename, "w", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=self.data[0].keys())
            writer.writeheader()
            writer.writerows(self.data)
        print(f"\n📊 Data saved to: {self.filename}  "
              f"({len(self.data)} frames)")


# ============================================================
# MAIN WEBOTS DETECTION SYSTEM
# ============================================================

class WebotsDetectionSystem:
    """
    Webots-integrated version of HybridDetectionSystem.
    Same pipeline; vehicle speed now comes from Webots physics.
    """

    def __init__(self, camera_index: int = 0,
                 show_video: bool = True,
                 fallback_speed_mph: float = 30.0,
                 webots_host: str = "127.0.0.1",
                 webots_port: int = 65432):

        print("\n" + "=" * 60)
        print("SPEED SIGN DETECTION — WEBOTS INTEGRATION")
        print("Real Webcam  +  Webots Vehicle Physics")
        print("=" * 60)

        self.config     = Config()
        self.show_video = show_video

        # [1] Camera
        print(f"\n[1/6] Opening camera {camera_index}...")
        self.camera = cv2.VideoCapture(camera_index)
        if not self.camera.isOpened():
            raise RuntimeError(f"Cannot open camera {camera_index}")
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH,  self.config.frame_width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, self.config.frame_height)
        w = int(self.camera.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(self.camera.get(cv2.CAP_PROP_FRAME_HEIGHT))
        print(f"   Camera ready: {w}x{h}")

        # [2] YOLO detector (UNCHANGED)
        print(f"\n[2/6] Loading YOLO: {self.config.yolo_model_path}")
        self.detector = YoloSpeedDetector(
            model_path    = self.config.yolo_model_path,
            conf_th       = self.config.conf_threshold,
            iou_th        = self.config.iou_threshold,
            min_box_area  = self.config.min_box_area,
            logger        = self._logger()
        )
        print("   YOLO ready")

        # [3] Decision engine (UNCHANGED)
        print("\n[3/6] Decision engine...")
        self.decision = DecisionEngine(
            confirm_frames         = self.config.confirm_frames,
            temporary_gap_mph      = self.config.temporary_gap_mph,
            overspeed_tolerance_mph= self.config.overspeed_tolerance_mph,
            overspeed_hold_seconds = self.config.overspeed_hold_seconds,
            gps_min_moving_mps     = self.config.gps_min_moving_mps,
            logger                 = self._logger()
        )
        print("   Decision engine ready")

        # [4] Webots bridge
        print(f"\n[4/6] Webots bridge → {webots_host}:{webots_port}")
        self.vehicle = WebotsVehicleState(fallback_speed_mph)
        self.bridge  = WebotsBridge(self.vehicle, webots_host, webots_port)
        print("   Bridge thread started (will connect when Webots runs)")

        # [5] Buzzer
        print("\n[5/6] Buzzer...")
        self.buzzer  = Buzzer(cooldown_seconds=self.config.alert_cooldown_seconds)
        self.alerter = AlertManager(self.buzzer,
                                    self.config.alert_cooldown_seconds)
        print("   Buzzer ready")

        # [6] Logger
        print("\n[6/6] Data logger...")
        self.data_logger = DataLogger()
        print("   Logger ready")

        # State
        self.running       = True
        self.frame_count   = 0
        self.last_status_t = 0.0

        # Manual override (press T to toggle)
        self.manual_override        = False
        self.manual_override_speed  = fallback_speed_mph

        print("\n" + "=" * 60)
        print("SYSTEM READY")
        print("Waiting for Webots to start… (running with fallback speed"
              f" {fallback_speed_mph} mph until connected)")
        print("=" * 60)
        self._print_controls()

    # ----------------------------------------------------------
    def _logger(self):
        class L:
            def info(s, m):    print(f"[INFO]  {m}")
            def debug(s, m):   pass
            def warning(s, m): print(f"[WARN]  {m}")
            def error(s, m):   print(f"[ERROR] {m}")
        return L()

    def _print_controls(self):
        print("\nControls (click the OpenCV window first):")
        print("  M       → cycle map speed limit")
        print("  T       → toggle manual speed override (for testing)")
        print("  W / S   → +5 / -5 mph override speed")
        print("  1–9     → set override to 10–90 mph")
        print("  Q       → quit\n")

    # ----------------------------------------------------------
    # MAIN FRAME PIPELINE (same as main_hybrid.py)
    # ----------------------------------------------------------
    def process_frame(self, frame):
        snap = self.vehicle.get_snapshot()

        # Use manual override if active
        if self.manual_override:
            speed_mps = self.manual_override_speed / 2.237
            map_mph   = snap["map_speed_mph"]
        else:
            speed_mps = snap["speed_mps"]
            map_mph   = snap["map_speed_mph"]

        # 1. YOLO on real webcam frame
        detections = self.detector.detect(frame)
        top        = detections[0] if detections else None
        top_speed  = top["speed"] if top else None
        top_conf   = top["conf"]  if top else 0.0

        # 2. Decision engine (UNCHANGED logic)
        event = self.decision.update(top_speed, speed_mps, map_mph)

        confirmed    = None
        is_overspeed = False
        is_temporary = False

        if event:
            confirmed    = event["sign_confirmed_mph"]
            is_temporary = event["is_temporary"]
            is_overspeed = event["is_overspeed"]

            if is_temporary:
                self.alerter.alert(
                    f"Temporary limit: {confirmed} mph\n"
                    f"Map limit: {event['map_mph']} mph  "
                    f"(possible roadworks / school zone)\n"
                    f"Vehicle speed: {snap['speed_mph']:.1f} mph",
                    "TEMPORARY"
                )

            if is_overspeed:
                self.alerter.alert(
                    f"Vehicle: {event['gps_mph']:.1f} mph  |  "
                    f"Limit: {confirmed} mph\n"
                    f"Webots connected: {snap['connected']}\n"
                    f"REDUCE SPEED IMMEDIATELY!",
                    "OVERSPEED"
                )

        # 3. Log
        self.data_logger.log(snap, top_speed, confirmed,
                             top_conf, is_overspeed, is_temporary)

        # 4. Draw overlay
        if self.show_video:
            frame = self._draw_overlay(frame, top, snap, confirmed,
                                       is_overspeed, is_temporary)

        return frame, top_speed, confirmed, top_conf, is_overspeed, is_temporary

    # ----------------------------------------------------------
    def _draw_overlay(self, frame, detection, snap,
                      confirmed, is_overspeed, is_temporary):

        # Detection bounding box
        if detection:
            x1, y1, x2, y2 = detection["xyxy"]
            box_color = (0, 0, 255) if is_overspeed else \
                        (0, 255, 255) if is_temporary else (0, 255, 0)
            cv2.rectangle(frame, (x1, y1), (x2, y2), box_color, 3)
            cv2.putText(frame,
                        f"{detection['speed']} mph ({detection['conf']:.2f})",
                        (x1, y1 - 10), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, box_color, 2)

        h, w = frame.shape[:2]

        # Dark header bar
        cv2.rectangle(frame, (0, 0), (w, 90), (30, 30, 30), -1)

        # Line 1 — vehicle speed
        speed_val  = self.manual_override_speed if self.manual_override \
                     else snap["speed_mph"]
        speed_src  = "MANUAL" if self.manual_override else \
                     ("WEBOTS" if snap["connected"] else "FALLBACK")
        spd_color  = (0, 0, 255) if is_overspeed else (255, 255, 255)
        cv2.putText(frame,
                    f"Vehicle: {speed_val:.0f} mph [{speed_src}]",
                    (10, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.75, spd_color, 2)

        # Line 2 — confirmed limit
        if confirmed:
            lim_color = (0, 255, 255) if is_temporary else (0, 255, 0)
            cv2.putText(frame,
                        f"Limit: {confirmed} mph"
                        + (" [TEMP]" if is_temporary else ""),
                        (10, 58), cv2.FONT_HERSHEY_SIMPLEX, 0.75, lim_color, 2)

        # Map speed (right side)
        cv2.putText(frame,
                    f"Map: {snap['map_speed_mph']:.0f} mph",
                    (w - 210, 28), cv2.FONT_HERSHEY_SIMPLEX, 0.7,
                    (180, 180, 180), 2)

        # Webots connection indicator
        dot_color = (0, 255, 0) if snap["connected"] else (0, 100, 255)
        cv2.circle(frame, (w - 20, 20), 10, dot_color, -1)
        cv2.putText(frame,
                    "WBT" if snap["connected"] else "OFF",
                    (w - 52, 25), cv2.FONT_HERSHEY_SIMPLEX, 0.5,
                    dot_color, 1)

        # Alert banners
        if is_overspeed:
            cv2.rectangle(frame, (0, h - 50), (w, h), (0, 0, 180), -1)
            cv2.putText(frame, "⚠  OVERSPEED  ⚠",
                        (w // 2 - 130, h - 15),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (255, 255, 255), 2)
        elif is_temporary:
            cv2.rectangle(frame, (0, h - 50), (w, h), (0, 140, 200), -1)
            cv2.putText(frame, "🔔  TEMPORARY SIGN — BUZZER ACTIVE  🔔",
                        (10, h - 15), cv2.FONT_HERSHEY_SIMPLEX,
                        0.7, (255, 255, 255), 2)

        # Controls reminder
        cv2.putText(frame, "M=map  T=override  W/S=speed  Q=quit",
                    (10, h - (55 if is_overspeed or is_temporary else 10)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.45, (120, 120, 120), 1)

        return frame

    # ----------------------------------------------------------
    # KEYBOARD HANDLING (OpenCV)
    # ----------------------------------------------------------
    def _handle_key(self, key: int) -> bool:
        """Returns False when quit requested."""
        if key == ord('q'):
            return False
        elif key == ord('m'):
            limits = [20, 30, 40, 50, 60, 70]
            cur = self.vehicle.map_speed_mph
            idx = limits.index(cur) if cur in limits else 0
            self.vehicle.map_speed_mph = limits[(idx + 1) % len(limits)]
            print(f"[Key] Map limit → {self.vehicle.map_speed_mph} mph")
        elif key == ord('t'):
            self.manual_override = not self.manual_override
            state = "ON" if self.manual_override else "OFF"
            print(f"[Key] Manual override {state} "
                  f"({self.manual_override_speed:.0f} mph)")
        elif self.manual_override:
            if key == ord('w'):
                self.manual_override_speed = min(100,
                                                 self.manual_override_speed + 5)
                print(f"[Key] Override speed → {self.manual_override_speed} mph")
            elif key == ord('s'):
                self.manual_override_speed = max(0,
                                                 self.manual_override_speed - 5)
                print(f"[Key] Override speed → {self.manual_override_speed} mph")
            elif key == ord('0'):
                self.manual_override_speed = 0
            elif ord('1') <= key <= ord('9'):
                self.manual_override_speed = (key - ord('0')) * 10
                print(f"[Key] Override speed → {self.manual_override_speed} mph")
        return True

    # ----------------------------------------------------------
    # MAIN LOOP
    # ----------------------------------------------------------
    def run(self):
        print("\nStarting detection loop…")
        print("Hold printed speed signs in front of the webcam!\n")

        try:
            while self.running:
                ret, frame = self.camera.read()
                if not ret:
                    print("[WARNING] Camera read failed — skipping frame")
                    continue

                self.frame_count += 1
                frame, det, conf_spd, conf, is_over, is_temp = \
                    self.process_frame(frame)

                if self.show_video:
                    cv2.imshow("Speed Detection — Webots Integration", frame)
                    key = cv2.waitKey(1) & 0xFF
                    if not self._handle_key(key):
                        break

                # Periodic console status (1 Hz)
                now = time.time()
                if now - self.last_status_t > 1.0:
                    self.last_status_t = now
                    snap = self.vehicle.get_snapshot()
                    wbt  = "✓" if snap["connected"] else "✗"
                    spd  = (self.manual_override_speed if self.manual_override
                            else snap["speed_mph"])
                    src  = "MANUAL" if self.manual_override else f"Webots{wbt}"
                    print(f"[{self.frame_count:>5}] "
                          f"Speed: {spd:.0f} mph [{src}]  |  "
                          f"Detected: {det or '--'}  |  "
                          f"Confirmed: {conf_spd or '--'}  |  "
                          f"Map: {snap['map_speed_mph']:.0f} mph  |  "
                          f"Temp: {is_temp}  Overspeed: {is_over}")

        except KeyboardInterrupt:
            print("\nInterrupted.")
        finally:
            self.cleanup()

    def cleanup(self):
        print("\nShutting down…")
        self.bridge.stop()
        self.data_logger.save()
        self.camera.release()
        cv2.destroyAllWindows()

        print("\n" + "=" * 60)
        print("SESSION SUMMARY")
        print("=" * 60)
        print(f"Frames processed : {self.frame_count}")
        print(f"Alerts triggered : {len(self.alerter.alerts_log)}")
        for a in self.alerter.alerts_log:
            print(f"  [{a['timestamp']}] {a['type']}: "
                  f"{a['message'][:60].strip()}")
        print("=" * 60)


# ============================================================
# ENTRY POINT
# ============================================================

def parse_args():
    p = argparse.ArgumentParser(
        description="Webots-integrated speed sign detection"
    )
    p.add_argument("--camera",         type=int,   default=0,
                   help="Webcam index (0=built-in, 1=external)")
    p.add_argument("--fallback_speed", type=float, default=30.0,
                   help="Speed (mph) used when Webots not yet connected")
    p.add_argument("--webots_host",    type=str,   default="127.0.0.1")
    p.add_argument("--webots_port",    type=int,   default=65432)
    p.add_argument("--no_show",        action="store_true",
                   help="Disable OpenCV video window")
    return p.parse_args()


if __name__ == "__main__":
    args = parse_args()
    system = WebotsDetectionSystem(
        camera_index       = args.camera,
        show_video         = not args.no_show,
        fallback_speed_mph = args.fallback_speed,
        webots_host        = args.webots_host,
        webots_port        = args.webots_port,
    )
    system.run()
