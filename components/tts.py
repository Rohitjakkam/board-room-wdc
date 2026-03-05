"""
Text-to-Speech helper using the browser's Web Speech API.
Renders a play/stop button that reads text aloud via JavaScript.

Includes a workaround for Chrome's 15-second pause bug by chunking
long text into sentence-sized utterances.
"""

import hashlib
import re
import streamlit.components.v1 as components


def _strip_html(text: str) -> str:
    """Remove HTML tags and collapse whitespace for clean speech output."""
    clean = re.sub(r'<[^>]+>', ' ', text)
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


def speak_button(text: str, label: str = "Listen", key: str = "tts"):
    """Render a play/stop TTS button that reads *text* aloud.

    Uses the browser's built-in Web Speech API -- no backend calls,
    no extra dependencies, works on all modern browsers.

    Handles Chrome's 15-second pause bug by splitting long text into
    sentence-sized chunks and queuing them sequentially.
    """
    if not text:
        return

    clean_text = _strip_html(text)
    if not clean_text:
        return

    safe_key = "tts_" + hashlib.md5(key.encode()).hexdigest()[:8]
    # Escape for JS single-quoted string
    js_text = (clean_text
               .replace("\\", "\\\\")
               .replace("'", "\\'")
               .replace("\n", " ")
               .replace("\r", ""))

    # JS regex for sentence splitting — kept outside f-string to avoid
    # Python escape sequence warnings with \s
    _sentence_re = r"[^.!?]+[.!?]+\s*"

    html = f"""
    <div style="display:inline-block;">
        <button id="btn_{safe_key}" style="
            background: linear-gradient(135deg, #1E3A5F 0%, #2c5282 100%);
            color: white; border: none; padding: 6px 14px;
            border-radius: 20px; cursor: pointer; font-size: 13px;
            font-weight: 500; display: inline-flex; align-items: center; gap: 5px;
            transition: all 0.2s; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        " onmouseover="this.style.transform='scale(1.05)'"
          onmouseout="this.style.transform='scale(1)'">
            <span id="ico_{safe_key}">&#128266;</span>
            <span id="lbl_{safe_key}">{label}</span>
        </button>
    </div>
    <script>
    (function() {{
        var synth = window.speechSynthesis;
        var active = false;
        var btn = document.getElementById('btn_{safe_key}');
        var ico = document.getElementById('ico_{safe_key}');
        var lbl = document.getElementById('lbl_{safe_key}');
        var voicesReady = false;
        var cachedVoice = null;

        function pickVoice() {{
            var voices = synth.getVoices();
            if (!voices.length) return null;
            var pref = voices.find(function(v) {{
                return v.lang.startsWith('en') &&
                       (v.name.indexOf('Google') >= 0 ||
                        v.name.indexOf('Microsoft') >= 0 ||
                        v.name.indexOf('Natural') >= 0);
            }});
            if (!pref) pref = voices.find(function(v) {{ return v.lang.startsWith('en'); }});
            return pref || null;
        }}

        /* Pre-load voices (Chrome loads them async) */
        if (synth.onvoiceschanged !== undefined) {{
            synth.onvoiceschanged = function() {{
                cachedVoice = pickVoice();
                voicesReady = true;
            }};
        }}
        cachedVoice = pickVoice();
        if (cachedVoice) voicesReady = true;

        /* Split text into chunks at sentence boundaries to avoid
           Chrome's 15-second pause bug. Each chunk < 200 chars. */
        function chunkText(text) {{
            var sentences = text.match(/{_sentence_re}/g);
            if (!sentences) return [text];
            var chunks = [];
            var current = '';
            for (var i = 0; i < sentences.length; i++) {{
                if ((current + sentences[i]).length > 200 && current.length > 0) {{
                    chunks.push(current.trim());
                    current = sentences[i];
                }} else {{
                    current += sentences[i];
                }}
            }}
            if (current.trim()) chunks.push(current.trim());
            return chunks.length ? chunks : [text];
        }}

        function resetBtn() {{
            active = false;
            ico.innerHTML = '&#128266;';
            lbl.textContent = '{label}';
        }}

        btn.onclick = function() {{
            if (active || synth.speaking) {{
                synth.cancel();
                resetBtn();
                return;
            }}
            var fullText = '{js_text}';
            var chunks = chunkText(fullText);
            active = true;
            ico.innerHTML = '&#9209;';
            lbl.textContent = 'Stop';

            function speakChunk(idx) {{
                if (idx >= chunks.length || !active) {{
                    resetBtn();
                    return;
                }}
                var u = new SpeechSynthesisUtterance(chunks[idx]);
                u.rate = 0.95;
                u.pitch = 1.0;
                if (cachedVoice) u.voice = cachedVoice;
                else {{
                    var v = pickVoice();
                    if (v) {{ cachedVoice = v; u.voice = v; }}
                }}
                u.onend = function() {{ speakChunk(idx + 1); }};
                u.onerror = function() {{ resetBtn(); }};
                synth.speak(u);
            }}
            speakChunk(0);
        }};
    }})();
    </script>
    """
    components.html(html, height=42)
