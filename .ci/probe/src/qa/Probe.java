package qa;
import android.app.*;import android.os.*;import android.view.*;import android.view.accessibility.*;import android.accessibilityservice.*;import android.graphics.Rect;import org.json.*;
public class Probe extends Instrumentation {
 Bundle args; UiAutomation u;
 public void onCreate(Bundle b){super.onCreate(b);args=b;start();}
 String label(AccessibilityNodeInfo n){return n==null?"<none>":String.valueOf(n.getText())+" | "+String.valueOf(n.getContentDescription());}
 void dump(AccessibilityNodeInfo n,JSONArray a)throws Exception{if(n==null)return;JSONObject o=new JSONObject();Rect r=new Rect();n.getBoundsInScreen(r);o.put("label",label(n));o.put("hint",String.valueOf(n.getHintText()));o.put("class",String.valueOf(n.getClassName()));o.put("bounds",r.toShortString());o.put("a11yFocused",n.isAccessibilityFocused());o.put("focusable",n.isFocusable());o.put("selected",n.isSelected());o.put("enabled",n.isEnabled());o.put("clickable",n.isClickable());o.put("actions",n.getActions());a.put(o);for(int i=0;i<n.getChildCount();i++)dump(n.getChild(i),a);}
 void key(int action,int code,int meta,long down){u.injectInputEvent(new KeyEvent(down,SystemClock.uptimeMillis(),action,code,0,meta,KeyCharacterMap.VIRTUAL_KEYBOARD,0,KeyEvent.FLAG_FROM_SYSTEM,InputDevice.SOURCE_KEYBOARD),true);}
 void next(){long t=SystemClock.uptimeMillis();key(0,57,KeyEvent.META_ALT_ON|KeyEvent.META_ALT_LEFT_ON,t);key(0,22,KeyEvent.META_ALT_ON|KeyEvent.META_ALT_LEFT_ON,t);key(1,22,KeyEvent.META_ALT_ON|KeyEvent.META_ALT_LEFT_ON,t);key(1,57,0,t);}
 public void onStart(){Bundle result=new Bundle();try{u=getUiAutomation(UiAutomation.FLAG_DONT_SUPPRESS_ACCESSIBILITY_SERVICES);AccessibilityServiceInfo s=u.getServiceInfo();s.flags|=AccessibilityServiceInfo.FLAG_RETRIEVE_INTERACTIVE_WINDOWS;u.setServiceInfo(s);JSONArray states=new JSONArray();
 for(int i=0;i<=Integer.parseInt(args.getString("steps","0"));i++){if(i>0){next();SystemClock.sleep(1000);}AccessibilityNodeInfo root=u.getRootInActiveWindow();for(int retry=0;root==null&&retry<20;retry++){SystemClock.sleep(100);root=u.getRootInActiveWindow();}JSONObject state=new JSONObject();state.put("step",i);state.put("focus",label(root==null?null:root.findFocus(AccessibilityNodeInfo.FOCUS_ACCESSIBILITY)));JSONArray nodes=new JSONArray();dump(root,nodes);state.put("nodes",nodes);states.put(state);}result.putString("stream",states.toString(2));finish(0,result);
 }catch(Exception e){result.putString("stream",e.toString());finish(1,result);}}
}
