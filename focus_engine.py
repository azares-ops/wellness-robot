"""
focus_engine.py
───────────────
Self-directed focus sessions with wellness scoring.

User picks:
  • Their own task name (optional text)
  • Timer preset: sprint (25m) / deep (45m) / long (90m) / custom

System runs silently:
  • Records posture score + emotion valence every frame
  • No suggestion interruptions (only critical posture alerts pass through)
  • Touch 2 = end session early and still get scored

End of session:
  • Focus Score = posture 60% + emotion 40%
  • Grade S / A / B / C / D
  • XP awarded, level system, persisted to file
"""

import time
import json
import os


class FocusEngine:

    PRESETS = {
        'sprint': 25 * 60,
        'deep':   45 * 60,
        'long':   90 * 60,
    }

    GRADES = [
        (90, 100, 'S', '🏆 Perfect Focus',
         'Exceptional. Posture and mood held strong the entire session.', 100),
        (75,  89, 'A', '⭐ Deep Focus',
         'Great session. Minor dips but you stayed on track.', 75),
        (60,  74, 'B', '✅ Solid Session',
         'Good effort. A few posture or mood dips but overall productive.', 50),
        (40,  59, 'C', '📈 Keep Building',
         'You showed up. Next session aim to hold posture in the first half.', 25),
        (0,   39, 'D', '🌱 Rough Session',
         "That one was hard. Rest if you need it — even attempting counts.", 10),
    ]

    XP_PER_LEVEL = 200
    XP_FILE      = 'focus_xp.json'

    def __init__(self):
        self.active            = False
        self.task_name         = None
        self.duration_seconds  = None
        self.start_time        = None
        self.end_time          = None

        self.posture_samples   = []
        self.emotion_samples   = []
        self.interruptions     = []

        self.total_xp          = self._load_xp()
        self.sessions_done     = 0
        print(f"[FocusEngine] Ready. Total XP: {self.total_xp}  Level: {self.get_level()}")

    # ── XP persistence ───────────────────────────────────────────────────

    def _load_xp(self) -> int:
        try:
            with open(self.XP_FILE) as f:
                return json.load(f).get('total_xp', 0)
        except Exception:
            return 0

    def _save_xp(self):
        try:
            with open(self.XP_FILE, 'w') as f:
                json.dump({'total_xp': self.total_xp}, f)
        except Exception as e:
            print(f"[FocusEngine] XP save error: {e}")

    def get_level(self) -> int:
        return (self.total_xp // self.XP_PER_LEVEL) + 1

    def get_xp_in_level(self) -> int:
        return self.total_xp % self.XP_PER_LEVEL

    def get_xp_progress_pct(self) -> int:
        return round(self.get_xp_in_level() / self.XP_PER_LEVEL * 100)

    # ── Session control ──────────────────────────────────────────────────

    def start(self, task_name: str = None, preset: str = 'sprint',
              custom_seconds: int = None) -> dict:
        self.active           = True
        self.task_name        = (task_name or 'Focus Session').strip() or 'Focus Session'
        self.start_time       = time.time()
        self.posture_samples  = []
        self.emotion_samples  = []
        self.interruptions    = []

        if preset == 'custom' and custom_seconds and int(custom_seconds) > 0:
            self.duration_seconds = int(custom_seconds)
        else:
            self.duration_seconds = self.PRESETS.get(preset, self.PRESETS['sprint'])

        self.end_time = self.start_time + self.duration_seconds
        print(f"[FocusEngine] Started '{self.task_name}' — {self.duration_seconds//60} min")
        return self.get_status()

    def end_early(self) -> dict | None:
        """Touch 2 during focus — end session and score it."""
        if not self.active:
            return None
        return self._finish()

    def tick(self, posture_result, emotion_results) -> dict | None:
        """
        Called every frame during focus session.
        Returns None normally, returns result dict when timer expires.
        """
        if not self.active:
            return None

        # Record posture score
        if posture_result:
            p = posture_result.get('posture')
            if p:
                self.posture_samples.append(p.get('score', 100))

        # Record emotion valence
        if emotion_results:
            e = emotion_results[0]
            valence = {'positive': 1, 'neutral': 0, 'negative': -1}.get(
                e.get('state', 'neutral'), 0)
            self.emotion_samples.append(valence)

        # Check timer
        if time.time() >= self.end_time:
            return self._finish()

        return None

    def log_interruption(self, suggestion_key: str):
        """Called when a wellness suggestion fires during focus."""
        self.interruptions.append({
            'time_elapsed': round(time.time() - self.start_time),
            'type':         suggestion_key,
        })

    def is_active(self) -> bool:
        return self.active

    # ── Internal ─────────────────────────────────────────────────────────

    def _finish(self) -> dict:
        self.active        = False
        self.sessions_done += 1

        actual_sec  = round(time.time() - self.start_time)
        score       = self._compute_score()
        grade_info  = self._get_grade(score)

        self.total_xp += grade_info['xp']
        self._save_xp()

        result = {
            'task_name':       self.task_name,
            'planned_minutes': self.duration_seconds // 60,
            'actual_minutes':  actual_sec // 60,
            'actual_seconds':  actual_sec,
            'focus_score':     score,
            'grade':           grade_info['grade'],
            'reward_title':    grade_info['title'],
            'reward_message':  grade_info['message'],
            'xp_earned':       grade_info['xp'],
            'total_xp':        self.total_xp,
            'level':           self.get_level(),
            'xp_progress':     self.get_xp_progress_pct(),
            'xp_in_level':     self.get_xp_in_level(),
            'avg_posture':     round(sum(self.posture_samples) / len(self.posture_samples), 1)
                               if self.posture_samples else 0,
            'avg_emotion':     round(sum(self.emotion_samples) / len(self.emotion_samples), 2)
                               if self.emotion_samples else 0,
            'interruptions':   len(self.interruptions),
            'interruption_log':self.interruptions,
            'sessions_done':   self.sessions_done,
        }
        print(f"[FocusEngine] Done. Score:{score} Grade:{grade_info['grade']} "
              f"XP+{grade_info['xp']} Total:{self.total_xp} Level:{self.get_level()}")
        return result

    def _compute_score(self) -> int:
        posture_avg = (sum(self.posture_samples) / len(self.posture_samples)
                       if self.posture_samples else 50)
        emotion_avg = (((sum(self.emotion_samples) / len(self.emotion_samples)) + 1) / 2 * 100
                       if self.emotion_samples else 50)
        return round(posture_avg * 0.6 + emotion_avg * 0.4)

    def _get_grade(self, score: int) -> dict:
        for lo, hi, grade, title, msg, xp in self.GRADES:
            if lo <= score <= hi:
                return {'grade': grade, 'title': title, 'message': msg, 'xp': xp}
        return {'grade': 'D', 'title': '🌱 Rough Session',
                'message': 'Even attempting counts.', 'xp': 10}

    # ── Status ───────────────────────────────────────────────────────────

    def get_status(self) -> dict:
        if not self.active:
            return {
                'active': False,
                'level':      self.get_level(),
                'total_xp':   self.total_xp,
                'xp_progress':self.get_xp_progress_pct(),
            }
        elapsed   = time.time() - self.start_time
        remaining = max(0, self.end_time - time.time())
        pct       = min(100, round(elapsed / self.duration_seconds * 100))
        return {
            'active':            True,
            'task_name':         self.task_name,
            'elapsed_seconds':   round(elapsed),
            'remaining_seconds': round(remaining),
            'elapsed_pct':       pct,
            'planned_minutes':   self.duration_seconds // 60,
            'level':             self.get_level(),
            'total_xp':          self.total_xp,
            'xp_progress':       self.get_xp_progress_pct(),
        }
