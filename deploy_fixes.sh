#!/bin/bash
set -e
cd /home/who/grok_robo

echo "=== Deploying fixed files ==="

# 1. posture_engine.py
cp /home/claude/posture_engine.py posture_engine.py
echo "✓ posture_engine.py"

# 2. emotion_engine.py
cp /home/claude/emotion_engine.py emotion_engine.py
echo "✓ emotion_engine.py"

# 3. vision_engine.py
cp /home/claude/vision_engine.py vision_engine.py
echo "✓ vision_engine.py"

# 4. Patch app.py in place
python3 /home/claude/app_patch.py

# 5. Add camera_frame SocketIO handler if missing
python3 - << 'EOF'
with open('app.py', 'r') as f:
    content = f.read()

if 'camera_frame' not in content:
    handler = """
@socketio.on('camera_frame')
def on_camera_frame(data):
    if vision_engine and engines_ready:
        vision_engine.push_frame(data.get('frame', ''))
"""
    # Insert before the disconnect handler
    content = content.replace(
        "@socketio.on('disconnect')",
        handler + "\n@socketio.on('disconnect')"
    )
    with open('app.py', 'w') as f:
        f.write(content)
    print("✓ camera_frame handler added to app.py")
else:
    print("✓ camera_frame handler already present")
EOF

echo ""
echo "=== All fixes deployed. Restart with: ==="
echo "  source venv/bin/activate && python3 app.py"
