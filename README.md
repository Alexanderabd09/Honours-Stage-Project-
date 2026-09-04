# Speed Limit Sign Detection and Driver Alert System

Real-time detection of UK speed limit signs from a camera feed, cross-referenced
against live vehicle speed and OpenStreetMap road data to decide whether a
detected sign represents a **temporary** restriction or a permanent one.

BSc Honours Stage Project — Robotics and Artificial Intelligence, University of
Hull, April 2026.

---

## Why temporary signs

Satellite navigation systems read permanent speed limits from map data. They do
not see the temporary limits posted at roadworks, around school zones, or on
smart motorways — restrictions that carry the same legal weight as any other
limit but are routinely missed.

This system watches for that specific case. When the detected sign is
significantly lower than the limit the map reports for the current road, it
treats the sign as a temporary restriction and issues a distinct alert:

```
detected_sign_mph  <=  map_speed_mph - temporary_gap_mph
```

A 30 mph sign detected on a road the map calls 50 mph produces a 20 mph gap,
which exceeds the 10 mph threshold, and the temporary-sign alert fires.

---

## Results

The detector is a YOLOv8 model trained for 100 epochs on a custom dataset of UK
speed limit signs.

| Metric | Value |
| --- | --- |
| mAP@0.5 | 0.989 |
| Precision | 0.987 |
| Recall | 0.971 |
| Confidence threshold | 0.60 |

System evaluation over 1,182 logged frames:

| Measure | Result |
| --- | --- |
| Frames containing a detected sign | 34.6% |
| Mean confidence on successful detections | 0.917 |
| Overspeed events correctly flagged | 49 |
| Temporary-sign events correctly flagged | 102 |
| Webots bridge connected | 94.2% of frames |

Full methodology, evaluation and discussion are in the
[final report](docs/final-report.pdf).

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
│  Webcam ───────► YoloSpeedDetector  │
│  (real printed signs)     │         │
│                           ▼         │
│                    DecisionEngine   │
│                           │         │
│            ┌──────────────┤         │
│         is_temporary?  is_overspeed?│
│            │               │        │
│         BUZZER          Console     │
│         + console       alert       │
│         alert                       │
└─────────────────────────────────────┘
```

Vehicle speed comes from the Webots simulator over a TCP socket rather than from
physical GPS hardware, which removed the need for a test vehicle during
development. A lane-following PID controller drives the simulated car and
produces physics-based speed readings that feed the detection pipeline directly.

---

## Repository structure

```
.
├── main_webots.py          Entry point — camera loop, alerts, logging
├── detector.py             YoloSpeedDetector: YOLOv8 inference, label parsing
├── decision.py             DecisionEngine: temporary vs. overspeed logic
├── map_osm.py              OpenStreetMap speed limit lookup via Overpass API
├── config.py               All tuneable parameters (dataclass)
├── train_model.py          YOLOv8 training script
│
├── controllers/
│   └── speed_car_controller/
│       └── speed_car_controller.py   Webots car controller and TCP server
│
├── worlds/
│   └── city.wbt            Webots world
│
├── weights/
│   └── best.pt             Trained detector
│
├── assets/
│   └── printable_speed_signs.pdf     Print these to test with a webcam
│
└── docs/
    └── final-report.pdf    Full project report
```

---

## Getting started

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

[Webots](https://cyberbotics.com) must be installed separately — it provides the
`vehicle` and `controller` Python modules used by the car controller.

### 2. Print the test signs

Print `assets/printable_speed_signs.pdf`. These are what you hold up to the
webcam.

### 3. Start the simulation

Open `worlds/city.wbt` in Webots and press **Play**. Webots picks up
`controllers/speed_car_controller/` automatically. The car begins driving and
broadcasts its speed on port 65432 at 10 Hz.

### 4. Start the detection system

In a separate terminal:

```bash
python main_webots.py
```

The two processes run side by side. If Webots is not running, `main_webots.py`
falls back to `--fallback_speed` (default 30 mph) so detection can still be
tested standalone.

---

## Controls

In the OpenCV window:

| Key | Action |
| --- | --- |
| `M` | Cycle map speed limit (20/30/40/50/60/70 mph) |
| `T` | Toggle manual speed override |
| `W` / `S` | ±5 mph (override mode only) |
| `1`–`9` | Set override speed to 10–90 mph |
| `Q` | Quit |

The indicator in the top-right corner shows bridge status — green for connected
to Webots, orange for fallback speed.

In the Webots window: `↑`/`↓` adjust speed, `←`/`→` steer manually, `A`
re-enables auto-drive.

---

## Troubleshooting

**Connection refused on port 65432** — Webots is not running or the simulation is
paused. Press Play.

**Car does not move** — motor device names in `speed_car_controller.py` may not
match your robot model. Open the robot node in Webots and check the device names.

**No detections** — check lighting, move the printed sign closer to fill more of
the frame, or lower `conf_threshold` in `config.py`.

---

## Author

Ojonibe Alexander Abdu — BSc Mechatronics, Robotics and Automation Engineering,
University of Hull.

Supervisor: Baseer Ahmad. Second marker: Peter Robinson.

Licensed under the [MIT Licence](LICENSE).
