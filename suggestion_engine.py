import time
import json
import os

XP_FILE = "data/xp_store.json"

class SuggestionEngine:

    # ── Suggestion templates (neutral base) ──────────────────────────────────
    SUGGESTIONS = {
        'head_down': {
            'title': 'Lift Your Head Up',
            'instruction': 'You have been looking down for a while. This strains your neck and affects your mood. Lift your head and look straight ahead.',
            'task': 'Hold your head upright and look forward for 10 seconds.',
            'category': 'posture', 'duration': 10,
        },
        'uneven_shoulders': {
            'title': 'Balance Your Shoulders',
            'instruction': 'Your shoulders have been uneven. This causes back and neck pain over time. Sit or stand with both shoulders level.',
            'task': 'Roll both shoulders back together and hold level for 10 seconds.',
            'category': 'posture', 'duration': 10,
        },
        'spine_lean': {
            'title': 'Straighten Your Spine',
            'instruction': 'You have been leaning to one side. This puts uneven pressure on your spine. Center your weight.',
            'task': 'Sit up straight, centered, and hold for 15 seconds.',
            'category': 'posture', 'duration': 15,
        },
        'forward_hunch': {
            'title': 'Open Up Your Chest',
            'instruction': 'You have been hunching forward. This compresses your lungs and adds stress. Pull your shoulders back.',
            'task': 'Pull shoulders back, lift your chest, and hold for 15 seconds.',
            'category': 'stretch', 'duration': 15,
        },
        'negative_emotion': {
            'title': 'Calm Your Mind',
            'instruction': 'You have been showing signs of stress. A slow deep breath resets your nervous system.',
            'task': 'Breathe in 4s → hold 4s → out 4s. Repeat 3 times.',
            'category': 'breathing', 'duration': 30,
        },
        'hunch_and_stress': {
            'title': 'Reset Body and Mind',
            'instruction': 'Hunching AND stress detected. Bad posture worsens your mood — fixing both together gives fast relief.',
            'task': 'Stand up, pull shoulders back, take 3 deep breaths, then sit back straight.',
            'category': 'stretch+breathing', 'duration': 30,
        },
        'head_down_and_sad': {
            'title': 'Look Up and Breathe',
            'instruction': 'Looking down and feeling low — these reinforce each other. Looking up physically shifts your mood.',
            'task': 'Lift your head, look up for 5 seconds, smile, then breathe deeply 3 times.',
            'category': 'posture+breathing', 'duration': 20,
        },
        'sitting_too_long': {
            'title': 'Stretch Break',
            'instruction': 'You have been sitting too long. Circulation slows down — get up and move.',
            'task': 'Stand up, stretch arms above head, hold 10 seconds, sit back down.',
            'category': 'stretch', 'duration': 10,
        },
        'good_posture_positive': {
            'title': 'You Are Doing Great!',
            'instruction': 'Excellent posture and positive mood. Keep this up — you are in the zone.',
            'task': None, 'category': 'reward', 'duration': 0,
        },
        'good_posture_neutral': {
            'title': 'Good Posture!',
            'instruction': 'Your posture looks good. Try smiling — even a small smile shifts your mood upward.',
            'task': None, 'category': 'reward', 'duration': 0,
        },
    }

    # ── Mode reframings ───────────────────────────────────────────────────────
    MOTIVATOR_OVERRIDES = {
        'head_down':       {'title': '⚡ Head Up Challenge!', 'instruction': 'Heads up, champion! Your neck deserves better. Beat your last streak.'},
        'uneven_shoulders': {'title': '⚡ Shoulder Power!', 'instruction': 'Level those shoulders — you are stronger than you think. Let\'s go!'},
        'spine_lean':      {'title': '⚡ Power Pose!', 'instruction': 'Champions stand centered. Straighten up and own your space.'},
        'forward_hunch':   {'title': '⚡ Chest Out!', 'instruction': 'Open that chest wide — show the room who\'s in charge. Dominate your posture.'},
        'negative_emotion': {'title': '⚡ Mental Reset!', 'instruction': 'Top performers control their breathing. Three power breaths — go!'},
        'sitting_too_long': {'title': '⚡ Move Break!', 'instruction': 'Elite athletes never sit too long. Stand up, stretch, and attack the next block.'},
    }

    SUPPORTER_OVERRIDES = {
        'head_down':       {'title': '💛 Gentle Reminder', 'instruction': 'Hey, no rush — whenever you\'re ready, try lifting your head a little. You\'re doing well.'},
        'uneven_shoulders': {'title': '💛 Small Adjustment', 'instruction': 'Just a small thing — your shoulders could use a little leveling when you get a chance.'},
        'spine_lean':      {'title': '💛 Check In', 'instruction': 'Take a moment to notice how you\'re sitting. No pressure — just a gentle nudge to center.'},
        'forward_hunch':   {'title': '💛 Take a Breath', 'instruction': 'You might be carrying some tension. Whenever you\'re ready, try rolling your shoulders back.'},
        'negative_emotion': {'title': '💛 You\'re Okay', 'instruction': 'Looks like you might be feeling a bit stressed. That\'s okay. A slow breath can help when you\'re ready.'},
        'sitting_too_long': {'title': '💛 Little Break?', 'instruction': 'You\'ve been sitting a while. A tiny stretch whenever you feel like it could feel really nice.'},
    }

    HAPA_STAGE_MAP = {
        'pending':   'motivation',
        'confirmed': 'intention',
        'in_action': 'action',
        'completed': 'maintenance',
    }

    def __init__(self, mode='supporter', observation_period=60, cooldown=60):
        self.mode = mode                          # 'motivator' | 'supporter' | 'tracker'
        self.observation_period = observation_period
        self.cooldown = cooldown

        self.current_suggestion = None
        self.suggestion_start_time = None
        self.last_suggestion_time = 0
        self.last_suggestion_key = None          # prevent consecutive repeats

        self.start_time = time.time()
        self.sitting_start_time = None
        self.posture_history = []
        self.emotion_history = []

        self.completed_count = 0
        self.total_suggestions = 0
        self.dismiss_counts = {}
        self.confirm_time = None                 # for intention-action gap

        # Focus mode state
        self.focus_active = False
        self.focus_task = None
        self.focus_end_time = None
        self.focus_posture_scores = []
        self.focus_emotion_valences = []

        # XP / Level
        self._xp_data = self._load_xp()

    # ── XP persistence ────────────────────────────────────────────────────────
    def _load_xp(self):
        os.makedirs('data', exist_ok=True)
        if os.path.exists(XP_FILE):
            with open(XP_FILE) as f:
                return json.load(f)
        return {'xp': 0, 'level': 1}

    def _save_xp(self):
        with open(XP_FILE, 'w') as f:
            json.dump(self._xp_data, f)

    def _add_xp(self, amount):
        self._xp_data['xp'] += amount
        while self._xp_data['xp'] >= self._xp_data['level'] * 200:
            self._xp_data['xp'] -= self._xp_data['level'] * 200
            self._xp_data['level'] += 1
        self._save_xp()

    def get_xp_info(self):
        return {
            'xp': self._xp_data['xp'],
            'level': self._xp_data['level'],
            'xp_to_next': self._xp_data['level'] * 200
        }

    # ── Focus mode ────────────────────────────────────────────────────────────
    def start_focus(self, task_name, duration_s):
        self.focus_active = True
        self.focus_task = task_name
        self.focus_end_time = time.time() + duration_s
        self.focus_posture_scores = []
        self.focus_emotion_valences = []
        print(f"[SuggestionEngine] Focus started: '{task_name}' for {duration_s}s")

    def end_focus(self):
        if not self.focus_active:
            return None
        self.focus_active = False
        p_scores = self.focus_posture_scores
        e_vals = self.focus_emotion_valences

        # Focus Score: 60% posture, 40% emotion
        posture_avg = (sum(p_scores) / len(p_scores)) if p_scores else 50
        # Emotion: map valence [-1,+1] → [0,100]
        emotion_avg = ((sum(e_vals) / len(e_vals)) + 1) / 2 * 100 if e_vals else 50

        focus_score = round(posture_avg * 0.6 + emotion_avg * 0.4)

        # Grade
        if focus_score >= 90:   grade = 'S'
        elif focus_score >= 80: grade = 'A'
        elif focus_score >= 70: grade = 'B'
        elif focus_score >= 60: grade = 'C'
        else:                   grade = 'D'

        xp_earned = {'S': 50, 'A': 35, 'B': 25, 'C': 15, 'D': 10}[grade]
        self._add_xp(xp_earned)

        return {
            'task': self.focus_task,
            'focus_score': focus_score,
            'posture_avg': round(posture_avg, 1),
            'emotion_avg': round(emotion_avg, 1),
            'grade': grade,
            'xp_earned': xp_earned,
            **self.get_xp_info()
        }

    def is_focus_expired(self):
        return self.focus_active and time.time() >= self.focus_end_time

    # ── Observation helpers ───────────────────────────────────────────────────
    def _observing(self):
        return time.time() - self.start_time < self.observation_period

    def get_progress(self):
        elapsed = time.time() - self.start_time
        return min(100, round((elapsed / self.observation_period) * 100))

    def record(self, posture_result, emotion_results):
        now = time.time()
        posture = posture_result.get('posture') if posture_result else None
        emotion = emotion_results[0] if emotion_results else None

        if posture:
            self.posture_history.append({
                'time': now,
                'alerts': posture.get('alerts', []),
                'position': posture.get('position', 'unknown'),
                'good': posture.get('good_posture', True),
                'score': posture.get('score', 100),
            })

        if emotion:
            self.emotion_history.append({
                'time': now,
                'emotion': emotion.get('emotion_label', 'Neutral'),
                'state': emotion.get('state', 'neutral'),
                'valence': emotion.get('valence', 0.0),
            })

        # Feed focus mode accumulators
        if self.focus_active:
            if posture:
                self.focus_posture_scores.append(posture.get('score', 100))
            if emotion:
                self.focus_emotion_valences.append(emotion.get('valence', 0.0))

    def _dominant_posture_alert(self):
        if not self.posture_history:
            return None
        alert_counts = {}
        for entry in self.posture_history:
            for alert in entry['alerts']:
                alert_counts[alert] = alert_counts.get(alert, 0) + 1
        return max(alert_counts, key=alert_counts.get) if alert_counts else None

    def _dominant_emotion_state(self):
        if not self.emotion_history:
            return 'neutral'
        state_counts = {}
        for entry in self.emotion_history:
            s = entry['state']
            state_counts[s] = state_counts.get(s, 0) + 1
        return max(state_counts, key=state_counts.get)

    def _mostly_sitting(self):
        if not self.posture_history:
            return False
        sitting = [e for e in self.posture_history if e['position'] == 'sitting']
        return len(sitting) > len(self.posture_history) * 0.7

    # ── Main evaluate loop ────────────────────────────────────────────────────
    def evaluate(self, posture_result, emotion_results):
        now = time.time()
        self.record(posture_result, emotion_results)

        # Tracker mode — silent, no cards
        if self.mode == 'tracker':
            return None

        # During focus — only fire critical posture alerts
        if self.focus_active:
            posture = posture_result.get('posture') if posture_result else None
            if posture and not posture.get('good_posture'):
                if now - self.last_suggestion_time > 120:  # max once per 2 min during focus
                    dominant = self._dominant_posture_alert()
                    if dominant in ('forward_hunch', 'head_down'):
                        sug = self._build_suggestion(dominant)
                        self.last_suggestion_time = now
                        return sug
            return None

        # Normal mode: observation window
        if self._observing():
            return None

        if self.current_suggestion:
            dur = self.current_suggestion['duration']
            if now - self.suggestion_start_time < dur + 5:
                return None

        if now - self.last_suggestion_time < self.cooldown:
            return None

        dominant_alert = self._dominant_posture_alert()
        dominant_emotion = self._dominant_emotion_state()

        # Priority logic
        suggestion_key = None
        if dominant_alert in ('forward_hunch', 'spine_lean') and dominant_emotion == 'negative':
            suggestion_key = 'hunch_and_stress'
        elif dominant_alert == 'head_down' and dominant_emotion == 'negative':
            suggestion_key = 'head_down_and_sad'

        if not suggestion_key:
            for alert in ['forward_hunch', 'spine_lean', 'head_down', 'uneven_shoulders']:
                if dominant_alert == alert:
                    suggestion_key = alert
                    break

        if not suggestion_key and dominant_emotion == 'negative':
            suggestion_key = 'negative_emotion'

        if not suggestion_key and self._mostly_sitting():
            suggestion_key = 'sitting_too_long'

        if not suggestion_key:
            suggestion_key = 'good_posture_positive' if dominant_emotion == 'positive' else 'good_posture_neutral'

        # Prevent same suggestion twice in a row
        if suggestion_key == self.last_suggestion_key and suggestion_key not in ('good_posture_positive', 'good_posture_neutral'):
            # Pick next priority instead
            fallback = ['forward_hunch', 'head_down', 'spine_lean', 'uneven_shoulders', 'negative_emotion', 'sitting_too_long']
            for fb in fallback:
                if fb != suggestion_key:
                    suggestion_key = fb
                    break

        sug = self._build_suggestion(suggestion_key)
        self.current_suggestion = sug
        self.suggestion_start_time = now
        self.last_suggestion_time = now
        self.last_suggestion_key = suggestion_key
        self.total_suggestions += 1

        # Reset observation window
        self.posture_history = []
        self.emotion_history = []
        self.start_time = now

        return sug

    def _build_suggestion(self, key):
        base = dict(self.SUGGESTIONS[key])
        # Apply mode overrides for instruction tone
        if self.mode == 'motivator' and key in self.MOTIVATOR_OVERRIDES:
            base.update(self.MOTIVATOR_OVERRIDES[key])
        elif self.mode == 'supporter' and key in self.SUPPORTER_OVERRIDES:
            base.update(self.SUPPORTER_OVERRIDES[key])

        base['key'] = key
        base['timestamp'] = time.time()
        base['status'] = 'pending'
        base['hapa_stage'] = 'motivation'
        return base

    # ── Task lifecycle ────────────────────────────────────────────────────────
    def confirm_task(self):
        if self.current_suggestion:
            self.current_suggestion['status'] = 'confirmed'
            self.current_suggestion['hapa_stage'] = 'intention'
            self.confirm_time = time.time()
            return self.current_suggestion
        return None

    def complete_task(self):
        if self.current_suggestion and self.current_suggestion['status'] == 'confirmed':
            self.current_suggestion['status'] = 'completed'
            self.current_suggestion['hapa_stage'] = 'maintenance'
            self.completed_count += 1
            gap = round(time.time() - self.confirm_time, 1) if self.confirm_time else None
            completed = dict(self.current_suggestion)
            completed['intention_action_gap_s'] = gap
            self.current_suggestion = None
            self.confirm_time = None
            self._add_xp(10)
            return completed
        return None

    def dismiss_task(self):
        if self.current_suggestion:
            key = self.current_suggestion.get('key', 'unknown')
            self.dismiss_counts[key] = self.dismiss_counts.get(key, 0) + 1
            self.current_suggestion = None

    def get_score(self):
        if self.total_suggestions == 0:
            return 0
        return round((self.completed_count / self.total_suggestions) * 100)

    def get_stats(self):
        return {
            'completed': self.completed_count,
            'total': self.total_suggestions,
            'score_pct': self.get_score(),
            'dismissed': self.dismiss_counts,
            'mode': self.mode,
            'xp': self.get_xp_info(),
        }
