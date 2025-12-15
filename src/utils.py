import time
import logging

def setup_logger(level=logging.INFO) -> logging.Logger:
    logger = logging.getLogger("speed_sign_system")
    logger.setLevel(level)
    if not logger.handlers:
        ch = logging.StreamHandler()
        fmt = logging.Formatter("[%(asctime)s] %(levelname)s - %(message)s")
        ch.setFormatter(fmt)
        logger.addHandler(ch)
    return logger

class TTLCache:
    def __init__(self, ttl_seconds: int):
        self.ttl = ttl_seconds
        self._store = {}

    def get(self, key):
        item = self._store.get(key)
        if not item:
            return None
        value, ts = item
        if time.time() - ts > self.ttl:
            self._store.pop(key, None)
            return None
        return value

    def set(self, key, value):
        self._store[key] = (value, time.time())

def clamp(x, lo, hi):
    return max(lo, min(hi, x))
