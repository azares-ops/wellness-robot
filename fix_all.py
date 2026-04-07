"""
Run this directly on the Pi:
  cd /home/who/grok_robo && python3 /home/claude/fix_all.py
  (or copy to Pi and run there)
"""
import os, re

BASE = '/home/who/grok_robo'

# ─────────────────────────────────────────────────────────────
# 1. POSTURE ENGINE — fix thresholds + numpy serialization
# ─────────────────────────────────────────────────────────────
POSTURE = '''\
import cv2
import numpy as np
from collections import deque

class PostureDetector:
    KEYPOINT_NAMES = [
        "nose", "left_eye", "right_eye", "left_ear", "right_ear",
        "left_shoulder", "right_shoulder", "left_elbow", "right_elbow",
        "left_wrist", "right_wrist", "left_hip", "right_hip",
        "left_knee", "right_knee", "left_ankle", "right_ankle"
    ]

    def __init__(self):
        print("[PostureDetector] Loading YOLOv8-pose...")
        from ultralytics import YOLO
        self.model = YOLO("yolov8m-pose.pt")
        dummy = np.zeros((480, 640, 3), dtype=np.uint8)
        self.model(dummy, verbose=False)
        self._alert_history          = deque(maxlen=6)
        self._posture_score_history  = deque(maxlen=8)
        print("[PostureDetector] Ready.")

    def detect(self, frame):
        results = self.model(frame, verbose=False, conf=0.35, imgsz=640)[0]
        if results.keypoints is None or len(results.keypoints.data) == 0:
            return {"keypoints": {}, "posture": None, "bbox": None,
                    "detected": False, "score": 0}

        best_idx = self._pick_best_person(results)
        kp_data  = results.keypoints.data[best_idx].cpu().numpy()
        box      = results.boxes.xyxy[best_idx].cpu().numpy() if results.boxes is not None else None

        kp = {}
        for i, name in enumerate(self.KEYPOINT_NAMES):
            x, y, conf = kp_data[i]
            kp[name] = {"x": float(x), "y": float(y), "confidence": float(conf)}

        posture = self._analyze(kp, frame.shape)
        self._alert_history.append(posture["alerts"])
        posture["alerts"]       = self._smooth_alerts()
        posture["good_posture"] = len(posture["alerts"]) == 0
        posture["score"]        = int(self._compute_score(posture["alerts"]))
        self._posture_score_history.append(posture["score"])
        posture["smoothed_score"] = int(round(float(np.mean(self._posture_score_history))))

        return {
            "keypoints": kp,
            "posture":   posture,
            "bbox":      box.tolist() if box is not None else None,
            "detected":  True,
            "score":     posture["smoothed_score"],
        }

    def _pick_best_person(self, results):
        if len(results.keypoints.data) == 1:
            return 0
        best, best_conf = 0, -1.0
        for i, kp in enumerate(results.keypoints.data):
            avg = float(kp[:, 2].mean())
            if avg > best_conf:
                best_conf, best = avg, i
        return best

    def _smooth_alerts(self):
        if len(self._alert_history) < 2:
            return list(self._alert_history[-1]) if self._alert_history else []
        counts = {}
        total  = len(self._alert_history)
        for fa in self._alert_history:
            for a in fa:
                counts[a] = counts.get(a, 0) + 1
        # fire if alert appears in >= 40% of recent frames (was 50%)
        return [a for a, c in counts.items() if c >= total * 0.40]

    def _compute_score(self, alerts):
        penalty = {"forward_hunch": 35, "head_down": 25,
                   "spine_lean": 20, "uneven_shoulders": 15}
        return int(max(0, 100 - sum(penalty.get(a, 10) for a in alerts)))

    def _get(self, kp, name, min_conf=0.35):   # lowered from 0.45 — laptop cam
        p = kp.get(name)
        if p and p["confidence"] >= min_conf:
            return np.array([p["x"], p["y"]])
        return None

    def _analyze(self, kp, shape):
        alerts = []
        ls   = self._get(kp, "left_shoulder")
        rs   = self._get(kp, "right_shoulder")
        lh   = self._get(kp, "left_hip")
        rh   = self._get(kp, "right_hip")
        lk   = self._get(kp, "left_knee")
        rk   = self._get(kp, "right_knee")
        nose = self._get(kp, "nose")
        le   = self._get(kp, "left_ear")
        re_  = self._get(kp, "right_ear")

        if ls is None or rs is None:
            return {"position": "unknown", "alerts": [], "good_posture": True}

        shoulder_width = abs(ls[0] - rs[0]) + 1e-5

        # ── POSITION ──────────────────────────────────────────────────────
        position = "sitting"   # default — hips rarely visible on laptop cam
        if lh is not None and rh is not None:
            torso_v = abs(((lh[1]+rh[1])/2) - ((ls[1]+rs[1])/2))
            if lk is not None and rk is not None:
                leg_v = abs(((lk[1]+rk[1])/2) - ((lh[1]+rh[1])/2))
                position = "sitting" if leg_v < torso_v * 0.65 else "standing"

        # ── HEAD DOWN ─────────────────────────────────────────────────────
        # Nose must be clearly above shoulder midpoint
        if nose is not None:
            shoulder_mid_y = (ls[1] + rs[1]) / 2
            head_rise = shoulder_mid_y - nose[1]   # positive = nose above
            # Threshold: 15% of shoulder width (was 30% — too strict for front cam)
            if head_rise < shoulder_width * 0.15:
                alerts.append("head_down")

        # ── UNEVEN SHOULDERS ──────────────────────────────────────────────
        tilt = abs(ls[1] - rs[1]) / shoulder_width
        if tilt > 0.20:    # relaxed from 0.15
            alerts.append("uneven_shoulders")

        # ── FORWARD HUNCH ─────────────────────────────────────────────────
        # Best signal for front-facing cam: ears way off shoulder centre
        if le is not None and re_ is not None:
            ear_cx  = (le[0] + re_[0]) / 2
            sho_cx  = (ls[0] + rs[0]) / 2
            # Also check ear height vs shoulder — ears should be well above
            ear_cy  = (le[1] + re_[1]) / 2
            sho_cy  = (ls[1] + rs[1]) / 2
            ear_rise = (sho_cy - ear_cy) / shoulder_width  # positive = ears above
            if ear_rise < 0.10:   # ears are at or below shoulder level = hunching
                alerts.append("forward_hunch")
        elif lh is not None and rh is not None:
            # Fallback: shoulder-hip horizontal offset
            sho_cx = (ls[0] + rs[0]) / 2
            hip_cx = (lh[0] + rh[0]) / 2
            if abs(sho_cx - hip_cx) / shoulder_width > 0.22:
                alerts.append("forward_hunch")

        # ── SPINE LEAN ────────────────────────────────────────────────────
        if lh is not None and rh is not None:
            sho_cx = (ls[0] + rs[0]) / 2
            hip_cx = (lh[0] + rh[0]) / 2
            if abs(sho_cx - hip_cx) / shoulder_width > 0.20:
                alerts.append("spine_lean")

        return {"position": position, "alerts": alerts,
                "good_posture": len(alerts) == 0}
'''

# ─────────────────────────────────────────────────────────────
# 2. EMOTION ENGINE — better face detection, never blank, faster
# ─────────────────────────────────────────────────────────────
EMOTION = '''\
import cv2
import numpy as np
from collections import deque

class EmotionDetector:
    EMOTION_STATE = {
        "Anger": "negative", "Contempt": "negative", "Disgust": "negative",
        "Fear": "negative", "Sadness": "negative", "Happiness": "positive",
        "Surprise": "neutral", "Neutral": "neutral",
    }
    LABELS = ["Anger","Contempt","Disgust","Fear","Happiness","Neutral","Sadness","Surprise"]
    DISPLAY_NAME = {
        "Anger":"angry","Contempt":"contempt","Disgust":"disgust",
        "Fear":"fear","Happiness":"happy","Neutral":"neutral",
        "Sadness":"sad","Surprise":"surprise"
    }

    def __init__(self):
        from hsemotion_onnx.facial_emotions import HSEmotionRecognizer
        self.recognizer = None
        for model_name in ["enet_b2_8", "enet_b0_8_best_vgaf", "enet_b0_8_best_afew"]:
            try:
                print(f"[EmotionDetector] Trying {model_name}...")
                self.recognizer = HSEmotionRecognizer(model_name=model_name)
                self.MODEL_SIZE = self.recognizer.img_size
                print(f"[EmotionDetector] Loaded {model_name} ✓  img_size={self.MODEL_SIZE}")
                break
            except Exception as e:
                print(f"[EmotionDetector] {model_name} failed: {e}")
        if self.recognizer is None:
            raise RuntimeError("All emotion models failed to load.")

        self.face_cascade = cv2.CascadeClassifier(
            cv2.data.haarcascades + "haarcascade_frontalface_default.xml")
        self._face_histories = {}
        self._SMOOTH_WINDOW  = 4     # faster response
        self._MIN_CONF_DELTA = 0.06  # easier to break out of neutral
        self._last_result    = []    # cache — never return blank after first detection
        print("[EmotionDetector] Ready.")

    def detect(self, frame, debug=False):
        try:
            h, w = frame.shape[:2]
            gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
            gray = cv2.equalizeHist(gray)

            faces = self.face_cascade.detectMultiScale(
                gray,
                scaleFactor=1.05,    # finer steps
                minNeighbors=3,      # fewer required
                minSize=(30, 30),    # catch small faces
                flags=cv2.CASCADE_SCALE_IMAGE
            )

            if len(faces) == 0:
                return self._last_result   # return cached, never blank

            # Process largest face only
            faces = sorted(faces, key=lambda f: f[2]*f[3], reverse=True)
            emotions = []

            for i, (x, y, fw, fh) in enumerate(faces[:1]):
                pad_x = int(fw * 0.30)
                pad_y = int(fh * 0.35)
                x1 = max(0, x - pad_x);  y1 = max(0, y - pad_y)
                x2 = min(w, x+fw+pad_x); y2 = min(h, y+fh+pad_y)
                face_crop = frame[y1:y2, x1:x2]
                if face_crop.size == 0 or face_crop.shape[0] < 20:
                    continue

                sz = self.MODEL_SIZE
                face_rgb = cv2.cvtColor(
                    cv2.resize(face_crop, (sz, sz), interpolation=cv2.INTER_AREA),
                    cv2.COLOR_BGR2RGB)

                # CLAHE contrast boost
                lab = cv2.cvtColor(face_rgb, cv2.COLOR_RGB2LAB)
                lab[:,:,0] = cv2.createCLAHE(2.0,(4,4)).apply(lab[:,:,0])
                face_rgb = cv2.cvtColor(lab, cv2.COLOR_LAB2RGB)

                _, scores = self.recognizer.predict_emotions(face_rgb, logits=False)
                scores = np.array(scores, dtype=np.float32)

                if debug:
                    print("[DEBUG]", {k:round(float(v)*100,1) for k,v in zip(self.LABELS,scores)})

                if i not in self._face_histories:
                    self._face_histories[i] = deque(maxlen=self._SMOOTH_WINDOW)
                self._face_histories[i].append(scores)
                avg = np.mean(self._face_histories[i], axis=0)

                ni  = self.LABELS.index("Neutral")
                bi  = int(np.argmax(avg))
                if bi != ni and (avg[bi] - avg[ni]) < self._MIN_CONF_DELTA:
                    bi = ni
                lbl = self.LABELS[bi]

                emotions.append({
                    "bbox":          (int(x), int(y), int(fw), int(fh)),
                    "emotion":       self.DISPLAY_NAME.get(lbl, lbl.lower()),
                    "emotion_label": lbl,
                    "state":         self.EMOTION_STATE.get(lbl, "neutral"),
                    "valence":       round(float(self._valence(avg)), 3),
                    "confidence":    round(float(avg[bi])*100, 1),
                    "scores":        {k: round(float(v)*100,1) for k,v in zip(self.LABELS,avg)},
                })

            if emotions:
                self._last_result = emotions
            return self._last_result

        except Exception as e:
            print(f"[EmotionDetector] Error: {e}")
            return self._last_result

    def _valence(self, scores):
        w = {"Happiness":+1.0,"Surprise":+0.2,"Neutral":0.0,
             "Fear":-0.6,"Sadness":-0.8,"Disgust":-0.7,"Contempt":-0.6,"Anger":-0.9}
        return float(np.clip(sum(w.get(l,0)*float(s) for l,s in zip(self.LABELS,scores)),-1,1))
'''

# ─────────────────────────────────────────────────────────────
# 3. PATCH app.py  (timing + gate + camera_frame handler)
# ─────────────────────────────────────────────────────────────
def patch_app():
    path = os.path.join(BASE, 'app.py')
    with open(path) as f:
        c = f.read()

    changes = []

    # 3a. Faster suggestion timing: observation=15s, cooldown=20s
    old = "suggestion_engine = SuggestionEngine(mode=mode)"
    new = "suggestion_engine = SuggestionEngine(mode=mode, observation_period=15, cooldown=20)"
    if old in c:
        c = c.replace(old, new); changes.append("observation_period=15, cooldown=20")

    # 3b. Remove posture is not None gate
    old = "    if suggestion_engine and posture is not None:\n        suggestion = suggestion_engine.evaluate(posture_data, emotion_data)"
    new = "    if suggestion_engine:\n        suggestion = suggestion_engine.evaluate(posture_data, emotion_data)"
    if old in c:
        c = c.replace(old, new); changes.append("removed posture is not None gate")

    # 3c. Fix numpy int in posture_score emit
    old = "'posture_score': posture_data.get('score', 0) if posture_data else 0,"
    new = "'posture_score': int(posture_data.get('score', 0) or 0) if posture_data else 0,"
    if old in c:
        c = c.replace(old, new); changes.append("int() posture_score")

    # 3d. VisionEngine no longer takes camera_index
    old = "vision_engine = VisionEngine(camera_index=0, on_result=on_result)"
    new = "vision_engine = VisionEngine(on_result=on_result)"
    if old in c:
        c = c.replace(old, new); changes.append("removed camera_index arg")

    # 3e. Add camera_frame handler if missing
    if "camera_frame" not in c:
        handler = """\n@socketio.on('camera_frame')\ndef on_camera_frame(data):\n    if vision_engine and engines_ready:\n        vision_engine.push_frame(data.get('frame', ''))\n"""
        c = c.replace("@socketio.on('disconnect')", handler + "\n@socketio.on('disconnect')")
        changes.append("added camera_frame handler")

    with open(path, 'w') as f:
        f.write(c)
    return changes

# ─────────────────────────────────────────────────────────────
# WRITE FILES
# ─────────────────────────────────────────────────────────────
for fname, content in [('posture_engine.py', POSTURE), ('emotion_engine.py', EMOTION)]:
    path = os.path.join(BASE, fname)
    with open(path, 'w') as f:
        f.write(content)
    print(f"✓ wrote {fname}")

changes = patch_app()
for c in changes:
    print(f"✓ app.py: {c}")

# Copy vision_engine.py if the new one exists
ve_src = '/home/claude/vision_engine.py'
ve_dst = os.path.join(BASE, 'vision_engine.py')
if os.path.exists(ve_src):
    import shutil; shutil.copy(ve_src, ve_dst)
    print("✓ vision_engine.py copied")

print("\nDone! Run:  source venv/bin/activate && python3 app.py")
