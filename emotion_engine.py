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
