import time

class AlertManager:
    def __init__(self, cooldown_seconds: float, enable_buzzer: bool, gpio_pin: int, logger):
        self.cooldown = cooldown_seconds
        self.enable_buzzer = enable_buzzer
        self.gpio_pin = gpio_pin
        self.logger = logger
        self._last_alert_ts = 0.0

        self._gpio = None
        if self.enable_buzzer:
            try:
                import RPi.GPIO as GPIO
                GPIO.setmode(GPIO.BCM)
                GPIO.setup(self.gpio_pin, GPIO.OUT)
                self._gpio = GPIO
            except Exception as e:
                self.logger.error(f"Failed to init GPIO buzzer, disabling: {e}")
                self.enable_buzzer = False

    def close(self):
        if self._gpio:
            try:
                self._gpio.cleanup()
            except Exception:
                pass

    def can_alert(self):
        return (time.time() - self._last_alert_ts) >= self.cooldown

    def alert(self, reason: str):
        if not self.can_alert():
            return False

        self._last_alert_ts = time.time()
        self.logger.warning(f"ALERT: {reason}")

        if self.enable_buzzer and self._gpio:
            # simple beep
            self._gpio.output(self.gpio_pin, 1)
            time.sleep(0.15)
            self._gpio.output(self.gpio_pin, 0)

        return True
