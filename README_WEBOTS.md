# Speed Sign Detection — Webots Integration
## Project BA-25-1057 | University of Hull
### Student: Ojonibe Alexander Abdu | Supervisor: Baseer Ahmad

---

## What Changed vs the Hybrid System

| Component | Hybrid (original) | Webots (new) |
|-----------|------------------|--------------|
| Vehicle speed | Keyboard W/S | **Webots physics engine** |
| Position | Simulated arithmetic | **Webots GPS sensor** |
| Speed controller | Keyboard | **Webots motor cruise control** |
| Temporary sign buzzer | Console only | **Audible buzzer + console** |
| `detector.py` | ✅ Unchanged | ✅ Unchanged |
| `decision.py` | ✅ Unchanged | ✅ Unchanged |
| `config.py` | ✅ Unchanged | ✅ Unchanged |

---

## Architecture

```
┌─────────────────────────────────────┐
│            WEBOTS SIMULATION        │
│                                     │
│   Road World  ──►  Model Car        │
│                      │              │
│                   Webots GPS        │
│                   (real m/s)        │
│                      │              │
│         speed_car_controller.py     │
│                      │              │
└──────────────────────│──────────────┘
                        │
              TCP socket :65432
              JSON: {speed_mps, pos_x, pos_z}
                        │
┌──────────────────────▼──────────────┐
│            main_webots.py           │
│                                     │
│  WebotsBridge ──► WebotsVehicleState│
│  (receives speed in background)     │
│                                     │
│  Your Webcam ──► YoloSpeedDetector  │
│  (real printed signs)     │         │
│                           ▼         │
│                    DecisionEngine   │
│                    (UNCHANGED)      │
│                           │         │
│            ┌──────────────┤         │
│         is_temporary?  is_overspeed?│
│            │               │        │
│         BUZZER!         Console     │
│         + Console       alert       │
│         alert                       │
└─────────────────────────────────────┘
```

---

## Quick Start

### Step 1 — Install dependencies
```bash
pip install opencv-python ultralytics numpy
```

### Step 2 — Add your trained model
```bash
cp path/to/best.pt weights/best.pt
```

### Step 3 — Set up Webots

1. Download Webots from https://cyberbotics.com if not installed
2. Open Webots → **File → Open World**
3. Navigate to `worlds/speed_detection_world.wbt`
4. Webots will automatically find the `controllers/speed_car_controller/` folder

### Step 4 — Run Webots
Click the **Play ▶** button in Webots.
The car will begin driving and broadcast its speed on port 65432.

### Step 5 — Run the detection system (in a separate terminal)
```bash
python main_webots.py
```

Both processes run at the same time. `main_webots.py` will automatically
connect to Webots as soon as it starts.

---

## How the Speed Connection Works

1. When Webots starts, `speed_car_controller.py` opens a TCP server on `127.0.0.1:65432`
2. Every 100ms, it sends a JSON packet: `{"speed_mps": 13.4, "speed_mph": 30.0, "pos_x": 5.2, "pos_z": -3.1}`
3. `main_webots.py` has a background thread (`WebotsBridge`) that connects and reads these packets
4. The vehicle state is updated in real-time so the decision engine always has the true Webots speed

If Webots is not running, `main_webots.py` falls back to the `--fallback_speed` value (default 30 mph) so you can still test detection.

---

## Buzzer Logic

The buzzer fires when `DecisionEngine` returns `is_temporary = True`.

This happens when (from your unchanged `decision.py`):
```
detected_sign_mph  <=  map_speed_mph - temporary_gap_mph
```
e.g. Map is 50 mph, detected sign is 30 mph → gap = 20 → **TEMPORARY** → **BUZZER**

The buzzer:
- Prints a coloured alert to the console
- Plays an audible system sound (Linux/macOS/Windows)
- Has a 5-second cooldown to avoid spamming (configurable in `config.py`)

---

## Controls (in OpenCV window)

| Key | Action |
|-----|--------|
| M | Cycle map speed limit (20/30/40/50/60/70 mph) |
| T | Toggle manual speed override (for testing without Webots) |
| W / S | ±5 mph (only when override active) |
| 1–9 | Set override speed to 10–90 mph |
| Q | Quit |

The green/orange dot in the top-right corner of the video window shows whether
Webots is connected (green = connected, orange = using fallback).

---

## Adjusting the Car's Speed in Webots

Option A — Edit the default in the controller:
```python
# speed_car_controller.py, line ~30
CRUISE_SPEED_MPS = 13.4   # 30 mph  →  change this
```

Option B — Press W/S in the Webots 3D window while it's running
(keyboard must focus the Webots window, not the OpenCV window).

---

## Testing Scenarios

### Temporary Sign Test (main use case)
1. Set map limit to 50 mph → press `M` until "Map: 50 mph"
2. Hold a **30 mph** printed sign in front of your webcam
3. Wait 3 frames for confirmation
4. **Buzzer fires** — gap = 20 mph > `temporary_gap_mph` (10 mph)

### Overspeed Test
1. Press `T` to enable manual override
2. Press `4` to set speed to 40 mph
3. Hold a **30 mph** sign in front of the camera
4. Overspeed alert fires after 1 second

### Webots Speed Test
1. Change `CRUISE_SPEED_MPS = 17.9` in the controller (40 mph)
2. Restart Webots
3. Hold a **30 mph** sign → overspeed alert fires

---

## File Structure

```
webots_speed_detection/
│
├── main_webots.py                    ← NEW: main entry point
│
├── controllers/
│   └── speed_car_controller/
│       └── speed_car_controller.py  ← NEW: Webots car controller
│
├── worlds/
│   └── speed_detection_world.wbt    ← NEW: Webots world file
│
│   ── UNCHANGED from hybrid system ──
├── detector.py
├── decision.py
├── config.py
├── create_signs.py
├── printable_speed_signs.pdf
└── weights/
    └── best.pt   ← you add this
```

---

## Troubleshooting

**"Connection refused on port 65432"**
→ Webots is not running yet, or the simulation is paused. Press ▶ in Webots.

**Car doesn't move in Webots**
→ Motor names in `speed_car_controller.py` may not match your robot model.
  Open the robot node in Webots, check motor device names, and update the
  `motor_names` list in the controller.

**BmwX5 proto not found**
→ Replace the `BmwX5` block in the `.wbt` file with a `Robot` node and add
  `RotationalMotor` devices manually. Or use a TwoWheelRobot / Pioneer3at.

**No detections**
→ Same as hybrid system: check lighting, move sign closer, lower
  `conf_threshold` in `config.py`.
