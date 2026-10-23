"""Real TalkBack keyboard navigation on the job-scoped hosted emulator."""
import gzip
import json
import os
import re
import time
import traceback
import device_ui as d
OUT = d.OUT
initial={k:d.sh('settings','get','secure',k).strip() for k in ['enabled_accessibility_services','accessibility_enabled']}
states=0;focuses=[];checks=[];started=time.monotonic()
archive=gzip.open(OUT/'talkback-states.jsonl.gz','wt',encoding='utf-8')
def probe():
 global states
 raw=d.sh('am','instrument','-w','qa.quranly.probe/qa.Probe')
 state=json.JSONDecoder().raw_decode(raw[raw.index('['):])[0][0]
 required={'label','hint','class','bounds','a11yFocused','focusable','selected','enabled','clickable','actions'}
 assert state['nodes'] and all(required<=n.keys() for n in state['nodes'])
 archive.write(json.dumps(state,ensure_ascii=False)+'\n');archive.flush();states+=1;focuses.append(state['focus']);return state
def chord(code):
 keyboard = os.environ['QURAN_CI_KEYBOARD']
 for key,value in [(56,1),(code,1),(code,0),(56,0)]:
  d.sh(f'sendevent {keyboard} 1 {key} {value}; sendevent {keyboard} 0 0 0');time.sleep(.06)
 time.sleep(.4)
def reach(label,direction=106,limit=40):
 for _ in range(limit):
  state=probe()
  if label in state['focus']:return state
  chord(direction)
 raise AssertionError((label,focuses[-limit:]))
def activate(label,direction=106):
 reach(label,direction);chord(28);time.sleep(.5)
def passed(case):
 checks.append(case);print('PASS',case,flush=True)
def arrow(state,label,active):
 nodes=[n for n in state['nodes'] if label in n['label']]
 assert len(nodes)==1, (label,'duplicate/missing named control',nodes)
 n=nodes[0]
 assert n['class']=='android.widget.Button', (label,'role',n)
 assert n['enabled']==active and bool(n['actions']&16)==active, (label,'enabled/click action',n)
 assert n['clickable']==active, (label,'clickable',n)
d.adb('root');d.adb('wait-for-device')
try:
 version = re.search(r'versionName=([^\s]+)', d.sh('dumpsys','package','com.google.android.marvin.talkback')).group(1)
 d.sh('am','force-stop',d.PACKAGE)
 d.sh('settings','put','secure','enabled_accessibility_services','com.google.android.marvin.talkback/com.google.android.marvin.talkback.TalkBackService')
 d.sh('settings','put','secure','accessibility_enabled','1');time.sleep(2);d.start()
 state=reach('الآية 1:1 ')
 for label,active in [('العودة إلى اختيار القراءة',True),('الآية التالية',True),('الآية السابقة',False)]:
  arrow(state,label,active)
 passed('unique-arrow-button-name-role-and-enabled-action')
 verse=[n for n in state['nodes'] if 'الآية 1:1 ' in n['label']]
 assert len(verse)==1 and verse[0]['actions']&16 and 'بِسۡمِ ٱللَّهِ' in verse[0]['label']
 d.shot('talkback-reader-focused');passed('canonical-whole-verse-label-and-action')
 activate('فتح التفسير');passed('direct-bookstand-activation')
 activate('اختيار تفسير الطبري')
 state=probe();author=[n for n in state['nodes'] if 'اختيار تفسير الطبري' in n['label']]
 assert len(author)==1 and all(author[0][k] for k in ['selected','enabled','clickable']) and author[0]['actions']&16
 passed('selected-author-name-role-action')
 activate('المصدر والترخيص',105)
 state=probe();assert any('مركز تفسير' in n['label'] for n in state['nodes'])
 d.shot('talkback-source');passed('source-activation')
 activate('العودة إلى التفسير',105)
 activate('العودة إلى القراءة',105)
 state=probe();assert any('الآية 1:1 ' in n['label'] for n in state['nodes'])
 passed('source-sheet-reader-return')
 activate('الآية التالية',105)
 state=reach('الآية 1:2 ')
 assert any('ٱلۡحَمۡدُ' in n['label'] for n in state['nodes'])
 d.shot('talkback-adjacent-focused');passed('adjacent-ayah-focus')
 activate('الآية السابقة',105)
 state=reach('الآية 1:1 ')
 passed('previous-arrow-accessible-activation')
 activate('الآية التالية',105)
 reach('الآية 1:2 ')
 activate('العودة إلى اختيار القراءة',105)
 activate('السور')
 state=probe();chapters=[n for n in state['nodes'] if 'السورة 1' in n['label']]
 assert len(chapters)==1 and chapters[0]['selected'] and chapters[0]['enabled'] and chapters[0]['actions']&16
 activate('السورة 2')
 passed('chapter-picker-name-role-selection-activation')
 activate('الانتقال إلى آية')
 state=probe();verses=[n for n in state['nodes'] if n['label'].endswith('Verse 1')]
 assert len(verses)==1 and verses[0]['selected'] and verses[0]['actions']&16
 activate('Verse 2')
 passed('verse-grid-name-role-selection-activation')
 activate('Start Reading Quran')
 state=reach('الآية 2:2 ')
 assert any('الآية 2:2 ' in n['label'] for n in state['nodes'])
 d.shot('talkback-picker-return-reader');passed('picker-reader-key-consistency')
 # Select two distant test states with ordinary UI input while TalkBack is off.
 # All assertions and activations below use the real service and keyboard.
 import device_navigation as current
 for surah,ayah in [(27,59),(114,6)]:
  d.sh('settings','put','secure','accessibility_enabled','0');time.sleep(.5)
  current.jump(surah,ayah)
  d.sh('settings','put','secure','accessibility_enabled','1');time.sleep(2)
  state=reach(f'الآية {surah}:{ayah} ')
  arrow(state,'العودة إلى اختيار القراءة',True)
  arrow(state,'الآية السابقة',True)
  arrow(state,'الآية التالية',surah!=114)
  if surah==27:
   activate('العودة إلى اختيار القراءة',105)
   reach('Start Reading Quran')
   activate('Start Reading Quran')
   reach('الآية 27:59 ')
   activate('الآية التالية',105);reach('الآية 27:60 ')
   activate('الآية السابقة',105);reach('الآية 27:59 ')
   d.shot('talkback-restored-27-59')
   passed('retained-27-59-header-entry-reader-next-previous-activation')
  else:
   activate('الآية السابقة',105)
   state=reach('الآية 114:5 ');arrow(state,'الآية التالية',True)
   activate('الآية التالية',105)
   state=reach('الآية 114:6 ');arrow(state,'الآية التالية',False)
   d.shot('talkback-final-boundary-114-6')
   passed('disabled-final-next-role-action-and-adjacent-return')
 d.save('talkback-result',dict(status='passed',source_commit=os.environ['GITHUB_SHA'],states=states,checks=checks,elapsedSeconds=round(time.monotonic()-started,3),talkbackVersion=version,activation='Real Alt+arrow/Enter Linux keyboard events in task-owned emulator',phoneAccess=False,limits=['No human speech/pronunciation or touch-gesture validation.','Original TalkBack parity has no retained observation.']))
except BaseException as error:
 d.save('talkback-failure',dict(source_commit=os.environ['GITHUB_SHA'],status='failed',error=repr(error),traceback=traceback.format_exc(),states=states,checks=checks,recentFocuses=focuses[-12:]))
 d.shot('talkback-failure');raise
finally:
 archive.close()
 for key,value in initial.items():
  if value=='null':d.sh('settings','delete','secure',key)
  else:d.sh('settings','put','secure',key,value)
 pass
