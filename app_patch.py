# This shows the KEY changes needed in app.py
# Run this script on the Pi to patch the file in place

import re

with open('/home/who/grok_robo/app.py', 'r') as f:
    content = f.read()

# Fix 1: VisionEngine no longer takes camera_index
content = content.replace(
    "vision_engine = VisionEngine(camera_index=0, on_result=on_result)",
    "vision_engine = VisionEngine(on_result=on_result)"
)

# Fix 2: observation_period=20, cooldown=30 so suggestions appear faster
content = content.replace(
    "suggestion_engine = SuggestionEngine(mode=mode)",
    "suggestion_engine = SuggestionEngine(mode=mode, observation_period=20, cooldown=30)"
)

# Fix 3: Remove the "posture is not None" gate — evaluate even if posture is None
# so emotion-only suggestions can fire
content = content.replace(
    "    # ── Evaluate for suggestions ──\n    if suggestion_engine and posture is not None:\n        suggestion = suggestion_engine.evaluate(posture_data, emotion_data)",
    "    # ── Evaluate for suggestions ──\n    if suggestion_engine:\n        suggestion = suggestion_engine.evaluate(posture_data, emotion_data)"
)

# Fix 4: Fix numpy int32 serialization — wrap posture_score
content = content.replace(
    "'posture_score': posture_data.get('score', 0) if posture_data else 0,",
    "'posture_score': int(posture_data.get('score', 0)) if posture_data else 0,"
)

with open('/home/who/grok_robo/app.py', 'w') as f:
    f.write(content)

print("app.py patched successfully")

# Verify fixes
for fix, text in [
    ("VisionEngine no camera_index", "VisionEngine(on_result=on_result)"),
    ("observation_period=20", "observation_period=20"),
    ("evaluate gate removed", "if suggestion_engine:\n        suggestion = suggestion_engine.evaluate"),
    ("int() posture_score", "int(posture_data.get('score', 0))"),
]:
    found = text in content
    print(f"  {'✓' if found else '✗'} {fix}")
