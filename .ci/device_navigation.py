import time
from device_ui import *

def capture(name):
    dump(name)
    shot(name)


def entry():
    if find('السور') is None:
        click('العودة إلى اختيار القراءة', up=False, exact=True)
    wait('السور')


def search(value):
    field(value)
    time.sleep(.3)


def chapter(number, capture_prefix=None, query=None):
    entry()
    click('السور')
    wait('Chapter', exact=True)
    if capture_prefix:
        capture(capture_prefix + '-unfiltered')
    search(query if query is not None else str(number))
    if capture_prefix:
        capture(capture_prefix + '-filtered-keyboard')
    sh('input', 'keyevent', 'KEYCODE_BACK')
    root = dump()
    target = next((n for n in root.iter('node')
                   if label(n).endswith('السورة ' + str(number))), None)
    assert target is not None, [label(n) for n in root.iter('node') if label(n)]
    if capture_prefix:
        capture(capture_prefix + '-filtered')
    tap(target)
    wait('Start Reading Quran', exact=True)


def verse(number, capture_prefix=None):
    entry()
    click('الانتقال إلى آية')
    wait('Select Verse', exact=True)
    if capture_prefix:
        capture(capture_prefix + '-grid')
    search(number)
    if capture_prefix:
        capture(capture_prefix + '-filtered-keyboard')
    sh('input', 'keyevent', 'KEYCODE_BACK')
    if capture_prefix:
        capture(capture_prefix + '-filtered')
    click('Verse ' + str(number), exact=True)
    wait('Start Reading Quran', exact=True)


def begin(surah, ayah):
    click('Start Reading Quran', exact=True)
    wait(f'الآية {surah}:{ayah} ')


def jump(surah, ayah):
    chapter(surah)
    verse(ayah)
    begin(surah, ayah)
