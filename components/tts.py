"""
Speech helpers using the browser's Web Speech API.

- speak_button: Text-to-Speech — reads text aloud (with Chrome chunking workaround)
- mic_button:   Speech-to-Text — dictates into a Streamlit text_area via microphone
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


def mic_button(target_label: str, key: str = "mic"):
    """Render a microphone button that dictates into a Streamlit text_area.

    Uses the browser's SpeechRecognition API. Transcribed speech is
    appended to the textarea identified by *target_label* (the label
    passed to st.text_area).

    Works on Chrome, Edge, and other Chromium-based browsers.
    Firefox has limited support.
    """
    safe_key = "mic_" + hashlib.md5(key.encode()).hexdigest()[:8]
    # Escape the label for JS string matching
    js_label = target_label.replace("\\", "\\\\").replace("'", "\\'")

    html = f"""
    <div style="display:inline-block;">
        <button id="btn_{safe_key}" style="
            background: linear-gradient(135deg, #c0392b 0%, #e74c3c 100%);
            color: white; border: none; padding: 6px 14px;
            border-radius: 20px; cursor: pointer; font-size: 13px;
            font-weight: 500; display: inline-flex; align-items: center; gap: 5px;
            transition: all 0.2s; box-shadow: 0 2px 4px rgba(0,0,0,0.1);
        " onmouseover="this.style.transform='scale(1.05)'"
          onmouseout="this.style.transform='scale(1)'">
            <span id="ico_{safe_key}">&#127908;</span>
            <span id="lbl_{safe_key}">Speak</span>
        </button>
        <span id="status_{safe_key}" style="margin-left:8px; font-size:12px; color:#888;"></span>
    </div>
    <script>
    (function() {{
        var SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        var btn = document.getElementById('btn_{safe_key}');
        var ico = document.getElementById('ico_{safe_key}');
        var lbl = document.getElementById('lbl_{safe_key}');
        var status = document.getElementById('status_{safe_key}');

        if (!SpeechRecognition) {{
            btn.disabled = true;
            btn.style.opacity = '0.5';
            lbl.textContent = 'Not supported';
            status.textContent = 'Use Chrome or Edge for voice input';
            return;
        }}

        var recognition = new SpeechRecognition();
        recognition.continuous = true;
        recognition.interimResults = true;
        recognition.lang = 'en-US';
        var listening = false;
        var finalTranscript = '';

        function findInput() {{
            /* Find the Streamlit textarea or input by its aria-label */
            var doc = window.parent.document;
            /* Try textarea first (st.text_area), then input (st.text_input) */
            var selectors = ['textarea', 'input[type="text"]'];
            for (var s = 0; s < selectors.length; s++) {{
                var elems = doc.querySelectorAll(selectors[s]);
                for (var i = 0; i < elems.length; i++) {{
                    var label = elems[i].getAttribute('aria-label') || '';
                    if (label === '{js_label}') return elems[i];
                }}
            }}
            return null;
        }}

        function setInputValue(el, text) {{
            /* Use React's internal setter so Streamlit picks up the change */
            var proto = el.tagName === 'TEXTAREA'
                ? window.parent.HTMLTextAreaElement.prototype
                : window.parent.HTMLInputElement.prototype;
            var setter = Object.getOwnPropertyDescriptor(proto, 'value').set;
            setter.call(el, text);
            el.dispatchEvent(new Event('input', {{ bubbles: true }}));
        }}

        btn.onclick = function() {{
            if (listening) {{
                recognition.stop();
                return;
            }}
            var textarea = findInput();
            if (!textarea) {{
                status.textContent = 'Text area not found';
                return;
            }}
            finalTranscript = textarea.value || '';
            if (finalTranscript && !finalTranscript.endsWith(' ')) {{
                finalTranscript += ' ';
            }}
            recognition.start();
        }};

        recognition.onstart = function() {{
            listening = true;
            ico.innerHTML = '&#9209;';
            lbl.textContent = 'Stop';
            btn.style.background = 'linear-gradient(135deg, #e74c3c 0%, #ff6b6b 100%)';
            btn.style.animation = 'pulse_{safe_key} 1.5s infinite';
            status.textContent = 'Listening...';
            /* Add pulse animation */
            if (!document.getElementById('style_{safe_key}')) {{
                var style = document.createElement('style');
                style.id = 'style_{safe_key}';
                style.textContent = '@keyframes pulse_{safe_key} {{ 0%,100% {{ box-shadow: 0 0 0 0 rgba(231,76,60,0.4); }} 50% {{ box-shadow: 0 0 0 10px rgba(231,76,60,0); }} }}';
                document.head.appendChild(style);
            }}
        }};

        recognition.onresult = function(event) {{
            var interimTranscript = '';
            for (var i = event.resultIndex; i < event.results.length; i++) {{
                var transcript = event.results[i][0].transcript;
                if (event.results[i].isFinal) {{
                    finalTranscript += transcript;
                }} else {{
                    interimTranscript += transcript;
                }}
            }}
            var textarea = findInput();
            if (textarea) {{
                var display = finalTranscript + interimTranscript;
                setInputValue(textarea, display);
            }}
            status.textContent = interimTranscript ? 'Hearing: ' + interimTranscript.substring(0, 40) + '...' : 'Listening...';
        }};

        recognition.onend = function() {{
            listening = false;
            ico.innerHTML = '&#127908;';
            lbl.textContent = 'Speak';
            btn.style.background = 'linear-gradient(135deg, #c0392b 0%, #e74c3c 100%)';
            btn.style.animation = 'none';
            status.textContent = finalTranscript ? 'Done' : '';
            /* Ensure final value is committed */
            var textarea = findInput();
            if (textarea && finalTranscript) {{
                setInputValue(textarea, finalTranscript);
            }}
        }};

        recognition.onerror = function(event) {{
            listening = false;
            ico.innerHTML = '&#127908;';
            lbl.textContent = 'Speak';
            btn.style.background = 'linear-gradient(135deg, #c0392b 0%, #e74c3c 100%)';
            btn.style.animation = 'none';
            if (event.error === 'not-allowed') {{
                status.textContent = 'Microphone access denied — check browser permissions';
            }} else {{
                status.textContent = 'Error: ' + event.error;
            }}
        }};
    }})();
    </script>
    """
    components.html(html, height=42)
