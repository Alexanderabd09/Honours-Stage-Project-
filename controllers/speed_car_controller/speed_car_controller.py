

import socket
import json
import threading
import time
import math

from vehicle import Driver


# TUNEABLE PARAMETERS

HOST = "127.0.0.1"
PORT = 65432

# Initial cruising speed in km/h (~31 mph)
INITIAL_SPEED_KPH = 50.0

# PID gains 
KP = 0.25
KI = 0.006
KD = 2.0

# Yellow line filter window size
FILTER_SIZE = 3

# SICK central detection half-area
SICK_HALF_AREA = 20

# Reference colour for yellow road line in BGR 
YELLOW_REF_B = 95
YELLOW_REF_G = 187
YELLOW_REF_R = 203
YELLOW_TOLERANCE = 30

UNKNOWN = 99999.99   # sentinel, 


# PID CONTROLLER  ( applyPID)


class LaneFollowPID:
    def __init__(self):
        self.old_value  = 0.0
        self.integral   = 0.0
        self.need_reset = False

    def reset(self):
        self.need_reset = True

    def update(self, angle: float) -> float:
        if self.need_reset:
            self.old_value  = angle
            self.integral   = 0.0
            self.need_reset = False

        # Anti-windup: clear integral on sign flip
        if math.copysign(1, angle) != math.copysign(1, self.old_value):
            self.integral = 0.0

        diff = angle - self.old_value

        if -30 < self.integral < 30:
            self.integral += angle

        self.old_value = angle
        return KP * angle + KI * self.integral + KD * diff



# ANGLE FILTER  


class AngleFilter:
    def __init__(self):
        self.values     = [0.0] * FILTER_SIZE
        self.first_call = True

    def update(self, new_value: float) -> float:
        if self.first_call or new_value == UNKNOWN:
            self.first_call = False
            self.values     = [0.0] * FILTER_SIZE
        else:
            self.values = self.values[1:] + [new_value]

        if new_value == UNKNOWN:
            return UNKNOWN

        return sum(self.values) / FILTER_SIZE



# MAIN CONTROLLER


class SpeedCarController:

    def __init__(self):
        self.driver    = Driver()
        self.timestep  = int(self.driver.getBasicTimeStep())

        #  Discover devices 
        self.has_camera  = False
        self.has_gps     = False
        self.has_sick    = False
        self.has_display = False

        for i in range(self.driver.getNumberOfDevices()):
            name = self.driver.getDeviceByIndex(i).getName()
            if   name == "camera":        self.has_camera  = True
            elif name == "gps":           self.has_gps     = True
            elif name == "Sick LMS 291":  self.has_sick    = True
            elif name == "display":       self.has_display = True

        print(f"[Controller] Devices — camera:{self.has_camera}  "
              f"gps:{self.has_gps}  sick:{self.has_sick}  "
              f"display:{self.has_display}")

        #Camera
        self.camera  = None
        self.cam_w   = 0
        self.cam_h   = 0
        self.cam_fov = 0.0
        if self.has_camera:
            self.camera  = self.driver.getDevice("camera")
            self.camera.enable(self.timestep)
            self.cam_w   = self.camera.getWidth()
            self.cam_h   = self.camera.getHeight()
            self.cam_fov = self.camera.getFov()
            print(f"[Controller] Camera {self.cam_w}x{self.cam_h} "
                  f"fov={self.cam_fov:.2f}")

        #SICK LiDAR
        self.sick      = None
        self.sick_w    = 0
        self.sick_fov  = 0.0
        if self.has_sick:
            self.sick     = self.driver.getDevice("Sick LMS 291")
            self.sick.enable(self.timestep)
            self.sick_w   = self.sick.getHorizontalResolution()
            self.sick_fov = self.sick.getFov()
            print(f"[Controller] SICK {self.sick_w}px fov={self.sick_fov:.2f}")

        #GPS
        self.gps           = None
        self.gps_coords    = [0.0, 0.0, 0.0]
        self.gps_speed_kph = 0.0
        if self.has_gps:
            self.gps = self.driver.getDevice("gps")
            self.gps.enable(self.timestep)
            print("[Controller] GPS enabled")

        #  Keyboard 
        self.keyboard = self.driver.getKeyboard()
        self.keyboard.enable(self.timestep)

        # Driving state 
        self.autodrive      = self.has_camera
        self.speed_kph      = 0.0
        self.steering_angle = 0.0
        self.manual_steer   = 0   # integer steps, 

        self.pid    = LaneFollowPID()
        self.filter = AngleFilter()

        # Start car
        if self.has_camera:
            self._set_speed(INITIAL_SPEED_KPH)

        self.driver.setHazardFlashers(True)
        self.driver.setDippedBeams(True)
        self.driver.setAntifogLights(True)
        self.driver.setWiperMode(Driver.SLOW)

        # Socket server 
        self.clients      = []
        self.clients_lock = threading.Lock()
        self._start_socket_server()

        print(f"[Controller] Socket broadcasting on {HOST}:{PORT}")
        print("[Controller] Webots keys: ↑↓=speed  ←→=steer  A=autodrive")
        if self.autodrive:
            print("[Controller] Auto-drive ON")
        else:
            print("[Controller] Manual mode (no camera found)")

   
    # SPEED & STEERING  (set_speed / set_steering_angle)
    

    def _set_speed(self, kph: float):
        kph = min(kph, 250.0)
        self.speed_kph = kph
        self.driver.setCruisingSpeed(kph)
        print(f"[Controller] Speed → {kph:.0f} km/h ({kph/1.609:.0f} mph)")

    def _set_steering_angle(self, angle: float):
        # Rate-limit: max 0.1 rad change per step 
        delta = angle - self.steering_angle
        if delta >  0.1: angle = self.steering_angle + 0.1
        if delta < -0.1: angle = self.steering_angle - 0.1
        self.steering_angle = angle
        self.driver.setSteeringAngle(max(-0.5, min(0.5, angle)))

    
    # KEYBOARD  ( check_keyboard)
  

    def _handle_keyboard(self):
        key = self.keyboard.getKey()
        if key == -1:
            return
        if key == self.keyboard.UP:
            self._set_speed(self.speed_kph + 5.0)
        elif key == self.keyboard.DOWN:
            self._set_speed(max(0.0, self.speed_kph - 5.0))
        elif key == self.keyboard.RIGHT:
            self._change_manual_steer(+1)
        elif key == self.keyboard.LEFT:
            self._change_manual_steer(-1)
        elif key == ord('A'):
            if self.has_camera:
                self.autodrive = True
                print("[Controller] Auto-drive ON")
            else:
                print("[Controller] Cannot enable auto-drive — no camera")

    def _change_manual_steer(self, inc: int):
        self.autodrive = False
        new_steer = self.manual_steer + inc
        if -25 <= new_steer <= 25:
            self.manual_steer = new_steer
            self._set_steering_angle(self.manual_steer * 0.02)

    
    # CAMERA — yellow line angle  (process_camera_image)
   

    def _process_camera(self) -> float:
        image = self.camera.getImage()
        if not image:
            return UNKNOWN

        num_pixels = self.cam_w * self.cam_h
        sumx  = 0
        count = 0

        # Webots camera image is BGRA, 4 bytes per pixel
        for px in range(num_pixels):
            base = px * 4
            b = image[base]
            g = image[base + 1]
            r = image[base + 2]
            diff = abs(b - YELLOW_REF_B) + abs(g - YELLOW_REF_G) + abs(r - YELLOW_REF_R)
            if diff < YELLOW_TOLERANCE:
                sumx  += px % self.cam_w
                count += 1

        if count == 0:
            return UNKNOWN

        return ((sumx / count / self.cam_w) - 0.5) * self.cam_fov

   
    # SICK — obstacle angle & distance 
   

    def _process_sick(self):
        data = self.sick.getRangeImage()
        if not data:
            return UNKNOWN, 0.0

        mid   = self.sick_w // 2
        sumx  = 0
        count = 0
        total = 0.0

        for x in range(mid - SICK_HALF_AREA, mid + SICK_HALF_AREA):
            r = data[x]
            if r < 20.0:
                sumx  += x
                count += 1
                total += r

        if count == 0:
            return UNKNOWN, 0.0

        dist  = total / count
        angle = ((sumx / count / self.sick_w) - 0.5) * self.sick_fov
        return angle, dist

   
    # GPS  ( compute_gps_speed)
   

    def _update_gps(self):
        self.gps_coords    = list(self.gps.getValues())
        self.gps_speed_kph = self.gps.getSpeed() * 3.6   # m/s → km/h

   
    # AUTO-DRIVE DECISION  ( main loop obstacle/line logic)
   

    def _run_autodrive(self, yellow_angle: float,
                       obs_angle: float, obs_dist: float):

        if self.has_sick and obs_angle != UNKNOWN:
            # Obstacle present, compute avoidance steer 
            self.driver.setBrakeIntensity(0.0)
            avoid_steer = self.steering_angle

            if 0.0 < obs_angle < 0.4:
                avoid_steer = self.steering_angle + (obs_angle - 0.25) / obs_dist
            elif obs_angle > -0.4:
                avoid_steer = self.steering_angle + (obs_angle + 0.25) / obs_dist

            steer = avoid_steer
            if yellow_angle != UNKNOWN:
                line_steer = self.pid.update(yellow_angle)
                # Take the more extreme steer (most cautious)
                if avoid_steer > 0 and line_steer > 0:
                    steer = max(avoid_steer, line_steer)
                elif avoid_steer < 0 and line_steer < 0:
                    steer = min(avoid_steer, line_steer)
            else:
                self.pid.reset()

            self._set_steering_angle(steer)

        elif yellow_angle != UNKNOWN:
            #  No obstacle? follow yellow line 
            self.driver.setBrakeIntensity(0.0)
            self._set_steering_angle(self.pid.update(yellow_angle))

        else:
            #  Lost line? brake and wait 
            self.driver.setBrakeIntensity(0.4)
            self.pid.reset()

   
    # TCP SOCKET SERVER
   

    def _start_socket_server(self):
        def serve():
            srv = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((HOST, PORT))
            srv.listen(5)
            srv.settimeout(1.0)
            print(f"[Socket] Listening on {HOST}:{PORT}")
            while True:
                try:
                    conn, addr = srv.accept()
                    with self.clients_lock:
                        self.clients.append(conn)
                    print(f"[Socket] Client connected: {addr}")
                except socket.timeout:
                    pass
                except Exception as e:
                    print(f"[Socket] Error: {e}")
                    break

        threading.Thread(target=serve, daemon=True).start()

    def _broadcast(self):
        speed_mps = self.gps_speed_kph / 3.6
        x = self.gps_coords[0] if self.gps_coords else 0.0
        z = self.gps_coords[2] if len(self.gps_coords) > 2 else 0.0

        payload = json.dumps({
            "speed_mps": round(speed_mps, 3),
            "speed_mph": round(speed_mps * 2.237, 1),
            "speed_kph": round(self.gps_speed_kph, 1),
            "pos_x":     round(x, 2),
            "pos_z":     round(z, 2),
            "ts":        time.time()
        }) + "\n"

        dead = []
        with self.clients_lock:
            for conn in self.clients:
                try:
                    conn.sendall(payload.encode())
                except Exception:
                    dead.append(conn)
            for d in dead:
                self.clients.remove(d)

   
    # MAIN LOOP
   

    def run(self):
        # Run sensors every 50 ms
        SENSOR_EVERY_N    = max(1, int(50 / self.timestep))
        BROADCAST_INTERVAL = 0.1   # 10 Hz
        broadcast_timer   = 0.0
        step_count        = 0

        while self.driver.step() != -1:

            # Keyboard every step
            self._handle_keyboard()

            # Sensors every 50 ms
            if step_count % SENSOR_EVERY_N == 0:

                yellow_angle = UNKNOWN
                obs_angle    = UNKNOWN
                obs_dist     = 0.0

                if self.has_camera:
                    yellow_angle = self.filter.update(self._process_camera())

                if self.has_sick:
                    obs_angle, obs_dist = self._process_sick()

                if self.autodrive and self.has_camera:
                    self._run_autodrive(yellow_angle, obs_angle, obs_dist)

                if self.has_gps:
                    self._update_gps()

            # Broadcast speed at 10 Hz
            broadcast_timer += self.timestep / 1000.0
            if broadcast_timer >= BROADCAST_INTERVAL:
                broadcast_timer = 0.0
                self._broadcast()

            step_count += 1


#  Entry point 
controller = SpeedCarController()
controller.run()