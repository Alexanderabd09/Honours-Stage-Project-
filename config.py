from dataclasses import dataclass

@dataclass
class Config:
    # Camera
    camera_index: int = 0
    frame_width: int = 640
    frame_height: int = 480

    # YOLO
    yolo_model_path: str = "weights/best.pt"
    conf_threshold: float = 0.60
    iou_threshold: float = 0.45
    min_box_area: int = 24 * 24  # ignore tiny boxes

    # Detection stability
    confirm_frames: int = 3  # N consecutive frames required to stabilise detection decision

    # GPS
    gps_port: str = "/dev/serial0"
    gps_baud: int = 9600
    gps_ema_alpha: float = 0.25   # speed smoothing (0..1)
    gps_min_moving_mps: float = 0.5  # ignore near-stationary noise

    # --- Map (Overpass / OSM)
    overpass_url: str = "https://overpass-api.de/api/interpreter"
    map_query_radius_m: int = 50
    map_cache_seconds: int = 60  # avoid hammering API

    #  Units
    use_mph: bool = True # England uses mph so we match it

    #  Alert logic
    overspeed_tolerance_mph: float = 2.0
    overspeed_hold_seconds: float = 1.0
    alert_cooldown_seconds: float = 5.0
    temporary_gap_mph: float = 10.0  # detected <= map - 10 -> "temporary"

    #  Buzzer
    enable_buzzer: bool = False
    buzzer_gpio_pin: int = 18  # example
