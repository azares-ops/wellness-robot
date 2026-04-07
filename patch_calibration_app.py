"""Run on Pi: python3 /home/claude/patch_app_calibration.py"""

path = '/home/who/grok_robo/app.py'
with open(path) as f:
    c = f.read()

# 1. updatePostureChip — handle calibrating state
OLD_CHIP = """function updatePostureChip(posture) {
  const chip = document.getElementById('chip-posture');
  if (!posture) return;
  if (posture.good_posture) {
    chip.textContent = '✓ ' + (posture.position || 'Good posture');
    chip.className = 'info-chip good';
  } else {
    const labels = {
      head_down: '↓ Head down', uneven_shoulders: '⟷ Uneven shoulders',
      spine_lean: '↗ Spine lean', forward_hunch: '⤵ Hunching'
    };
    const alert = posture.alerts && posture.alerts[0];
    chip.textContent = labels[alert] || '⚠ Bad posture';
    chip.className = 'info-chip alert';
  }
}"""

NEW_CHIP = """function updatePostureChip(posture) {
  const chip = document.getElementById('chip-posture');
  if (!posture) return;
  if (posture.calibrating) {
    chip.textContent = '🎯 Calibrating... ' + (posture.cal_pct || 0) + '%';
    chip.className = 'info-chip';
    return;
  }
  if (posture.good_posture) {
    chip.textContent = '✓ ' + (posture.position || 'Good posture');
    chip.className = 'info-chip good';
  } else {
    const labels = {
      head_down: '↓ Head down', uneven_shoulders: '⟷ Uneven shoulders',
      spine_lean: '↗ Spine lean', forward_hunch: '⤵ Hunching'
    };
    const alert = posture.alerts && posture.alerts[0];
    chip.textContent = labels[alert] || '⚠ Bad posture';
    chip.className = 'info-chip alert';
  }
}"""

if OLD_CHIP in c:
    c = c.replace(OLD_CHIP, NEW_CHIP)
    print("✓ updatePostureChip updated with calibration state")
else:
    print("✗ updatePostureChip not found — check manually")

with open(path, 'w') as f:
    f.write(c)

print("Done.")
