"""Public UI checks confined to the task-owned shared emulator."""
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import xml.etree.ElementTree as ET

OUT = Path(__file__).resolve().parent
import os
ADB = ['adb', '-s', os.environ['QURAN_CI_SERIAL']]
OUT = Path('.ci/out/device')
OUT.mkdir(parents=True, exist_ok=True)
PACKAGE = 'com.xfocus.quranly.local'

def adb(*args, timeout=35):
    return subprocess.check_output(ADB + list(map(str, args)), text=True, timeout=timeout)

def sh(*args, timeout=35):
    return adb('shell', *args, timeout=timeout)

def label(node):
    return node.get('content-desc') or node.get('text') or ''

def dump(name=None):
    sh('uiautomator', 'dump', '/sdcard/qa-issue6-window.xml')
    raw = sh('cat', '/sdcard/qa-issue6-window.xml')
    if name:
        (OUT / (name + '.xml')).write_text(raw)
    return ET.fromstring(raw)

def shot(name):
    (OUT / (name + '.png')).write_bytes(subprocess.check_output(ADB + ['exec-out', 'screencap', '-p']))

def find(query, root=None, exact=False):
    if root is None:
        root = dump()
    return next((n for n in root.iter('node') if label(n) == query or
                 (not exact and query in label(n))), None)

def wait(query, exact=False, timeout=15):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        node = find(query, exact=exact)
        if node is not None:
            return node
        time.sleep(.25)
    raise AssertionError('UI did not settle to label: ' + query)

def dimensions():
    value = re.findall(r'(\d+)x(\d+)', sh('wm', 'size'))[-1]
    width, height = map(int, value)
    if sh('settings', 'get', 'system', 'user_rotation').strip() in ('1', '3'):
        width, height = height, width
    return width, height

def swipe(up=True):
    width, height = dimensions()
    x, low, high = width // 2, int(height * .80), int(height * .28)
    sh('input', 'swipe', x, low if up else high, x, high if up else low, 160)
    time.sleep(.12)

def bounds(node):
    return tuple(map(int, re.findall(r'\d+', node.get('bounds'))))

def tap(node):
    x1, y1, x2, y2 = bounds(node)
    assert x2 > x1 and y2 > y1, node.attrib
    assert node.get('enabled') == 'true', node.attrib
    sh('input', 'tap', (x1 + x2) // 2, (y1 + y2) // 2)
    time.sleep(.45)

def seek(query, up=True, exact=False, limit=45):
    for _ in range(limit + 1):
        root = dump()
        node = find(query, root, exact)
        if node is not None:
            return node
        swipe(up)
    raise AssertionError('UI label not reachable: ' + query)

def click(query, up=True, exact=False, limit=45):
    tap(seek(query, up, exact, limit))

def start():
    assert int(sh('getprop', 'ro.build.version.sdk').strip()) >= 35
    sh('am', 'start', '-W', '-n', PACKAGE + '/.MainActivity')
    time.sleep(.8)

def top():
    seek('الانتقال إلى آية', up=False, exact=True)

def mode(name):
    top()
    click(name, exact=True)
    time.sleep(.5)

def field(value, index=0):
    fields = [n for n in dump().iter('node') if n.get('class') == 'android.widget.EditText']
    tap(fields[index])
    sh('input', 'keycombination', 'KEYCODE_CTRL_LEFT', 'KEYCODE_A')
    sh('input', 'keyevent', 'KEYCODE_DEL')
    sh('input', 'text', str(value))

def jump(surah, ayah):
    top()
    click('الانتقال إلى آية', exact=True)
    field(surah)
    field(ayah, 1)
    sh('input', 'keyevent', 'KEYCODE_BACK')
    click('فتح الآية', exact=True)

def number(kind, value, valid=True):
    assert kind in ('صفحة', 'جزء')
    top()
    click('الانتقال إلى ' + kind, exact=True)
    field(value)
    sh('input', 'keyevent', 'KEYCODE_BACK')
    click('فتح ' + ('الصفحة' if kind == 'صفحة' else 'الجزء'), exact=True)
    if not valid:
        expected = 'اختر صفحة من 1 إلى 604.' if kind == 'صفحة' else 'اختر جزءاً من 1 إلى 30.'
        assert find(expected) is not None, expected
        click('إلغاء', exact=True)

def page(number, selected=None, name=None):
    top()
    seek(f'الصفحة {number} من 604')
    if selected:
        seek('الآية المحددة ' + selected)
    if name:
        dump(name)
        shot(name)

def ayah(reference):
    return seek('الآية ' + reference + ' ')

def actions(reference):
    tap(ayah(reference))
    wait('نسخ الآية مع المرجع', exact=True)

def copy(reference, expected, name):
    actions(reference)
    click('نسخ الآية مع المرجع', exact=True)
    sh('am', 'start', '-W', '-n', 'qa.quranly.probe/qa.PasteActivity')
    click('Read Android clipboard', exact=True)
    root = dump(name)
    fields = [n for n in root.iter('node') if n.get('class') == 'android.widget.EditText']
    assert len(fields) == 1 and fields[0].get('text') == expected, fields[0].attrib
    shot(name)
    sh('input', 'keyevent', 'KEYCODE_BACK')
    time.sleep(.4)
    return {'key': reference, 'unicode_sha256': hashlib.sha256(expected.encode()).hexdigest(),
            'characters': len(expected), 'exact_android_clipboard_match': True}

def save(name, value):
    (OUT / (name + '.json')).write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
