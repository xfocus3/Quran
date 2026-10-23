package com.xfocus.quranly.local;

/** Inert text projection for the digest-pinned three-book source, not HTML.
 * Only observed source break/paragraph tokens and nbsp are interpreted. All
 * other UTF-16 units pass through unchanged, including leading U+FEFF, literal
 * angle brackets and unmatched/cross-entry footnotes. Raw storage is untouched.
 * One forward pass uses memory proportional to the selected row, never a book.
 */
public final class TafsirDisplay {
    private TafsirDisplay() {}

    public static String render(String raw) {
        StringBuilder text = new StringBuilder(raw.length());
        int offset = 0;
        while (offset < raw.length()) {
            char value = raw.charAt(offset);
            int consumed = 1;
            if (value == '\r') {
                value = '\n';
                if (offset + 1 < raw.length() && raw.charAt(offset + 1) == '\n') consumed = 2;
            } else if (value == '<') {
                if (raw.startsWith("<br>", offset)) consumed = 4;
                else if (raw.startsWith("<p>", offset)) consumed = 3;
                else if (raw.startsWith("</p>", offset)) consumed = 4;
                else if (raw.startsWith("</div>", offset)) consumed = 6;
                if (consumed > 1) value = '\n';
            } else if (value == '&' && raw.startsWith("&nbsp;", offset)) {
                value = '\u00a0';
                consumed = 6;
            }
            text.append(value);
            offset += consumed;
        }
        return text.toString();
    }
}
