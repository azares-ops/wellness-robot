import numpy as np
import json
import csv
import os
from collections import deque

class AnalysisEngine:
    """
    Novel research contribution:
    - Cross-correlation between posture score and emotion valence time series
    - P→E lag: does posture drop predict emotion drop (and by how many minutes)?
    - Posture degradation curve: personal decay rate within a session
    - Session summary statistics for paper
    """

    def __init__(self):
        self._posture_ts = deque(maxlen=500)   # (elapsed_s, score)
        self._emotion_ts = deque(maxlen=500)   # (elapsed_s, valence)
        self._pe_lag = None          # seconds, positive = posture leads emotion
        self._decay_rate = None      # posture points lost per minute

    def ingest(self, elapsed_s, posture_score, emotion_valence):
        """Feed every 10-second log tick."""
        self._posture_ts.append((elapsed_s, posture_score))
        self._emotion_ts.append((elapsed_s, emotion_valence))

        # Recompute lag when enough data
        if len(self._posture_ts) >= 12:   # >= 2 minutes of data
            self._compute_lag()
            self._compute_decay()

    def _compute_lag(self):
        """
        Cross-correlate posture score and emotion valence.
        Returns lag in seconds. Positive = posture changes BEFORE emotion.
        """
        try:
            p_vals = np.array([v for _, v in self._posture_ts])
            e_vals = np.array([v for _, v in self._emotion_ts])
            t_vals = np.array([t for t, _ in self._posture_ts])

            # Normalise both series
            def norm(x):
                s = x.std()
                return (x - x.mean()) / s if s > 1e-6 else x - x.mean()

            p_n = norm(p_vals)
            e_n = norm(e_vals)

            # Full cross-correlation
            corr = np.correlate(p_n, e_n, mode='full')
            lags = np.arange(-(len(p_n) - 1), len(p_n))

            # Restrict search to ±5 minutes lag
            sample_interval = 10  # seconds per tick
            max_lag_samples = int(300 / sample_interval)
            centre = len(p_n) - 1
            lo = centre - max_lag_samples
            hi = centre + max_lag_samples + 1
            corr_window = corr[lo:hi]
            lags_window = lags[lo:hi]

            best = int(np.argmax(corr_window))
            self._pe_lag = int(lags_window[best]) * sample_interval  # convert to seconds
        except Exception as e:
            print(f"[Analysis] Lag computation error: {e}")

    def _compute_decay(self):
        """
        Fit a linear regression to posture score over time.
        Negative slope = score is degrading; reports points-per-minute.
        """
        try:
            times = np.array([t for t, _ in self._posture_ts])
            scores = np.array([v for _, v in self._posture_ts])
            if times.ptp() < 60:
                return
            # Linear fit
            coeffs = np.polyfit(times / 60.0, scores, 1)  # per minute
            self._decay_rate = round(float(coeffs[0]), 2)  # negative = degrading
        except Exception as e:
            print(f"[Analysis] Decay computation error: {e}")

    def get_pe_lag(self):
        """Returns P→E lag in seconds, or None if not enough data."""
        return self._pe_lag

    def get_decay_rate(self):
        """Returns posture score change per minute (negative = degrading)."""
        return self._decay_rate

    def get_summary(self):
        """Returns a dict of all computed metrics for /stats endpoint and paper."""
        p_vals = [v for _, v in self._posture_ts]
        e_vals = [v for _, v in self._emotion_ts]

        return {
            'pe_lag_s': self._pe_lag,
            'pe_lag_min': round(self._pe_lag / 60, 2) if self._pe_lag is not None else None,
            'posture_decay_per_min': self._decay_rate,
            'mean_posture_score': round(float(np.mean(p_vals)), 1) if p_vals else None,
            'std_posture_score': round(float(np.std(p_vals)), 1) if p_vals else None,
            'mean_emotion_valence': round(float(np.mean(e_vals)), 3) if e_vals else None,
            'std_emotion_valence': round(float(np.std(e_vals)), 3) if e_vals else None,
            'samples': len(p_vals),
        }

    @staticmethod
    def load_session_csv(csv_path):
        """Load a session timeseries CSV and return lists for re-analysis."""
        rows = []
        with open(csv_path, newline='') as f:
            for row in csv.DictReader(f):
                rows.append({
                    'elapsed_s': float(row['elapsed_s']),
                    'posture_score': float(row['posture_score']),
                    'emotion_valence': float(row['emotion_valence']),
                })
        return rows
