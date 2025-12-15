import argparse
import time
import cv2

from config import Config
from src.utils import setup_logger
from src.camera import Camera
from src.detector import YoloSpeedDetector
from src.gps_reader import GPSReader
from src.map_osm import OSMMaxSpeedClient
from src.decision import DecisionEngine
from src.alert import AlertManager

def parse_args():
    p = argparse.ArgumentParser()
    p.add_argument("--show", action="store_true", help="Show camera window for debugging")
    p.add_argument("--log", default="INFO", help="DEBUG/INFO/WARNING/ERROR")
    p.add_argument("--mock_gps", action="store_true", help="Use fake GPS data")
    p.add_argument("--mock_map", action="store_true", help="Disable Overpass queries")
    return p.parse_args()

def main():
    args = parse_args()
    cfg = Config()

    import logging
    logger = setup_logger(getattr(logging, args.log.upper(), logging.INFO))

    logger.info("Starting speed sign system...")

    cam = None
    gps = None
    osm = None
    alerter = None

    try:
        cam = Camera(cfg.camera_index, cfg.frame_width, cfg.frame_height)
        detector = YoloSpeedDetector(cfg.yolo_model_path, cfg.conf_threshold, cfg.iou_threshold, cfg.min_box_area, logger)

        if not args.mock_gps:
            gps = GPSReader(cfg.gps_port, cfg.gps_baud, cfg.gps_ema_alpha, logger)

        if not args.mock_map:
            osm = OSMMaxSpeedClient(cfg.overpass_url, cfg.map_query_radius_m, cfg.map_cache_seconds, logger)

        decision = DecisionEngine(
            confirm_frames=cfg.confirm_frames,
            temporary_gap_mph=cfg.temporary_gap_mph,
            overspeed_tolerance_mph=cfg.overspeed_tolerance_mph,
            overspeed_hold_seconds=cfg.overspeed_hold_seconds,
            gps_min_moving_mps=cfg.gps_min_moving_mps,
            logger=logger
        )

        alerter = AlertManager(cfg.alert_cooldown_seconds, cfg.enable_buzzer, cfg.buzzer_gpio_pin, logger)

        # mock GPS state
        mock_lat, mock_lon = 53.7457, -0.3367  # Hull-ish
        mock_speed_mps = 6.0  # ~13.4 mph

        last_map_lookup = 0.0
        map_speed_mph = None
        last_print = 0.0

        while True:
            frame = cam.read()
            if frame is None:
                logger.error("Camera read failed.")
                time.sleep(0.1)
                continue

            dets = detector.detect(frame)
            top = dets[0] if dets else None
            top_speed = top["speed"] if top else None
            top_conf = top["conf"] if top else None

            # GPS fix
            if args.mock_gps:
                gps_fix = {"lat": mock_lat, "lon": mock_lon, "speed_mps": mock_speed_mps}
            else:
                gps_fix = gps.read_fix() or gps.last_fix

            # Map lookup throttled
            now = time.time()
            if gps_fix and osm and (now - last_map_lookup) >= cfg.map_cache_seconds:
                last_map_lookup = now
                map_speed_mph = osm.get_maxspeed_mph(gps_fix["lat"], gps_fix["lon"])

            # Decision update
            gps_speed_mps = gps_fix["speed_mps"] if gps_fix else None
            event = decision.update(top_speed, gps_speed_mps, map_speed_mph)

            # Alert conditions
            if event:
                confirmed = event["sign_confirmed_mph"]
                is_temp = event["is_temporary"]
                is_over = event["is_overspeed"]

                if is_temp:
                    # new lower than map → temp event (alert once)
                    alerter.alert(f"Temporary limit detected: {confirmed} mph (map {event['map_mph']} mph)")

                if is_over:
                    alerter.alert(f"Overspeed: {event['gps_mph']:.1f} mph in {confirmed} mph zone")

                # periodic debug print
                if now - last_print > 0.5:
                    last_print = now
                    gps_str = f"{event['gps_mph']:.1f}" if event["gps_mph"] is not None else "None"
                    logger.info(
                        f"det={top_speed} ({top_conf:.2f}) | conf={confirmed} | "
                        f"gps={gps_str} | map={event['map_mph']} | temp={is_temp} | over={is_over}"
                        f"map={event['map_mph']} | temp={is_temp} | over={is_over}"
                    )


            # Draw + show
            if args.show:
                if top:
                    x1, y1, x2, y2 = top["xyxy"]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                    cv2.putText(frame, f"{top_speed} ({top_conf:.2f})", (x1, y1 - 8),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 2)

                cv2.imshow("Speed Sign System", frame)
                if cv2.waitKey(1) & 0xFF == ord('q'):
                    break

    except KeyboardInterrupt:
        logger.info("Stopping...")
    finally:
        if cam:
            cam.release()
        if gps:
            gps.close()
        if alerter:
            alerter.close()
        cv2.destroyAllWindows()

if __name__ == "__main__":
    main()
