import csv
import json
import os
import time
from datetime import datetime
from collections import deque
import numpy as np

DATA_DIR = "data"

class DataLogger:
    """
    Logs posture scores, emotion valence, suggestion events, and touch interactions.
    Produces per-session CSV files and a summary JSON for research analysis.
    """

    def __init__(self, user_id="user1", mode="supporter"):
        os.makedirs(DATA_DIR, exist_ok=True)
        self.user_id = user_id
        self.mode = mode

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        self.session_id = f"{user_id}_{ts}"
        self.csv_path = os.path.join(DATA_DIR, f"{self.session_id}_timeseries.csv")
        self.events_path = os.path.join(DATA_DIR, f"{self.session_id}_events.csv")
        self.summary_path = os.path.join(DATA_DIR, f"{self.session_id}_summary.json")

        # Init CSVs
        with open(self.csv_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['timestamp', 'elapsed_s', 'posture_score', 'emotion_valence',
                        'posture_alert', 'emotion_label', 'position'])

        with open(self.events_path, 'w', newline='') as f:
            w = csv.writer(f)
            w.writerow(['timestamp', 'elapsed_s', 'event_type', 'suggestion_key',
                        'confirm_ts', 'complete_ts', 'intention_action_gap_s', 'abandoned'])

        self.session_start = time.time()
        self._ts_buffer = []     # For cross-correlation analysis
        self._confirm_ts = {}    # suggestion_key → confirm timestamp

        print(f"[DataLogger] Session: {self.session_id}")

    def log_frame(self, posture_result, emotion_results):
        """Call every 10 seconds with latest posture + emotion data."""
        now = time.time()
        elapsed = round(now - self.session_start, 1)

        posture = posture_result.get('posture') if posture_result else None
        emotion = emotion_results[0] if emotion_results else None

        posture_score = posture.get('score', 0) if posture else 0
        posture_alert = ','.join(posture.get('alerts', [])) if posture else ''
        position = posture.get('position', '') if posture else ''
        valence = emotion.get('valence', 0.0) if emotion else 0.0
        emotion_label = emotion.get('emotion_label', 'Neutral') if emotion else 'Neutral'

        with open(self.csv_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, posture_score,
                round(valence, 3), posture_alert, emotion_label, position
            ])

        self._ts_buffer.append({
            'elapsed': elapsed,
            'posture_score': posture_score,
            'valence': valence
        })

    def log_suggestion(self, suggestion_key):
        now = time.time()
        elapsed = round(now - self.session_start, 1)
        with open(self.events_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, 'suggestion', suggestion_key,
                '', '', '', ''
            ])

    def log_confirm(self, suggestion_key):
        now = time.time()
        self._confirm_ts[suggestion_key] = now
        elapsed = round(now - self.session_start, 1)
        with open(self.events_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, 'confirm', suggestion_key,
                round(now, 2), '', '', ''
            ])

    def log_complete(self, suggestion_key):
        now = time.time()
        elapsed = round(now - self.session_start, 1)
        gap = ''
        if suggestion_key in self._confirm_ts:
            gap = round(now - self._confirm_ts.pop(suggestion_key), 1)
        with open(self.events_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, 'complete', suggestion_key,
                '', round(now, 2), gap, 'false'
            ])
        return gap  # intention-action gap in seconds

    def log_abandon(self, suggestion_key):
        now = time.time()
        elapsed = round(now - self.session_start, 1)
        gap = ''
        if suggestion_key in self._confirm_ts:
            gap = round(now - self._confirm_ts.pop(suggestion_key), 1)
        with open(self.events_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, 'abandon', suggestion_key,
                '', '', gap, 'true'
            ])

    def log_dismiss(self, suggestion_key):
        now = time.time()
        elapsed = round(now - self.session_start, 1)
        with open(self.events_path, 'a', newline='') as f:
            csv.writer(f).writerow([
                round(now, 2), elapsed, 'dismiss', suggestion_key,
                '', '', '', 'true'
            ])

    def finalize(self, extra_stats=None):
        """Write summary JSON at end of session."""
        summary = {
            'session_id': self.session_id,
            'user_id': self.user_id,
            'mode': self.mode,
            'session_start': self.session_start,
            'session_end': time.time(),
            'duration_s': round(time.time() - self.session_start, 1),
            'csv': self.csv_path,
            'events': self.events_path,
        }
        if extra_stats:
            summary.update(extra_stats)
        with open(self.summary_path, 'w') as f:
            json.dump(summary, f, indent=2)
        print(f"[DataLogger] Session saved: {self.summary_path}")
        return summary
