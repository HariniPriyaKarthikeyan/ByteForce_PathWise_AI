import collections
import heapq
import io
import itertools
import json
import math
import os
import queue
import shutil
import subprocess
import sys
import threading
import time
from urllib.parse import urlparse
import cv2
import numpy as np
import requests
import streamlit as st

st.set_page_config(page_title="SmartTrolley AI", page_icon="🛒", layout="wide")

CALIBRATION_FILE = "calibration.json"
SETTINGS_FILE = "settings.json"
DETECT_W = 900            # QR detection runs on frames at most this wide

try:                      # optional extra decoder
    from pyzbar import pyzbar as _pyzbar
except Exception:         # pragma: no cover
    _pyzbar = None


NODES = {
    "ENTRANCE": (0, 0),
    "JUNCTION": (0, 2),
    "MILK": (-2, 2),
    "BREAD": (0, 4),
    "RICE": (2, 2),
}
EDGES = [
    ("ENTRANCE", "JUNCTION"),
    ("JUNCTION", "MILK"),
    ("JUNCTION", "BREAD"),
    ("JUNCTION", "RICE"),
]
PRODUCTS = ["MILK", "BREAD", "RICE"]

GRAPH = {n: {} for n in NODES}
for _a, _b in EDGES:
    _d = math.dist(NODES[_a], NODES[_b])
    GRAPH[_a][_b] = _d
    GRAPH[_b][_a] = _d


def dijkstra(start, goal):
    dist = {n: float("inf") for n in NODES}
    prev = {}
    dist[start] = 0
    pq = [(0, start)]
    while pq:
        d, cur = heapq.heappop(pq)
        if d > dist[cur]:
            continue
        if cur == goal:
            break
        for nb, w in GRAPH[cur].items():
            nd = d + w
            if nd < dist[nb]:
                dist[nb] = nd
                prev[nb] = cur
                heapq.heappush(pq, (nd, nb))
    if dist[goal] == float("inf"):
        raise ValueError("No route found")
    path, node = [], goal
    while node != start:
        path.append(node)
        node = prev[node]
    path.append(start)
    return path[::-1], dist[goal]


def heading_of(a, b):
    """0 = North, 1 = East, 2 = South, 3 = West"""
    dx = NODES[b][0] - NODES[a][0]
    dy = NODES[b][1] - NODES[a][1]
    if abs(dy) >= abs(dx):
        return 0 if dy > 0 else 2
    return 1 if dx > 0 else 3


def make_detectors():
    dets = []
    if hasattr(cv2, "QRCodeDetectorAruco"):
        try:
            dets.append(("aruco", cv2.QRCodeDetectorAruco()))
        except Exception:
            pass
    dets.append(("classic", cv2.QRCodeDetector()))
    return dets


def _poly_width(p):
    return sum(math.dist(p[i], p[(i + 1) % 4]) for i in range(4)) / 4.0


def _try_detector(det, img):
    try:
        text, pts, _ = det.detectAndDecode(img)
    except cv2.error:
        return "", None
    if pts is None:
        return "", None
    p = np.asarray(pts, dtype=np.float32).reshape(-1, 2)
    if len(p) < 4:
        return "", None
    return (text or "").strip(), p[:4]


def detect_qr(frame, detectors):
    
    h, w = frame.shape[:2]
    scale = DETECT_W / float(w) if w > DETECT_W else 1.0
    base = (cv2.resize(frame, None, fx=scale, fy=scale,
                       interpolation=cv2.INTER_AREA) if scale != 1.0 else frame)
    gray = cv2.cvtColor(base, cv2.COLOR_BGR2GRAY) if base.ndim == 3 else base

    def finish(text, p, s):
        p = np.asarray(p, dtype=np.float32) / (s * scale)
        return text.upper(), _poly_width(p), p

    if _pyzbar is not None:
        try:
            for obj in _pyzbar.decode(gray):
                text = obj.data.decode("utf-8", "ignore").strip()
                pts = np.array([[q.x, q.y] for q in obj.polygon], np.float32)
                if len(pts) != 4:
                    pts = cv2.boxPoints(cv2.minAreaRect(pts))
                if text:
                    return finish(text, pts, 1.0)
        except Exception:
            pass

    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8)).apply(gray)
    big = cv2.resize(gray, None, fx=1.6, fy=1.6, interpolation=cv2.INTER_CUBIC)
    variants = [(gray, 1.0), (clahe, 1.0), (big, 1.6)]

    fallback = None
    for img, s in variants:
        for _, det in detectors:
            text, p = _try_detector(det, img)
            if p is None:
                continue
            if text:
                return finish(text, p, s)
            if fallback is None:
                fallback = (p, s)
    if fallback is not None:
        return finish("", fallback[0], fallback[1])
    return "", None, None



class Speaker:
    

    def __init__(self, log):
        self.log = log
        self.q = queue.PriorityQueue()
        self.counter = itertools.count()
        self.enabled = True
        self.rate = 155
        self.voice = "en"
        self.current = ""
        self.last_text = ""
        self.last_time = 0.0
        self._pending = set()
        self.backend, self.cli = self._detect_backend()
        self.log(f"Speech backend: {self.backend}")
        threading.Thread(target=self._worker, daemon=True).start()

    @staticmethod
    def _detect_backend():
        for exe in ("espeak-ng", "espeak", "spd-say"):
            path = shutil.which(exe)
            if path:
                return "cli", path
        if sys.platform == "darwin" and shutil.which("say"):
            return "say", shutil.which("say")
        if os.name == "nt" and shutil.which("powershell"):
            return "sapi", shutil.which("powershell")
        try:
            import pyttsx3  # noqa: F401
            return "pyttsx3", None
        except Exception:
            return "none", None

    def say(self, text, urgent=False):
        text = (text or "").strip()
        if not text:
            return
        self.log(f"🔊 {text}")
        if not self.enabled:
            return
        now = time.time()
        if text == self.last_text and now - self.last_time < 1.5:
            return
        if text in self._pending:
            return
        if not urgent and self.q.qsize() >= 4:
            return
        self._pending.add(text)
        self.q.put((0 if urgent else 1, next(self.counter), text))

    def _worker(self):
        engine = None
        if self.backend == "pyttsx3":
            try:
                import pyttsx3
                engine = pyttsx3.init()
                engine.setProperty("rate", self.rate)
            except Exception as e:  # pragma: no cover
                self.log(f"pyttsx3 init failed ({e}); log only")
                self.backend = "none"

        while True:
            _, _, text = self.q.get()
            self._pending.discard(text)
            if not self.enabled:
                continue
            self.current = text
            self.last_text, self.last_time = text, time.time()
            try:
                if self.backend == "cli":
                    if self.cli.endswith("spd-say"):
                        cmd = [self.cli, "-w", "-r", "0", text]
                    else:
                        cmd = [self.cli, "-s", str(self.rate), "-v", self.voice, text]
                    subprocess.run(cmd, timeout=25, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif self.backend == "say":
                    subprocess.run([self.cli, "-r", str(self.rate), text],
                                   timeout=25, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif self.backend == "sapi":
                    safe = text.replace("'", "''")
                    ps = ("Add-Type -AssemblyName System.Speech;"
                          "$s=New-Object System.Speech.Synthesis.SpeechSynthesizer;"
                          "$s.Rate=1;"
                          f"$s.Speak('{safe}');")
                    subprocess.run([self.cli, "-NoProfile", "-Command", ps],
                                   timeout=25, check=False,
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                elif self.backend == "pyttsx3" and engine is not None:
                    engine.say(text)
                    engine.runAndWait()
            except Exception as e:
                self.log(f"Speech error: {type(e).__name__}: {e}")


DEFAULTS = dict(
    cam_url="http://192.168.4.2:8080/video",
    ip="192.168.4.1",
    dry_run=True,
    qr_cm=10.0,
    cal_cm=50.0,
    step_cm=65.0,
    arrive_cm=35.0,
    pulse_on=0.35,
    pulse_off=0.30,
    turn90=0.6,
    max_travel=40.0,
    speak=True,
    drive_mode="pulse",          # "pulse" (slow, scans while stopped) | "continuous"
    endpoint_style="path",       # "path" | "query" | "cmd"
    sim_mode=False,
    cue_far_every=6.0,
)
NOT_SAVED = ("dry_run", "sim_mode")     # always start safe


class Trolley:
    DISPLAY_W = 640

    def __init__(self):
        self.cfg = dict(DEFAULTS)
        self._load_settings()
        self.cfg["dry_run"] = True
        self.cfg["sim_mode"] = False

        self.focal = None
        self.cal_frame_w = None
        self.dist_is_estimate = True
        self._load_cal()

        
        self.frame_jpeg = None
        self.frame_w = None
        self.frame_time = 0.0
        self.cam_status = "Not connected"
        self.cam_mode = "-"
        self.cam_token = None
        self._raw = None
        self._raw_id = 0
        self._raw_lock = threading.Lock()
        self._frame_times = collections.deque(maxlen=20)
        self.fps = 0.0
        self._sim_prev = False
        self._sim_fake = 400.0

        
        self.det = None                       
        self._wpx_hist = collections.deque(maxlen=9)
        self._last_code = ""
        self._last_code_t = 0.0
        self._log_times = {}
        self.engine_names = ""
        self.state = "Idle"
        self.running = False
        self.current = "ENTRANCE"
        self.heading = 0
        self.stop_flag = threading.Event()
        self.logs = collections.deque(maxlen=120)
        self.session = requests.Session()
        self.last_instruction = ""
        self.sim_target = None

        self.motor_ok = 0
        self.motor_fail = 0
        self.last_motor_error = ""

        self.speaker = Speaker(self.log)
        self._last_far_cue = 0.0

    def log(self, msg):
        self.logs.appendleft(f"{time.strftime('%H:%M:%S')}  {msg}")

    def _log_throttled(self, key, msg, every=5.0):
        now = time.time()
        if now - self._log_times.get(key, 0.0) >= every:
            self._log_times[key] = now
            self.log(msg)

    def say(self, text, urgent=False):
        self.last_instruction = text
        self.speaker.say(text, urgent=urgent)

    def _load_settings(self):
        if not os.path.exists(SETTINGS_FILE):
            return
        try:
            with open(SETTINGS_FILE) as f:
                saved = json.load(f)
            for k, v in saved.items():
                if k in self.cfg and k not in NOT_SAVED:
                    self.cfg[k] = v
        except Exception:
            pass

    def save_settings(self):
        try:
            with open(SETTINGS_FILE, "w") as f:
                json.dump({k: v for k, v in self.cfg.items() if k not in NOT_SAVED},
                          f, indent=2)
        except Exception:
            pass

    def _load_cal(self):
        if os.path.exists(CALIBRATION_FILE):
            try:
                with open(CALIBRATION_FILE) as f:
                    data = json.load(f)
                self.focal = data.get("focal_length")
                self.cal_frame_w = data.get("frame_w")
            except Exception:
                self.focal = None

    def _recent_width(self, window=2.0):
        now = time.time()
        recent = [w for t, w in list(self._wpx_hist) if now - t < window]
        if not recent:
            return None
        return sorted(recent)[len(recent) // 2]

    def calibrate(self):
        wpx = self._recent_width(2.0)
        if wpx is None:
            return False
        self.focal = wpx * self.cfg["cal_cm"] / self.cfg["qr_cm"]
        self.cal_frame_w = self.frame_w
        try:
            with open(CALIBRATION_FILE, "w") as f:
                json.dump({"focal_length": self.focal, "frame_w": self.cal_frame_w,
                           "ref_width_px": wpx, "cal_cm": self.cfg["cal_cm"],
                           "qr_cm": self.cfg["qr_cm"]}, f, indent=2)
        except Exception:
            pass
        self.log(f"Calibrated: focal={self.focal:.0f}px (QR was {wpx:.0f}px wide)")
        self.say("Distance calibration saved.")
        return True

    def steps(self, cm):
        return max(1, int(round(cm / self.cfg["step_cm"])))

    def _effective_focal(self):
        if self.focal:
            self.dist_is_estimate = False
            f = self.focal
            if self.cal_frame_w and self.frame_w and self.cal_frame_w != self.frame_w:
                f = f * self.frame_w / self.cal_frame_w
            return f
        self.dist_is_estimate = True
        return (self.frame_w or 640) * 0.85

    def _distance(self, wpx):
        if not wpx:
            return None
        return self.cfg["qr_cm"] * self._effective_focal() / wpx

    def fresh_qr(self, max_age=0.8):
        """(code, distance_cm) of the most recent detection if it is recent."""
        d = self.det
        if d and time.time() - d["t"] <= max_age:
            return d["code"], self._distance(d["wpx"])
        return "", None

    def start_camera(self):
        token = object()
        self.cam_token = token
        self.det = None
        self._wpx_hist.clear()
        if self.cfg["sim_mode"]:
            threading.Thread(target=self._sim_loop, args=(token,), daemon=True).start()
        else:
            threading.Thread(target=self._cam_loop, args=(token,), daemon=True).start()
            threading.Thread(target=self._detect_loop, args=(token,), daemon=True).start()

    @staticmethod
    def _split_url(url):
        url = (url or "").strip()
        if not url:
            return None, None
        if "://" not in url:
            url = "http://" + url
        p = urlparse(url)
        if not p.netloc:
            return None, None
        base = f"{p.scheme}://{p.netloc}"
        path = p.path if p.path not in ("", "/") else "/video"
        q = f"?{p.query}" if p.query else ""
        return base, base + path + q

    @staticmethod
    def _phone_reachable(base):
        try:
            requests.get(base + "/", timeout=3)
            return True, ""
        except requests.RequestException as e:
            return False, type(e).__name__

    def _cam_loop(self, token):
        use_snapshot = False
        while self.cam_token is token:
            base, stream_url = self._split_url(self.cfg["cam_url"])
            if not base:
                self.cam_status = "No camera URL set"
                time.sleep(1.0)
                continue

            self.cam_status = "Connecting..."
            ok, why = self._phone_reachable(base)
            if not ok:
                self.cam_status = "Phone not reachable"
                self._log_throttled(
                    "unreach",
                    f"Cannot reach phone at {base} ({why}). Is the laptop on the "
                    f"SmartTrolley Wi-Fi? Is IP Webcam running ('Start server')? "
                    f"Does the IP match the one shown in the app?", every=8.0)
                time.sleep(2.0)
                continue

            if not use_snapshot:
                result = self._run_stream(token, stream_url)
                if self.cam_token is not token:
                    return
                if result == "nofirst":
                    use_snapshot = True
                    self.log("Video stream would not open - switching to snapshot "
                             "mode (/shot.jpg).")
                else:
                    self.log("Video stream lost - reconnecting...")
                    time.sleep(0.5)
            else:
                self._run_snapshots(token, base)
                if self.cam_token is not token:
                    return
                self.log("Snapshot mode failed - retrying the live stream.")
                use_snapshot = False
                time.sleep(1.0)

    def _run_stream(self, token, url):
        self.cam_status = "Opening video stream..."
        cap = None
        try:
            try:
                cap = cv2.VideoCapture(
                    url, cv2.CAP_FFMPEG,
                    [cv2.CAP_PROP_OPEN_TIMEOUT_MSEC, 5000,
                     cv2.CAP_PROP_READ_TIMEOUT_MSEC, 5000])
            except Exception:
                cap = cv2.VideoCapture(url)
            if cap is None or not cap.isOpened():
                return "nofirst"
            try:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
            except Exception:
                pass
            first = False
            last_ok = time.time()
            while self.cam_token is token:
                ok, frame = cap.read()
                if ok and frame is not None and frame.size:
                    first = True
                    last_ok = time.time()
                    self._on_frame(frame, "stream")
                else:
                    if time.time() - last_ok > 4.0:
                        break
                    time.sleep(0.05)
            return "lost" if first else "nofirst"
        finally:
            if cap is not None:
                cap.release()

    def _run_snapshots(self, token, base):
        url = base + "/shot.jpg"
        sess = requests.Session()
        fails = 0
        self.cam_status = "Connecting (snapshots)..."
        while self.cam_token is token:
            t0 = time.time()
            try:
                r = sess.get(url, timeout=3)
                if r.status_code == 200 and r.content:
                    frame = cv2.imdecode(np.frombuffer(r.content, np.uint8),
                                         cv2.IMREAD_COLOR)
                    if frame is not None:
                        fails = 0
                        self._on_frame(frame, "snapshot")
                        dt = time.time() - t0
                        if dt < 0.08:
                            time.sleep(0.08 - dt)
                        continue
                fails += 1
            except requests.RequestException:
                fails += 1
            if fails >= 8:
                self.cam_status = "Snapshot fetch failed"
                return
            time.sleep(0.2)

    def _on_frame(self, frame, mode):
        now = time.time()
        self.cam_status = f"Connected ({mode})"
        self.cam_mode = mode
        self.frame_w = frame.shape[1]
        with self._raw_lock:
            self._raw = frame            # the detector only READS this array
            self._raw_id += 1
        self._frame_times.append(now)
        if len(self._frame_times) >= 2:
            span = self._frame_times[-1] - self._frame_times[0]
            if span > 0:
                self.fps = (len(self._frame_times) - 1) / span
        self._publish(frame)

    def _publish(self, frame):
        try:
            h, w = frame.shape[:2]
            scale = min(1.0, self.DISPLAY_W / float(w))
            if scale < 1.0:
                disp = cv2.resize(frame, (int(w * scale), int(h * scale)),
                                  interpolation=cv2.INTER_AREA)
            else:
                disp = frame.copy()
            d = self.det
            if d and time.time() - d["t"] < 1.0:
                pts = (np.asarray(d["pts"]) * scale).astype(np.int32)
                colour = (0, 255, 0) if d["decoded"] else (0, 165, 255)
                cv2.polylines(disp, [pts], True, colour, 3)
                label = d["code"] or "QR (not readable yet)"
                dist = self._distance(d["wpx"])
                if dist:
                    label += f"  {dist:.0f} cm  ~{self.steps(dist)} steps"
                cv2.putText(disp, label, (10, 32), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, (0, 0, 0), 4)
                cv2.putText(disp, label, (10, 32), cv2.FONT_HERSHEY_SIMPLEX,
                            0.8, colour, 2)
            ok, buf = cv2.imencode(".jpg", disp, [int(cv2.IMWRITE_JPEG_QUALITY), 70])
            if ok:
                self.frame_jpeg = buf.tobytes()
                self.frame_time = time.time()
        except Exception as e:
            self._log_throttled("pub", f"Frame encode failed: {type(e).__name__}: {e}")

    def _detect_loop(self, token):
        detectors = make_detectors()
        self.engine_names = "+".join(n for n, _ in detectors) + \
            ("+pyzbar" if _pyzbar is not None else "")
        last_id = -1
        while self.cam_token is token:
            with self._raw_lock:
                frame, fid = self._raw, self._raw_id
            if frame is None or fid == last_id:
                time.sleep(0.01)
                continue
            last_id = fid
            try:
                text, wpx, pts = detect_qr(frame, detectors)
            except Exception as e:
                self._log_throttled("det", f"QR detect error: {type(e).__name__}: {e}")
                time.sleep(0.2)
                continue
            if pts is not None and wpx:
                self._register_detection(text, wpx, pts)

    def _register_detection(self, text, wpx, pts):
        now = time.time()
        if text:
            if self._last_code and text != self._last_code:
                self._wpx_hist.clear()       # a different QR: don't mix widths
            self._last_code, self._last_code_t = text, now
            code = text
        elif now - self._last_code_t < 1.0:
            code = self._last_code           # shape seen, decode missed this frame
        else:
            code = ""
        self._wpx_hist.append((now, float(wpx)))
        smooth = self._recent_width(1.5) or float(wpx)
        self.det = dict(code=code, wpx=smooth, pts=pts, t=now, decoded=bool(text))
        if text:
            self._log_throttled(f"seen-{text}", f"QR detected: {text}", every=6.0)

    def _sim_loop(self, token):
        self.cam_status = "SIMULATED"
        self.cam_mode = "sim"
        self.log("Simulation camera started (motors are NEVER driven in sim mode)")
        last = time.time()
        while self.cam_token is token:
            now = time.time()
            dt = max(1e-3, now - last)
            last = now
            if self.state.startswith("Moving") and not self.stop_flag.is_set():
                self._sim_fake = max(20.0, self._sim_fake - 45.0 * dt)
            elif self.state.startswith("At "):
                self._sim_fake = 25.0
            code = self.sim_target or ""
            self.frame_w = 640
            frame = np.zeros((480, 640, 3), dtype=np.uint8)
            cv2.putText(frame, f"SIM  {code or '-'}  {self._sim_fake:.0f} cm",
                        (20, 60), cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            if code:
                wpx = self._effective_focal() * self.cfg["qr_cm"] / self._sim_fake
                cx, cy = 320, 260
                pts = np.array([[cx - wpx / 2, cy - wpx / 2], [cx + wpx / 2, cy - wpx / 2],
                                [cx + wpx / 2, cy + wpx / 2], [cx - wpx / 2, cy + wpx / 2]],
                               np.float32)
                self.det = dict(code=code, wpx=float(wpx), pts=pts, t=now, decoded=True)
            else:
                self.det = None
            self._publish(frame)
            time.sleep(0.05)

    def test_camera(self):
        base, _ = self._split_url(self.cfg["cam_url"])
        if not base:
            return False, "Enter the phone camera URL first."
        ok, why = self._phone_reachable(base)
        if not ok:
            return False, (f"Cannot reach {base} ({why}). Check: laptop on the "
                           f"SmartTrolley Wi-Fi, IP Webcam 'Start server' is running, "
                           f"and the IP matches the one on the phone screen.")
        try:
            r = requests.get(base + "/shot.jpg", timeout=4)
            img = cv2.imdecode(np.frombuffer(r.content, np.uint8), cv2.IMREAD_COLOR)
            if img is None:
                return False, (f"Phone reachable but /shot.jpg gave no image "
                               f"(HTTP {r.status_code}). Is this IP Webcam?")
            h, w = img.shape[:2]
            return True, (f"Phone reachable, snapshot OK ({w}x{h}). "
                          f"App camera status: {self.cam_status}")
        except requests.RequestException as e:
            return False, f"Phone reachable but snapshot failed: {type(e).__name__}"

    def _url_for(self, command):
        ip = self.cfg["ip"].strip()
        if not ip.startswith("http"):
            ip = f"http://{ip}"
        ip = ip.rstrip("/")
        style = self.cfg["endpoint_style"]
        if style == "query":
            return f"{ip}/?cmd={command}"
        if style == "cmd":
            return f"{ip}/cmd?dir={command}"
        return f"{ip}/{command}"

    def send(self, command, retries=1):
        if command not in ("forward", "backward", "left", "right", "stop"):
            return False
        # Simulation can NEVER drive real motors.
        if self.cfg["dry_run"] or self.cfg["sim_mode"]:
            self._log_throttled(f"dry-{command}", f"[DRY RUN] {command}", every=1.0)
            self.motor_ok += 1
            return True
        url = self._url_for(command)
        for attempt in range(retries + 1):
            try:
                r = self.session.get(url, timeout=1.0)
                if r.status_code == 200:
                    self.motor_ok += 1
                    self._log_throttled(f"ok-{command}", f"[ESP32] {command} -> 200",
                                        every=1.0)
                    return True
                self.last_motor_error = f"HTTP {r.status_code} from {url}"
            except requests.RequestException as e:
                self.last_motor_error = f"{type(e).__name__} on {url}"
            if attempt < retries:
                time.sleep(0.15)
        self.motor_fail += 1
        self.log(f"ESP32 FAILED: {command} ({self.last_motor_error})")
        return False

    def test_connection(self):
        if self.cfg["dry_run"] or self.cfg["sim_mode"]:
            return False, "DRY RUN / simulation is ON - turn both off to test the motors."
        url = self._url_for("stop")
        t0 = time.time()
        try:
            r = self.session.get(url, timeout=3.0)
            ms = (time.time() - t0) * 1000
            body = (r.text or "").strip()[:100].replace("\n", " ")
            if r.status_code == 200:
                return True, f"ESP32 reachable ({ms:.0f} ms). Reply: {body or '(empty)'}"
            return False, (f"ESP32 answered HTTP {r.status_code} for {url}. "
                           f"Try another 'endpoint style' in the sidebar.")
        except requests.RequestException as e:
            return False, (f"Cannot reach {url} ({type(e).__name__}). Is the laptop "
                           f"on the SmartTrolley Wi-Fi, and is the ESP32 powered?")

    def emergency_stop(self):
        self.stop_flag.set()
        for _ in range(3):
            self.send("stop")
        self.state = "STOPPED"
        self.say("Emergency stop.", urgent=True)

    def turn(self, command, seconds):
        end = time.time() + seconds
        while time.time() < end:
            if self.stop_flag.is_set():
                self.send("stop")
                return False
            if not self.send(command, retries=1):
                self.send("stop")
                return False
            time.sleep(0.12)
        self.send("stop")
        time.sleep(0.35)
        return True

    def do_turn(self, diff):
        t = self.cfg["turn90"]
        if diff == 1:
            self.say("Turning right")
            return self.turn("right", t)
        if diff == 3:
            self.say("Turning left")
            return self.turn("left", t)
        if diff == 2:
            self.say("Turning around")
            return self.turn("right", t * 2)
        return True

    def _distance_cue(self, code, dist, target, announced):
        if dist is None:
            return
        name = (code or target).lower()
        if dist <= self.cfg["arrive_cm"]:
            return
        n = self.steps(dist)
        if n <= 6:
            key = f"step{n}"
            if key not in announced:
                announced.add(key)
                if n == 1:
                    self.say(f"One step to {name}.", urgent=True)
                else:
                    self.say(f"{n} steps to {name}.")
            return
        now = time.time()
        if now - self._last_far_cue >= self.cfg["cue_far_every"]:
            key = f"bucket{int(n // 5) * 5}"
            if key not in announced:
                announced.add(key)
                self._last_far_cue = now
                self.say(f"{name} is about {n} steps ahead. Keep going straight.")

    def travel_to(self, target):
        """Drive forward until the target QR is within arrive_cm."""
        self.sim_target = target
        self._sim_fake = 400.0
        start = time.time()
        last_drive = 0.0
        announced = set()
        last_seen = None
        said_search = False
        continuous = self.cfg["drive_mode"] == "continuous"

        while time.time() - start < self.cfg["max_travel"]:
            if self.stop_flag.is_set():
                self.send("stop")
                return False

            self.state = f"Moving to {target}"
            if continuous:
                if time.time() - last_drive > 0.5:
                    if not self.send("forward", retries=2):
                        self.send("stop")
                        self.say("I cannot reach the motors. Stopping.", urgent=True)
                        return False
                    last_drive = time.time()
                scan_end = time.time() + 0.1
            else:
                if not self.send("forward", retries=2):
                    self.send("stop")
                    self.say("I cannot reach the motors. Stopping.", urgent=True)
                    return False
                time.sleep(self.cfg["pulse_on"])
                self.send("stop")
                self.state = f"Scanning for {target}"
                scan_end = time.time() + self.cfg["pulse_off"]

            while time.time() < scan_end:
                if self.stop_flag.is_set():
                    self.send("stop")
                    return False
                code, dist = self.fresh_qr()
                if code and dist is not None:
                    if code == target:
                        last_seen = time.time()
                        if dist <= self.cfg["arrive_cm"]:
                            self.send("stop")
                            self.say(f"We have reached {target.lower()}. "
                                     f"It is right in front of you.", urgent=True)
                            return True
                    self._distance_cue(code, dist, target, announced)
                time.sleep(0.02)

            if not said_search and last_seen is None and time.time() - start > 10:
                said_search = True
                self.say(f"Still looking for {target.lower()}. Please check its "
                         f"code is in front of the camera.")

        self.send("stop")
        return False

    def start_mission(self, items):
        if self.running:
            return False
        self.stop_flag.clear()
        self.running = True
        self.state = "Starting"
        threading.Thread(target=self._mission, args=(list(items),), daemon=True).start()
        return True

    def _mission(self, items):
        try:
            remaining = list(items)
            self.say("Starting shopping trip.")
            while remaining and not self.stop_flag.is_set():
                best = min(remaining, key=lambda p: dijkstra(self.current, p)[1])
                route, _ = dijkstra(self.current, best)
                self.log(f"Route: {' -> '.join(route)}")
                self.say(f"Going to {best.lower()}.")

                for nxt in route[1:]:
                    nh = heading_of(self.current, nxt)
                    if not self.do_turn((nh - self.heading) % 4):
                        raise RuntimeError("Turn stopped")
                    self.heading = nh
                    if not self.travel_to(nxt):
                        if self.stop_flag.is_set():
                            raise RuntimeError("Stopped by user")
                        self.say("Checkpoint not found. Navigation stopped.", urgent=True)
                        return
                    self.current = nxt
                    if nxt != best:
                        self.say(f"Passing {nxt.lower()}.")

                self.say(f"You have reached {best.lower()}. Please pick up the item.",
                         urgent=True)
                remaining.remove(best)
                self.state = f"At {best} (waiting)"
                for _ in range(30):
                    if self.stop_flag.is_set():
                        break
                    time.sleep(0.1)

            if not self.stop_flag.is_set():
                self.say("All items reached. Shopping complete.", urgent=True)
        except Exception as e:
            self.log(f"Mission ended: {e}")
        finally:
            self.send("stop")
            self.running = False
            self.sim_target = None
            if self.state != "STOPPED":
                self.state = "Idle"

    def reset_position(self):
        self.current, self.heading = "ENTRANCE", 0
        self.log("Position reset to ENTRANCE, facing north")
        self.say("Position reset to entrance.")

    def handle_voice_command(self, text):
        t = (text or "").lower().strip()
        if not t:
            return "I did not catch that."
        self.log(f"🎤 command: {t}")

        if any(w in t for w in ("stop", "halt", "cancel", "abort")):
            self.emergency_stop()
            return "Stopped."
        if any(w in t for w in ("repeat", "again", "what did you say")):
            if self.last_instruction:
                self.say(self.last_instruction, urgent=True)
                return f"Repeating: {self.last_instruction}"
            return "Nothing to repeat yet."
        if any(w in t for w in ("status", "where am i", "where are we")):
            msg = f"You are at {self.current.lower()}. State: {self.state}."
            self.say(msg, urgent=True)
            return msg
        if any(w in t for w in ("reset", "start over")):
            self.reset_position()
            return "Position reset."
        if "go to" in t or "take me to" in t or "find" in t:
            for p in PRODUCTS:
                if p.lower() in t:
                    if self.running:
                        self.say("Already on a trip. Stop first.", urgent=True)
                        return "Already running."
                    self.start_mission([p])
                    return f"Heading to {p.lower()}."
            return "I do not know that product."
        if any(w in t for w in ("start", "begin", "shop", "go shopping")):
            picked = [p for p in PRODUCTS if p.lower() in t] or ["MILK"]
            if self.running:
                return "Already running."
            self.start_mission(picked)
            return f"Starting trip for {', '.join(picked).lower()}."
        if "forward" in t:
            self.send("forward")
            time.sleep(self.cfg["pulse_on"])
            self.send("stop")
            return "Moved forward briefly."
        if "left" in t:
            self.turn("left", self.cfg["turn90"])
            return "Turning left."
        if "right" in t:
            self.turn("right", self.cfg["turn90"])
            return "Turning right."
        if "help" in t:
            msg = ("Say: start shopping, stop, go to milk, status, repeat, "
                   "turn left, turn right, forward.")
            self.say(msg, urgent=True)
            return msg
        return f"I heard '{t}', but I do not know that command."


@st.cache_resource
def get_trolley():
    return Trolley()



def _ensure_wav(data: bytes) -> bytes:
    if data[:4] == b"RIFF":
        return data
    if not shutil.which("ffmpeg"):
        return data
    try:
        out = subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error",
             "-i", "pipe:0", "-ac", "1", "-ar", "16000", "-f", "wav", "pipe:1"],
            input=data, stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=30)
        return out.stdout or data
    except Exception:
        return data


def _speech_recognition_available() -> bool:
    try:
        import speech_recognition  # noqa: F401
        return True
    except Exception:
        return False


def transcribe_audio(data: bytes) -> str:
    try:
        import speech_recognition as sr
    except ImportError:
        return "__MISSING__"
    wav = _ensure_wav(data)
    r = sr.Recognizer()
    r.energy_threshold = 250
    r.dynamic_energy_threshold = True
    try:
        with sr.AudioFile(io.BytesIO(wav)) as src:
            audio = r.record(src)
    except Exception as e:
        return f"__ERROR__{e}"
    try:
        return r.recognize_google(audio)
    except sr.UnknownValueError:
        return ""
    except sr.RequestError as e:
        return f"__ERROR__{e}"



HAS_FRAGMENT = hasattr(st, "fragment")
_WIDE = [{"width": "stretch"}, {"use_container_width": True}, {}]


def wide(fn, *args, **kw):
    for i, extra in enumerate(_WIDE):
        try:
            return fn(*args, **kw, **extra)
        except Exception:
            if i == len(_WIDE) - 1:
                raise


def _fragment(**kw):
    if HAS_FRAGMENT:
        return st.fragment(**kw)
    return lambda f: f


@_fragment(run_every=0.4)
def live_view():
    try:
        T = get_trolley()
        left, right = st.columns([3, 2])

        with left:
            if T.frame_jpeg:
                wide(st.image, T.frame_jpeg)
                if T.frame_time and time.time() - T.frame_time > 5.0:
                    st.caption("Last frame is over 5 s old - stream stalled?")
            else:
                st.info(f"Waiting for camera... ({T.cam_status})")

        with right:
            st.subheader("📊 Live status")
            code, dist = T.fresh_qr()
            a, b = st.columns(2)
            a.metric("QR seen", code if code else "—")
            b.metric("Distance", f"{dist:.0f} cm" if dist else "—")
            a, b = st.columns(2)
            a.metric("Steps away", T.steps(dist) if dist else "—")
            b.metric("Trolley state", T.state)
            a, b = st.columns(2)
            a.metric("Position", T.current)
            b.metric("Camera", T.cam_status)
            st.caption(f"Video {T.fps:.0f} fps · QR engine: {T.engine_names or '—'}")

            if T.focal is None:
                st.warning("Distance is an uncalibrated estimate (±20%). "
                           "Press Calibrate in the sidebar for accurate cm.")
            if T.cfg["sim_mode"]:
                st.info("SIMULATION - fake camera, motors never move.")
            elif T.cfg["dry_run"]:
                st.info("DRY RUN is ON — motors will not move.")
            else:
                st.error("LIVE MODE — the trolley WILL move.")

            st.caption(f"🔊 Speaking: {T.speaker.current or '—'}")
            if T.last_instruction:
                st.caption(f"📢 Last: {T.last_instruction}")

            st.subheader("📜 Log")
            st.code("\n".join(list(T.logs)[:18]) or "No events yet", language=None)
    except Exception as e:
        st.error(f"Live view error: {type(e).__name__}: {e}")



from pathwise_features import pathwise_panel



def main():
    if not HAS_FRAGMENT:
        st.error("Please upgrade Streamlit:  pip install -U streamlit")
        st.stop()

    T = get_trolley()
    if T.cam_token is None:
        T.start_camera()

    st.title("🛒 SmartTrolley AI")
    st.caption("Voice-guided shopping assistant for visually impaired shoppers — "
               "controlled demonstration prototype")

    with st.sidebar:
        st.header("⚙️ Setup")

        sim = st.toggle("🧪 Simulation mode (no hardware)", value=T.cfg["sim_mode"],
                        help="Fake camera + fake distance. Motors never move.")
        T.cfg["sim_mode"] = sim
        if sim != T._sim_prev:
            T._sim_prev = sim
            T.start_camera()

        new_url = st.text_input("Phone camera URL", T.cfg["cam_url"],
                                help="Use the address shown in the IP Webcam app, "
                                     "e.g. http://192.168.4.2:8080/video")
        if new_url != T.cfg["cam_url"]:
            T.cfg["cam_url"] = new_url
            T.start_camera()
        c1, c2 = st.columns(2)
        if c1.button("🔄 Reconnect"):
            T.start_camera()
            st.success("Reconnecting…")
        if c2.button("📷 Test camera"):
            ok, msg = T.test_camera()
            (st.success if ok else st.error)(msg)

        T.cfg["ip"] = st.text_input("ESP32 IP", T.cfg["ip"])
        T.cfg["dry_run"] = st.toggle(
            "DRY RUN (motors will NOT move)", value=T.cfg["dry_run"],
            help="Turn this OFF to actually drive the motors.")
        if T.cfg["dry_run"]:
            st.warning("DRY RUN is ON — the trolley will never move. Turn it off.")
        else:
            st.error("LIVE MODE — the trolley WILL move.")

        styles = ["path", "query", "cmd"]
        T.cfg["endpoint_style"] = st.selectbox(
            "ESP32 endpoint style", styles,
            index=styles.index(T.cfg["endpoint_style"]),
            help="path = /forward   query = /?cmd=forward   cmd = /cmd?dir=forward")
        if st.button("🔌 Test ESP32 connection"):
            ok, msg = T.test_connection()
            (st.success if ok else st.error)(msg)
        st.caption(f"Motor calls: ✅ {T.motor_ok}   ❌ {T.motor_fail}")
        if T.last_motor_error:
            st.caption(f"Last error: {T.last_motor_error}")

        T.cfg["speak"] = st.toggle("🔊 Spoken instructions", value=T.cfg["speak"])
        T.speaker.enabled = T.cfg["speak"]
        if T.speaker.backend == "none":
            st.warning("No speech engine found, so cues are text-only. "
                       "Linux: sudo apt install espeak-ng")
        else:
            st.caption(f"Speech engine: {T.speaker.backend}")

        st.subheader("QR / distance")
        T.cfg["qr_cm"] = st.number_input("Real QR width (cm)", 1.0, 50.0, float(T.cfg["qr_cm"]))
        T.cfg["cal_cm"] = st.number_input("Calibration distance (cm)", 10.0, 200.0,
                                          float(T.cfg["cal_cm"]))
        T.cfg["step_cm"] = st.number_input("Step length (cm)", 30.0, 100.0,
                                           float(T.cfg["step_cm"]))
        T.cfg["arrive_cm"] = st.number_input("Arrive when QR closer than (cm)", 10.0, 150.0,
                                             float(T.cfg["arrive_cm"]))
        if st.button("📏 Calibrate (QR at calibration distance)"):
            if T.calibrate():
                st.success("Calibrated and saved.")
            else:
                st.error("No QR seen in the last 2 seconds. Hold it in front of the "
                         "camera, wait until the outline appears, then click again.")

        st.subheader("Motion")
        modes = ["pulse", "continuous"]
        T.cfg["drive_mode"] = st.selectbox(
            "Drive mode", modes, index=modes.index(T.cfg["drive_mode"]),
            help="pulse = short slow hops, scans while stopped (recommended). "
                 "continuous = keeps driving.")
        T.cfg["pulse_on"] = st.slider("Forward pulse (s)", 0.05, 1.5, float(T.cfg["pulse_on"]), 0.05)
        T.cfg["pulse_off"] = st.slider("Pause / scan (s)", 0.1, 1.5, float(T.cfg["pulse_off"]), 0.05)
        T.cfg["turn90"] = st.slider("90° turn time (s)", 0.2, 2.0, float(T.cfg["turn90"]), 0.05)
        T.cfg["max_travel"] = st.slider("Max travel per leg (s)", 5.0, 90.0,
                                        float(T.cfg["max_travel"]), 1.0)
        T.cfg["cue_far_every"] = st.slider("Seconds between far cues", 2.0, 20.0,
                                           float(T.cfg["cue_far_every"]), 1.0)
        if st.button("↩️ Reset position to ENTRANCE"):
            T.reset_position()

        st.subheader("🎤 Commands")
        heard = None
        if _speech_recognition_available() and hasattr(st, "audio_input"):
            clip = st.audio_input("Hold the mic and speak a command")
            if clip is not None:
                data = clip.getvalue() if hasattr(clip, "getvalue") else clip.read()
                if data and hash(data) != st.session_state.get("last_audio"):
                    st.session_state["last_audio"] = hash(data)   # run each clip ONCE
                    with st.spinner("Listening…"):
                        heard = transcribe_audio(data)
        else:
            st.caption("Mic input needs: pip install SpeechRecognition "
                       "(typed commands always work).")

        with st.form("cmd_form", clear_on_submit=True):
            typed = st.text_input("Type a command", placeholder="go to milk")
            submitted = st.form_submit_button("Send")
        if submitted and typed.strip():
            heard = typed.strip()                                  # ...and typed ONCE

        if heard == "__MISSING__":
            st.session_state["reply"] = "SpeechRecognition is not installed - type instead."
        elif heard and heard.startswith("__ERROR__"):
            st.session_state["reply"] = f"Speech recognition failed: {heard[9:]}"
        elif heard == "":
            st.session_state["reply"] = "I could not make out any words - try again."
        elif heard:
            st.session_state["reply"] = f"“{heard}” → {T.handle_voice_command(heard)}"
        if st.session_state.get("reply"):
            st.info(st.session_state["reply"])

        T.save_settings()

    col_list, col_go, col_manual = st.columns([2, 2, 3])
    with col_list:
        st.subheader("🎯 Shopping list")
        items = st.multiselect("Choose products", PRODUCTS, default=["MILK"])
    with col_go:
        st.subheader("Trip")
        if wide(st.button, "▶️ START", type="primary"):
            if not items:
                st.warning("Pick at least one product.")
            elif T.running:
                st.warning("Already running.")
            else:
                T.start_mission(items)
        if wide(st.button, "🛑 EMERGENCY STOP"):
            T.emergency_stop()
        if wide(st.button, "🔁 Repeat last instruction"):
            if T.last_instruction:
                T.say(T.last_instruction, urgent=True)
    with col_manual:
        st.subheader("🔧 Manual test (one pulse)")
        m = st.columns(4)
        for col, cmd in zip(m, ["forward", "left", "right", "stop"]):
            if wide(col.button, cmd.capitalize()):
                T.send(cmd)
                if cmd != "stop":
                    time.sleep(T.cfg["pulse_on"])
                    T.send("stop")

    pathwise_panel(T)
    live_view()


if __name__ == "__main__":
    main()
