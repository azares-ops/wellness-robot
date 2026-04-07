import cv2
import numpy as np
from collections import deque

class PostureDetector:
    KEYPOINT_NAMES = [
        'nose', 'left_eye', 'right_eye', 'left_ear', 'right_ear',
        'left_shoulder', 'right_shoulder', 'left_elbow', 'right_elbow',
        'left_wrist', 'right_wrist', 'left_hip', 'right_hip',
        'left_knee', 'right_knee', 'left_ankle', 'right_ankle'
    ]

    def __init__(self):
        print("[PostureDetector] Loading YOLOv8-nano-pose...")
        from ultralytics import YOLO
        self.model = YOLO('yolov8n-pose.pt')
        dummy = np.zeros((320, 320, 3), dtype=np.uint8)
        self.model(dummy, verbose=False)

        # ── Calibration state ──────────────────────────────────────────────
        # Collect 20 "good posture" frames at startup, then set personal
        # thresholds relative to the user's actual measurements.
        self._cal_frames     = []          # raw measurements during calibration
        self._cal_done       = False
        self._CAL_TARGET     = 20          # frames to collect

        # Personal baselines (set after calibration)
        self._base_head_drop  = None       # pixels: nose above shoulder midpoint
        self._base_tilt       = None       # shoulder height diff / shoulder width
        self._base_spine_cx   = None       # |shoulder cx - hip cx| / shoulder width
        self._base_hunch_cx   = None       # same as spine_cx (front-cam hunch)

        # Light temporal smoothing
        self._alert_history  = deque(maxlen=4)
        self._score_history  = deque(maxlen=6)

        print("[PostureDetector] Ready. Sit straight for 5 sec to calibrate.")

    # ──────────────────────────────────────────────────────────────────────
    def detect(self, frame):
        results = self.model(frame, verbose=False, conf=0.5, imgsz=320)[0]

        if results.keypoints is None or len(results.keypoints.data) == 0:
            return {'keypoints': {}, 'posture': None, 'bbox': None,
                    'detected': False, 'score': 0}

        kp_data = results.keypoints.data[0].cpu().numpy()
        box     = results.boxes.xyxy[0].cpu().numpy() \
                  if results.boxes is not None else None

        kp = {}
        for i, name in enumerate(self.KEYPOINT_NAMES):
            x, y, conf = kp_data[i]
            kp[name] = {'x': float(x), 'y': float(y), 'confidence': float(conf)}

        # ── Calibration phase ──────────────────────────────────────────────
        if not self._cal_done:
            self._calibrate(kp)
            # During calibration just report good posture with no alerts
            posture = {'position': 'calibrating', 'alerts': [],
                       'good_posture': True, 'score': 100, 'smoothed_score': 100,
                       'calibrating': True,
                       'cal_pct': int(len(self._cal_frames) / self._CAL_TARGET * 100)}
            return {'keypoints': kp, 'posture': posture,
                    'bbox': box.tolist() if box is not None else None,
                    'detected': True, 'score': 100}

        # ── Normal detection ───────────────────────────────────────────────
        posture = self._analyze(kp, frame.shape)

        self._alert_history.append(posture['alerts'])
        if len(self._alert_history) >= 2:
            counts = {}
            for fa in self._alert_history:
                for a in fa:
                    counts[a] = counts.get(a, 0) + 1
            posture['alerts'] = [a for a, c in counts.items()
                                 if c >= len(self._alert_history) * 0.5]

        posture['good_posture'] = len(posture['alerts']) == 0
        posture['score']        = int(self._compute_score(posture['alerts']))
        self._score_history.append(posture['score'])
        posture['smoothed_score'] = int(round(float(np.mean(self._score_history))))

        return {
            'keypoints': kp,
            'posture':   posture,
            'bbox':      box.tolist() if box is not None else None,
            'detected':  True,
            'score':     posture['smoothed_score'],
        }

    # ──────────────────────────────────────────────────────────────────────
    def _get(self, kp, name, min_conf=0.4):
        p = kp.get(name)
        if p and p['confidence'] >= min_conf:
            return np.array([p['x'], p['y']])
        return None

    def _measure(self, kp):
        """Extract raw measurements from a keypoint set. Returns dict or None."""
        ls   = self._get(kp, 'left_shoulder')
        rs   = self._get(kp, 'right_shoulder')
        nose = self._get(kp, 'nose')

        if ls is None or rs is None or nose is None:
            return None

        sw           = abs(ls[0] - rs[0]) + 1e-5
        shoulder_mid = (ls + rs) / 2
        head_drop    = shoulder_mid[1] - nose[1]          # +ve = nose above shoulders
        tilt         = abs(ls[1] - rs[1]) / sw

        m = {'head_drop': head_drop, 'sw': sw, 'tilt': tilt,
             'head_drop_ratio': head_drop / sw}

        lh = self._get(kp, 'left_hip')
        rh = self._get(kp, 'right_hip')
        if lh is not None and rh is not None:
            shoulder_cx = (ls[0] + rs[0]) / 2
            hip_cx      = (lh[0] + rh[0]) / 2
            m['spine_ratio'] = abs(shoulder_cx - hip_cx) / sw
        else:
            m['spine_ratio'] = None

        return m

    def _calibrate(self, kp):
        """Collect frames while user sits straight. Set personal thresholds."""
        m = self._measure(kp)
        if m is None:
            return  # can't use this frame

        self._cal_frames.append(m)

        if len(self._cal_frames) >= self._CAL_TARGET:
            good = self._cal_frames

            # ── Head drop baseline ──────────────────────────────────────────
            # User's natural good-posture head_drop ratio
            hdr_vals = [f['head_drop_ratio'] for f in good]
            base_hdr = float(np.median(hdr_vals))
            # Alert if head_drop falls more than 35% below baseline
            self._base_head_drop = max(0.05, base_hdr * 0.65)

            # ── Shoulder tilt ───────────────────────────────────────────────
            tilt_vals = [f['tilt'] for f in good]
            base_tilt = float(np.median(tilt_vals))
            # Alert if tilt exceeds baseline + 0.12 (but at least 0.18)
            self._base_tilt = max(0.18, base_tilt + 0.12)

            # ── Spine / hunch (if hips visible) ────────────────────────────
            spine_vals = [f['spine_ratio'] for f in good if f['spine_ratio'] is not None]
            if spine_vals:
                base_spine = float(np.median(spine_vals))
                self._base_spine = max(0.15, base_spine + 0.12)
            else:
                self._base_spine = 0.22   # fallback

            self._cal_done = True
            print(f"[PostureDetector] Calibration done.")
            print(f"  head_drop threshold ratio : {self._base_head_drop:.3f}")
            print(f"  shoulder tilt threshold   : {self._base_tilt:.3f}")
            print(f"  spine/hunch threshold     : {self._base_spine:.3f}")

    def _analyze(self, kp, shape):
        alerts = []

        ls   = self._get(kp, 'left_shoulder')
        rs   = self._get(kp, 'right_shoulder')
        lh   = self._get(kp, 'left_hip')
        rh   = self._get(kp, 'right_hip')
        lk   = self._get(kp, 'left_knee')
        rk   = self._get(kp, 'right_knee')
        nose = self._get(kp, 'nose')

        if ls is None or rs is None:
            return {'position': 'unknown', 'alerts': [], 'good_posture': True}

        sw = abs(ls[0] - rs[0]) + 1e-5

        # ── POSITION ──────────────────────────────────────────────────────
        position = 'sitting'
        if lh is not None and rh is not None:
            shoulder_mid = (ls + rs) / 2
            hip_mid      = (lh + rh) / 2
            torso_len    = abs(hip_mid[1] - shoulder_mid[1])
            if lk is not None and rk is not None:
                knee_mid = (lk + rk) / 2
                leg_len  = abs(knee_mid[1] - hip_mid[1])
                position = 'sitting' if leg_len < torso_len * 0.6 else 'standing'

        # ── HEAD DOWN ─────────────────────────────────────────────────────
        if nose is not None:
            shoulder_mid = (ls + rs) / 2
            head_drop_ratio = (shoulder_mid[1] - nose[1]) / sw
            if head_drop_ratio < self._base_head_drop:
                alerts.append('head_down')

        # ── UNEVEN SHOULDERS ──────────────────────────────────────────────
        tilt = abs(ls[1] - rs[1]) / sw
        if tilt > self._base_tilt:
            alerts.append('uneven_shoulders')

        # ── SPINE LEAN + FORWARD HUNCH (needs hips) ───────────────────────
        if lh is not None and rh is not None:
            shoulder_cx = (ls[0] + rs[0]) / 2
            hip_cx      = (lh[0] + rh[0]) / 2
            offset      = abs(shoulder_cx - hip_cx) / sw

            if offset > self._base_spine:
                # Distinguish lean vs hunch by direction
                # Pure lateral = spine_lean, forward offset same in both = hunch
                alerts.append('spine_lean')

        return {
            'position':    position,
            'alerts':      alerts,
            'good_posture': len(alerts) == 0,
        }

    def _compute_score(self, alerts):
        penalty = {'forward_hunch': 35, 'head_down': 25,
                   'spine_lean': 20, 'uneven_shoulders': 15}
        return int(max(0, 100 - sum(penalty.get(a, 10) for a in alerts)))
