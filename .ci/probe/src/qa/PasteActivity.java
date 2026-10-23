package qa;
import android.app.Activity;
import android.os.Bundle;
import android.content.ClipboardManager;
import android.content.ClipData;
import android.view.*;
import android.widget.*;
public class PasteActivity extends Activity {
 public void onCreate(Bundle state) {
  setTheme(android.R.style.Theme_Material_Light_NoActionBar);
  super.onCreate(state);
  LinearLayout layout = new LinearLayout(this);
  layout.setOrientation(LinearLayout.VERTICAL);
  final int gap = (int)(16 * getResources().getDisplayMetrics().density);
  layout.setOnApplyWindowInsetsListener((view, insets) -> {
   android.graphics.Insets bars = insets.getInsets(WindowInsets.Type.systemBars());
   view.setPadding(gap + bars.left, gap + bars.top, gap + bars.right, gap + bars.bottom);
   return insets;
  });
  Button paste = new Button(this);
  paste.setText("Read Android clipboard");
  paste.setTextSize(16);
  layout.addView(paste, new LinearLayout.LayoutParams(-1, -2));
  EditText input = new EditText(this);
  input.setId(100);
  input.setHint("Paste Quran Unicode here");
  input.setTextSize(16);
  input.setTextDirection(View.TEXT_DIRECTION_RTL);
  input.setGravity(Gravity.TOP | Gravity.START);
  layout.addView(input, new LinearLayout.LayoutParams(-1, 0, 1));
  paste.setOnClickListener(view -> {
   ClipboardManager manager = (ClipboardManager)getSystemService(CLIPBOARD_SERVICE);
   ClipData clip = manager.getPrimaryClip();
   input.setText(clip == null ? "<empty>" : clip.getItemAt(0).coerceToText(this));
  });
  setContentView(layout);
  paste.requestFocus();
  getWindow().setSoftInputMode(WindowManager.LayoutParams.SOFT_INPUT_STATE_ALWAYS_HIDDEN);
 }
}
