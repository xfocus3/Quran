import com.xfocus.quranly.local.TafsirDisplay;
import java.io.DataInputStream;
import java.io.DataOutputStream;
import java.io.EOFException;
import java.nio.charset.StandardCharsets;

/** Host probe of the production pure display boundary; no Android substitutes. */
public final class TafsirDisplayProbe {
    public static void main(String[] args) throws Exception {
        DataInputStream input = new DataInputStream(System.in);
        DataOutputStream output = new DataOutputStream(System.out);
        while (true) {
            int length;
            try { length = input.readInt(); } catch (EOFException end) { return; }
            if (length < 0 || length > 1_000_000) throw new IllegalArgumentException("Row too large");
            byte[] raw = input.readNBytes(length);
            if (raw.length != length) throw new EOFException("Partial row");
            byte[] display = TafsirDisplay.render(new String(raw, StandardCharsets.UTF_8))
                .getBytes(StandardCharsets.UTF_8);
            output.writeInt(display.length);
            output.write(display);
            output.flush();
        }
    }
}
