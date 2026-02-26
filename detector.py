from ultralytics import YOLO

class YoloSpeedDetector:
    def __init__(self, model_path: str, conf_th: float, iou_th: float, min_box_area: int, logger):
        self.model = YOLO(model_path)
        self.conf_th = conf_th
        self.iou_th = iou_th
        self.min_box_area = min_box_area
        self.logger = logger

        # model.names is dict: {id: "label"}
        self.names = self.model.names

    def _label_to_speed(self, label: str):
        # Accept "20" or "speed_20"
        digits = "".join([c for c in label if c.isdigit()])
        if digits == "":
            return None
        try:
            return int(digits)
        except ValueError:
            return None

    def detect(self, frame):
        """
        Returns list of detections:
          [{'speed': int, 'conf': float, 'xyxy': (x1,y1,x2,y2)}]
        """
        results = self.model.predict(
            source=frame,
            conf=self.conf_th,
            iou=self.iou_th,
            verbose=False
        )

        dets = []
        r = results[0]
        if r.boxes is None:
            return dets

        for b in r.boxes:
            conf = float(b.conf[0])
            cls_id = int(b.cls[0])
            label = self.names.get(cls_id, str(cls_id))
            speed = self._label_to_speed(label)
            if speed is None:
                continue

            x1, y1, x2, y2 = [int(v) for v in b.xyxy[0].tolist()]
            area = max(0, x2 - x1) * max(0, y2 - y1)
            if area < self.min_box_area:
                continue

            dets.append({"speed": speed, "conf": conf, "xyxy": (x1, y1, x2, y2)})

        # sort by confidence descending
        dets.sort(key=lambda d: d["conf"], reverse=True)
        return dets
