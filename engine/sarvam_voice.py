"""
VyaparDost AI — Voice Module (Speak & Approve)
Now with language selection: English, Hindi, Kannada.

Two modes, auto-selected:
  1. REAL MODE — if SARVAM_API_KEY is set, this calls the real Sarvam API
     for text-to-speech in the chosen language and can be wired to Sarvam's
     speech-to-text for the merchant's spoken reply.
  2. MOCK MODE — if no key is set, this falls back to:
       - Offline text-to-speech via pyttsx3 (uses Windows SAPI voices).
         NOTE: most Windows machines only ship an English SAPI voice by
         default, so Hindi/Kannada text in mock mode will PRINT correctly
         but may be spoken in an English accent or skipped if no matching
         voice is installed. The real Sarvam API produces proper native
         audio in all three languages — this only affects offline mock mode.
       - Typed input standing in for the merchant's spoken reply

To go live later: set SARVAM_API_KEY (via .env or environment variable) —
no other code changes needed.

Install for mock-mode speech (optional but recommended):
    pip install pyttsx3

Install for .env file support (recommended):
    pip install python-dotenv
"""

import base64
import os
import sys
import tempfile
import difflib

try:
    import sounddevice as sd
    import numpy as np
    HAS_MIC = True
except (ImportError, OSError):
    HAS_MIC = False

try:
    from dotenv import load_dotenv
    _env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env")
    load_dotenv(_env_path)
except ImportError:
    pass

SARVAM_API_KEY = os.environ.get("SARVAM_API_KEY", "").strip()
SARVAM_TTS_ENDPOINT = "https://api.sarvam.ai/text-to-speech"
SARVAM_STT_ENDPOINT = "https://api.sarvam.ai/speech-to-text"
SARVAM_TTS_MODEL = os.environ.get("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_SPEAKER = os.environ.get("SARVAM_SPEAKER", "shubh")

SARVAM_STT_MODEL = os.environ.get("SARVAM_STT_MODEL", "saaras:v3")
RECORD_SECONDS = float(os.environ.get("SARVAM_RECORD_SECONDS", "4"))
RECORD_SAMPLE_RATE = 16000

USE_REAL_SARVAM = bool(SARVAM_API_KEY)

LANGUAGES = {
    "1": {"name": "English", "sarvam_code": "en-IN"},
    "2": {"name": "Hindi", "sarvam_code": "hi-IN"},
    "3": {"name": "Kannada", "sarvam_code": "kn-IN"},
}

ACTION_TRANSLATIONS = {
    "Win back lapsed customers": {
        "en": "Win back lapsed customers",
        "hi": "पुराने ग्राहकों को वापस लाना",
        "kn": "ಹಳೆಯ ಗ್ರಾಹಕರನ್ನು ಮರಳಿ ತರುವುದು",
    },
    "Promote evening products": {
        "en": "Promote evening products",
        "hi": "शाम के उत्पादों को बढ़ावा देना",
        "kn": "ಸಂಜೆಯ ಉತ್ಪನ್ನಗಳನ್ನು ಉತ್ತೇಜಿಸುವುದು",
    },
    "Run a weekend offer": {
        "en": "Run a weekend offer",
        "hi": "सप्ताहांत ऑफर चलाना",
        "kn": "ವಾರಾಂತ್ಯದ ಆಫರ್ ನಡೆಸುವುದು",
    },
}

RECOMMENDATION_TEMPLATES = {
    "en": (
        "This week {customers_this_week} customers visited, compared to about "
        "{customers_normal} customers in a normal week — a loss of about ₹{loss_amount}. "
        "I compared three ways to recover it. "
        "{action} looks strongest — targeting {target_count} customers, "
        "expected to recover around ₹{opportunity}, about {recovery_pct}% of what was lost. "
        "A ₹{discount} offer stays within budget and discount guardrails. "
        "Shall I launch it?"
    ),
    "hi": (
        "इस हफ्ते {customers_this_week} ग्राहक आए, जबकि सामान्य हफ्ते में लगभग "
        "{customers_normal} ग्राहक आते हैं — लगभग ₹{loss_amount} का नुकसान हुआ। "
        "मैंने इसे ठीक करने के तीन तरीके देखे। "
        "{action} सबसे मजबूत लग रहा है — {target_count} ग्राहकों को लक्षित करके, "
        "लगभग ₹{opportunity} वापस आने की उम्मीद है, जो नुकसान का लगभग {recovery_pct}% है। "
        "₹{discount} की छूट बजट और छूट सीमा के भीतर है। "
        "क्या मैं इसे शुरू करूं?"
    ),
    "kn": (
        "ಈ ವಾರ {customers_this_week} ಗ್ರಾಹಕರು ಬಂದಿದ್ದಾರೆ, ಸಾಮಾನ್ಯ ವಾರದಲ್ಲಿ ಸುಮಾರು "
        "{customers_normal} ಗ್ರಾಹಕರು ಬರುತ್ತಾರೆ — ಸುಮಾರು ₹{loss_amount} ನಷ್ಟವಾಗಿದೆ. "
        "ಇದನ್ನು ಸರಿಪಡಿಸಲು ನಾನು ಮೂರು ಮಾರ್ಗಗಳನ್ನು ಹೋಲಿಸಿದೆ. "
        "{action} ಅತ್ಯಂತ ಪ್ರಬಲವಾಗಿ ಕಾಣುತ್ತದೆ — {target_count} ಗ್ರಾಹಕರನ್ನು ಗುರಿಯಾಗಿಸಿ, "
        "ಸುಮಾರು ₹{opportunity} ಮರಳಿ ಪಡೆಯುವ ನಿರೀಕ್ಷೆ ಇದೆ, ಇದು ನಷ್ಟದ ಸುಮಾರು {recovery_pct}%. "
        "₹{discount} ರಿಯಾಯಿತಿ ಬಜೆಟ್ ಮತ್ತು ರಿಯಾಯಿತಿ ಮಿತಿಯೊಳಗೆ ಇದೆ. "
        "ನಾನು ಇದನ್ನು ಪ್ರಾರಂಭಿಸಲೇ?"
    ),
}

CONFIRM_TEMPLATES = {
    "en": {
        "approved": "Approved. Launching the campaign now.",
        "declined": "Understood — I won't launch this campaign.",
    },
    "hi": {
        "approved": "स्वीकृत। अभी अभियान शुरू कर रहा हूं।",
        "declined": "ठीक है — मैं यह अभियान शुरू नहीं करूंगा।",
    },
    "kn": {
        "approved": "ಅನುಮೋದಿಸಲಾಗಿದೆ. ಈಗ ಅಭಿಯಾನವನ್ನು ಪ್ರಾರಂಭಿಸುತ್ತಿದ್ದೇನೆ.",
        "declined": "ಅರ್ಥವಾಯಿತು — ನಾನು ಈ ಅಭಿಯಾನವನ್ನು ಪ್ರಾರಂಭಿಸುವುದಿಲ್ಲ.",
    },
}

APPROVAL_PHRASES = [
    "yes", "ok", "okay", "launch", "lanch", "lunch it", "go ahead",
    "do it", "approve", "confirm", "sure", "send it",
    "haan", "bhej do", "haan bhej do", "ha", "kar do", "chalu karo",
    "shuru karo", "shuru kar do", "shuru",
    "हां", "हाँ", "भेज दो", "कर दो", "चालू करो", "शुरू करो", "शुरू",
    "howdu", "kalisi", "madi", "shuru madi", "prarambhisi",
    "ಹೌದು", "ಕಳಿಸಿ", "ಮಾಡಿ", "ಶುರು ಮಾಡಿ", "ಪ್ರಾರಂಭಿಸಿ", "ಪ್ರಾರಂಭ",
]


def select_language():
    """
    Prompts for a language choice. Tolerant of messy input:
      - exact number: "2"
      - exact name (any case): "Hindi", "kannada"
      - number with extra characters: "3.Kannada", "2) Hindi"
      - name embedded in a longer reply: "I want Kannada please"
    Defaults to English on blank/unrecognized input.
    """
    print("\nSelect language / भाषा चुनें / ಭಾಷೆ ಆಯ್ಕೆಮಾಡಿ:")
    for key, lang in LANGUAGES.items():
        print(f"  {key}. {lang['name']}")
    choice = input("Enter 1/2/3 or the language name (default: English): ").strip()
    choice_lower = choice.lower()

    lang = None

    if choice in LANGUAGES:
        lang = LANGUAGES[choice]

    if lang is None:
        name_lookup = {l["name"].lower(): l for l in LANGUAGES.values()}
        lang = name_lookup.get(choice_lower)

    if lang is None:
        for ch in choice:
            if ch in LANGUAGES:
                lang = LANGUAGES[ch]
                break

    if lang is None:
        for l in LANGUAGES.values():
            if l["name"].lower() in choice_lower:
                lang = l
                break

    if lang is None:
        lang = LANGUAGES["1"]

    print(f"-> Using {lang['name']}\n")
    return lang


def build_recommendation_text(lang_code, dip_pct, action, opportunity, discount,
                               customers_this_week=None, customers_normal=None,
                               loss_amount=None, target_count=None, recovery_pct=None):
    action_localized = ACTION_TRANSLATIONS.get(action, {}).get(lang_code, action)
    template = RECOMMENDATION_TEMPLATES.get(lang_code, RECOMMENDATION_TEMPLATES["en"])
    return template.format(
        dip_pct=f"{dip_pct:.0f}",
        action=action_localized,
        opportunity=f"{opportunity:,.0f}",
        discount=discount,
        customers_this_week=customers_this_week if customers_this_week is not None else "?",
        customers_normal=f"{customers_normal:.0f}" if customers_normal is not None else "?",
        loss_amount=f"{loss_amount:,.0f}" if loss_amount is not None else "?",
        target_count=target_count if target_count is not None else "?",
        recovery_pct=f"{recovery_pct:.0f}" if recovery_pct is not None else "?",
    )


def _play_wav_file(path):
    """
    Plays a WAV file using whatever the OS gives us for free — no extra
    pip installs required. Falls back to just telling the person where
    the file is if nothing works (e.g. a headless server).
    """
    try:
        if sys.platform.startswith("win"):
            import winsound
            winsound.PlaySound(path, winsound.SND_FILENAME)
        elif sys.platform == "darwin":
            os.system(f'afplay "{path}"')
        else:
            # most Linux desktops ship aplay (ALSA) by default
            os.system(f'aplay "{path}" 2>/dev/null || paplay "{path}"')
    except Exception as e:
        print(f"  (Couldn't auto-play audio: {e}. File saved at: {path})")


def _speak_real(text, sarvam_language_code="hi-IN"):
    import requests

    payload = {
        "text": text,
        "target_language_code": sarvam_language_code,
        "speaker": SARVAM_SPEAKER,
        "model": SARVAM_TTS_MODEL,
    }
    headers = {
        "api-subscription-key": SARVAM_API_KEY,
        "Content-Type": "application/json",
    }
    resp = requests.post(SARVAM_TTS_ENDPOINT, json=payload, headers=headers, timeout=15)
    resp.raise_for_status()
    data = resp.json()

    # The real response is JSON with an "audios" array of base64-encoded
    # WAV strings — NOT raw audio bytes. This is the part the old code
    # never did: it printed a "Spoke" message but never touched the
    # response body, so nothing was ever actually played.
    audio_b64_parts = data.get("audios")
    if not audio_b64_parts:
        raise RuntimeError(f"Sarvam API returned no audio: {data}")

    audio_bytes = base64.b64decode("".join(audio_b64_parts))

    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        f.write(audio_bytes)
        tmp_path = f.name

    print(f"[Sarvam TTS - {sarvam_language_code}] Speaking: \"{text}\"")
    _play_wav_file(tmp_path)
    return data


def _speak_mock(text):
    print(f'\n[VyaparDost speaking]: "{text}"')
    try:
        import pyttsx3
        engine = pyttsx3.init()
        engine.say(text)
        engine.runAndWait()
    except ImportError:
        print("  (Install `pyttsx3` for actual audio: pip install pyttsx3)")
    except Exception as e:
        print(f"  (TTS playback skipped: {e})")


def speak(text, sarvam_language_code="hi-IN"):
    if USE_REAL_SARVAM:
        try:
            return _speak_real(text, sarvam_language_code)
        except Exception as e:
            print(f"[Sarvam API error, falling back to mock]: {e}")
            _speak_mock(text)
    else:
        _speak_mock(text)


def speak_execution_confirmation(text, sarvam_language_code="hi-IN"):
    """
    Speaks a short confirmation back to the merchant AFTER the campaign
    has actually run (e.g. after n8n's real webhook response comes back)
    — separate from the initial recommendation prompt in demo_voice_exchange,
    since this happens later in the flow, once real results exist.
    Thin wrapper around speak() so the [ACT] step can talk, not just print.
    """
    speak(text, sarvam_language_code)


def _record_from_microphone(path, seconds=RECORD_SECONDS, samplerate=RECORD_SAMPLE_RATE):
    import wave

    print(f"\n🎤 Listening — speak your reply now ({seconds:.0f}s)...")
    audio = sd.rec(int(seconds * samplerate), samplerate=samplerate, channels=1, dtype="int16")
    sd.wait()
    with wave.open(path, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(samplerate)
        wf.writeframes(audio.tobytes())
    print("  (done listening)")


def _transcribe_with_sarvam(path, sarvam_language_code="hi-IN"):
    import requests

    with open(path, "rb") as f:
        files = {"file": ("reply.wav", f, "audio/wav")}
        data = {
            "model": SARVAM_STT_MODEL,
            "language_code": sarvam_language_code,
            "mode": "transcribe",
        }
        headers = {"api-subscription-key": SARVAM_API_KEY}
        resp = requests.post(SARVAM_STT_ENDPOINT, headers=headers, files=files, data=data, timeout=30)
    resp.raise_for_status()
    result = resp.json()
    return (result.get("transcript") or "").strip()


def _listen_via_microphone(sarvam_language_code):
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
        tmp_path = f.name
    _record_from_microphone(tmp_path)
    transcript = _transcribe_with_sarvam(tmp_path, sarvam_language_code)
    if not transcript:
        raise RuntimeError("Sarvam STT returned an empty transcript")
    print(f"  (Sarvam heard): \"{transcript}\"")
    return transcript


def _listen_typed():
    reply = input("Merchant (spoken reply, simulated as text for now): ").strip()
    if reply == "":
        reply = input("(No input detected — please type your reply again): ").strip()
    return reply


def _listen_real(sarvam_language_code="hi-IN"):
    """
    Actually listens via the microphone and transcribes with Sarvam's
    speech-to-text when both the mic library and the API key are
    available. Falls back to typed input otherwise — this is the piece
    that was missing before: previously this function ONLY ever did
    input(), regardless of mode, so speaking out loud never registered.
    """
    if USE_REAL_SARVAM and HAS_MIC:
        try:
            return _listen_via_microphone(sarvam_language_code)
        except Exception as e:
            print(f"[Mic/STT error, falling back to typed input]: {e}")
            return _listen_typed()
    if USE_REAL_SARVAM and not HAS_MIC:
        print("  (No microphone library found — install with: pip install sounddevice numpy)")
    return _listen_typed()


def _fuzzy_word_matches_keyword(word, keyword, threshold=0.75):
    return difflib.SequenceMatcher(None, word, keyword).ratio() >= threshold


def listen_for_approval(sarvam_language_code="hi-IN"):
    """
    Two passes:
      1. Exact substring match against APPROVAL_PHRASES — handles full
         phrases like "haan bhej do" that only make sense together.
      2. Fuzzy per-word match against the single-word phrases — catches
         typos and STT slips like "lach"/"lanch" for "launch", without
         needing every possible misspelling hardcoded in the list.
    Short words (<3 chars) are skipped in the fuzzy pass to avoid false
    positives (e.g. "it" or "ok" drifting into an unrelated match).
    """
    reply = _listen_real(sarvam_language_code)
    reply_lower = reply.lower()

    if any(phrase.lower() in reply_lower for phrase in APPROVAL_PHRASES):
        return True, reply

    single_word_phrases = [p.lower() for p in APPROVAL_PHRASES if " " not in p]
    for word in reply_lower.split():
        if len(word) < 3:
            continue
        for phrase in single_word_phrases:
            if _fuzzy_word_matches_keyword(word, phrase):
                return True, reply

    return False, reply


def demo_voice_exchange(dip_pct, action, opportunity, discount, lang=None,
                         customers_this_week=None, customers_normal=None,
                         loss_amount=None, target_count=None, recovery_pct=None):
    if lang is None:
        lang = select_language()
    lang_code = {"English": "en", "Hindi": "hi", "Kannada": "kn"}[lang["name"]]

    recommendation_text = build_recommendation_text(
        lang_code, dip_pct, action, opportunity, discount,
        customers_this_week=customers_this_week,
        customers_normal=customers_normal,
        loss_amount=loss_amount,
        target_count=target_count,
        recovery_pct=recovery_pct,
    )

    mode = "REAL SARVAM API" if USE_REAL_SARVAM else "MOCK MODE (offline TTS + typed input)"
    if USE_REAL_SARVAM:
        mode += " + mic listening" if HAS_MIC else " (TTS only — typed input, no mic library)"
    print(f"--- Voice exchange [{mode}] [{lang['name']}] ---")

    speak(recommendation_text, lang["sarvam_code"])

    approved, raw_reply = listen_for_approval(lang["sarvam_code"])
    print(f"[Merchant said]: \"{raw_reply}\"")

    confirmation = CONFIRM_TEMPLATES[lang_code]["approved" if approved else "declined"]
    speak(confirmation, lang["sarvam_code"])

    return approved


if __name__ == "__main__":
    result = demo_voice_exchange(
        dip_pct=27,
        action="Win back lapsed customers",
        opportunity=12000,
        discount=20,
    )
    print(f"\nFinal decision: {'LAUNCH' if result else 'HOLD'}")