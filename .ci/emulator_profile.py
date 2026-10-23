"""Retained reader observation viewport, shared by setup and device validation.

The reduced 720x1280/320 profile clipped the reader's bottom navigation.
Keep the original 1220x2712/480 inputs; do not resize comparison captures.
"""

LCD = {'hw.lcd.width': '1220', 'hw.lcd.height': '2712', 'hw.lcd.density': '480'}
PHYSICAL_SIZE = f"Physical size: {LCD['hw.lcd.width']}x{LCD['hw.lcd.height']}"
PHYSICAL_DENSITY = f"Physical density: {LCD['hw.lcd.density']}"
