"""
VyaparDost AI — Voice Agent "brain"  (question in -> answer out)

This is the missing piece behind the dashboard's Voice tab. Before, the tab
only replayed a saved report (data/last_run_report.json) written by
run_demo.py. Now the browser can ASK questions, and this module answers them
from the same real numbers the rest of the project uses (the CSVs, the
decision engine, the festival calendar, the memory file) — nothing hardcoded.

How it works (deliberately rule-based, like decision_engine.py, so every
answer is explainable and can't hallucinate a number):

    question text --> detect_lang() --> detect_intent() --> build answer

Answers are written in English, Hindi and Kannada. The browser then sends the
answer text to /api/voice/tts (Sarvam) to actually speak it.
"""

import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_engine import (
    load_csv, compute_weekly_sales, compute_sales_dip,
    generate_next_best_actions, DATA_DIR,
    MAX_CAMPAIGN_BUDGET, MAX_DISCOUNT_PER_OFFER,
)
from run_demo import (
    weekly_customer_counts, analyze_sales_pattern, check_upcoming_festival,
    HIGH_DEMAND_FESTIVALS, DAY_NAME_TRANSLATIONS, SLOT_NAME_TRANSLATIONS,
    BUSINESS_TYPES,
)
from sarvam_voice import ACTION_TRANSLATIONS

try:
    from memory import _read_local_memory
except Exception:  # memory module is optional for answering
    _read_local_memory = lambda: None

OFFER_DISCOUNT = 20  # ₹ — same offer the terminal demo recommends


def _inr(v):
    return f"₹{v:,.0f}"


# --------------------------------------------------------------------------
# Language + intent detection
# --------------------------------------------------------------------------
def detect_lang(text, default="en"):
    """Kannada / Devanagari script in the question overrides the dropdown."""
    if re.search(r"[\u0C80-\u0CFF]", text):
        return "kn"
    if re.search(r"[\u0900-\u097F]", text):
        return "hi"
    return default if default in ("en", "hi", "kn") else "en"


# Order matters: the first pattern that matches wins, so specific intents
# (festival, memory...) are checked before broad ones (sales).
INTENT_PATTERNS = [
    ("greeting", r"^\s*(hi|hello|hey|namaste|namaskar|namaskara|good (morning|evening|afternoon))\b|^\s*(नमस्ते|नमस्कार|ನಮಸ್ಕಾರ|ಹಲೋ)"),
    ("festival", r"festival|festive|diwali|navratri|ganesh|dussehra|त्योहार|त्यौहार|उत्सव|ಹಬ್ಬ|tyohar|hubba"),
    ("memory", r"last campaign|previous campaign|past campaign|remember|memory|what did you learn|पिछल|याद|सीख|ಹಿಂದಿನ|ನೆನಪು|pichhla|pichle"),
    ("paytm", r"paytm|cash|new users?|पेटीएम|नकद|कैश|ಪೇಟಿಎಂ|ಪೇಟಿಎಮ್|ನಗದು"),
    ("recommend", r"recommend|suggest|what should i|what do i do|next best|campaign|offer|recover|win.?back|advice|how (can|do) i (fix|grow|improve)|सुझाव|सुझा|सलाह|क्या करूं|क्या करूँ|क्या करें|ऑफर|अभियान|ಸಲಹೆ|ಏನು ಮಾಡ|ಆಫರ್|ಅಭಿಯಾನ|kya karu|kya karun"),
    ("slot", r"\btime\b|slot|hours?\b|morning|afternoon|evening|busy|quiet|समय|सुबह|दोपहर|शाम|ಸಮಯ|ಬೆಳಿಗ್ಗೆ|ಮಧ್ಯಾಹ್ನ|ಸಂಜೆ"),
    ("day", r"\bdays?\b|weekday|monday|tuesday|wednesday|thursday|friday|saturday|sunday|दिन|ದಿನ"),
    ("customers", r"customer|footfall|visitor|visit|people|regulars?|lapsed|ग्राहक|कस्टमर|ಗ್ರಾಹಕ"),
    ("loss", r"loss|lost|lose|down|drop|dip|decline|fell|fall|why|नुकसान|गिरा|गिरावट|कम|घट|क्यों|क्यूं|ಕುಸಿ|ನಷ್ಟ|ಇಳಿ|ಕಡಿಮೆ|ಯಾಕೆ|ಏಕೆ"),
    ("sales", r"sale|revenue|earn|income|turnover|money|business|week|weak|बिक्री|कमाई|आमदनी|आय|बेच|हफ्त|सप्ताह|ಮಾರಾಟ|ಆದಾಯ|ಗಳಿಕೆ|ವಾರ"),
]


def detect_intent(text):
    t = text.lower().strip()
    for name, pattern in INTENT_PATTERNS:
        if re.search(pattern, t):
            return name
    return "help"


# --------------------------------------------------------------------------
# Real data snapshot (recomputed on every question so it is never stale)
# --------------------------------------------------------------------------
def _snapshot():
    customers = load_csv(os.path.join(DATA_DIR, "customers.csv"))
    transactions = load_csv(os.path.join(DATA_DIR, "transactions.csv"))

    weekly_totals = compute_weekly_sales(transactions)
    dip_pct, prev_total, last_total = compute_sales_dip(weekly_totals)

    weeks = list(weekly_customer_counts(transactions).items())
    cust_this = weeks[-1][1] if weeks else 0
    cust_normal = (sum(c for _, c in weeks[:-1]) / len(weeks[:-1])) if len(weeks) > 1 else cust_this

    pattern = analyze_sales_pattern(transactions)
    best_day, best_day_amt = pattern["best_day"]
    worst_day, worst_day_amt = pattern["worst_day"]
    (bsd, bsn), bsa = pattern["best_slot"]
    (wsd, wsn), wsa = pattern["worst_slot"]

    campaign = [c for c in customers if c["group"] == "campaign"]
    cash_only = [c for c in campaign if c["paytm_user"] == "False"]

    return {
        "customers": customers, "transactions": transactions,
        "dip": dip_pct, "normal_sales": prev_total, "sales": last_total,
        "loss": (prev_total - last_total) if prev_total and last_total else 0,
        "cust_this": cust_this, "cust_normal": cust_normal,
        "best_day": best_day, "best_day_amt": best_day_amt,
        "worst_day": worst_day, "worst_day_amt": worst_day_amt,
        "best_slot_day": bsd, "best_slot": bsn, "best_slot_amt": bsa,
        "worst_slot_day": wsd, "worst_slot": wsn, "worst_slot_amt": wsa,
        "lapsed": len(campaign), "cash_only": len(cash_only),
    }


def _day(name, lang):
    return DAY_NAME_TRANSLATIONS.get(name, {}).get(lang, name)


def _slot(name, lang):
    return SLOT_NAME_TRANSLATIONS.get(name, {}).get(lang, name.lower())


# --------------------------------------------------------------------------
# Answer templates — en / hi / kn
# --------------------------------------------------------------------------
T = {
    "greeting": {
        "en": "Namaste! I'm VyaparDost, your business partner. Ask me about this week's sales, your customers, your best day, upcoming festivals — or what I recommend you do next.",
        "hi": "नमस्ते! मैं व्यापारदोस्त हूं, आपका बिज़नेस पार्टनर। मुझसे इस हफ्ते की बिक्री, ग्राहकों, सबसे अच्छे दिन, त्योहारों के बारे में पूछिए — या पूछिए कि आगे मेरा क्या सुझाव है।",
        "kn": "ನಮಸ್ಕಾರ! ನಾನು ವ್ಯಾಪಾರದೋಸ್ತ್, ನಿಮ್ಮ ವ್ಯವಹಾರ ಪಾಲುದಾರ. ಈ ವಾರದ ಮಾರಾಟ, ಗ್ರಾಹಕರು, ನಿಮ್ಮ ಅತ್ಯುತ್ತಮ ದಿನ, ಹಬ್ಬಗಳ ಬಗ್ಗೆ ಕೇಳಿ — ಅಥವಾ ಮುಂದೆ ನನ್ನ ಸಲಹೆ ಏನು ಎಂದು ಕೇಳಿ.",
    },
    "help": {
        "en": "I can answer questions about your business. Try: how are my sales this week, why are sales down, how many customers came, which is my best day, when is my quietest time, is a festival coming up, or what do you recommend?",
        "hi": "मैं आपके व्यापार के बारे में सवालों के जवाब दे सकता हूं। पूछिए: इस हफ्ते की बिक्री कितनी है, बिक्री क्यों गिरी, कितने ग्राहक आए, सबसे अच्छा दिन कौन सा है, सबसे शांत समय कौन सा है, क्या कोई त्योहार आ रहा है, या आपका क्या सुझाव है?",
        "kn": "ನಿಮ್ಮ ವ್ಯವಹಾರದ ಬಗ್ಗೆ ಪ್ರಶ್ನೆಗಳಿಗೆ ನಾನು ಉತ್ತರಿಸಬಲ್ಲೆ. ಕೇಳಿ: ಈ ವಾರದ ಮಾರಾಟ ಎಷ್ಟು, ಮಾರಾಟ ಏಕೆ ಕಡಿಮೆಯಾಯಿತು, ಎಷ್ಟು ಗ್ರಾಹಕರು ಬಂದರು, ನನ್ನ ಅತ್ಯುತ್ತಮ ದಿನ ಯಾವುದು, ಅತ್ಯಂತ ಶಾಂತ ಸಮಯ ಯಾವುದು, ಹಬ್ಬ ಬರುತ್ತಿದೆಯೇ, ಅಥವಾ ನಿಮ್ಮ ಸಲಹೆ ಏನು?",
    },
    "sales": {
        "en": "This week your sales were {sales}, compared to {normal} in a normal week — that's {dip}% lower. {cust} customers visited, against about {cnormal} usually.",
        "hi": "इस हफ्ते आपकी बिक्री {sales} रही, जबकि सामान्य हफ्ते में {normal} होती है — यानी {dip}% कम। इस हफ्ते {cust} ग्राहक आए, जबकि आमतौर पर लगभग {cnormal} आते हैं।",
        "kn": "ಈ ವಾರ ನಿಮ್ಮ ಮಾರಾಟ {sales} ಆಗಿದೆ, ಸಾಮಾನ್ಯ ವಾರದಲ್ಲಿ {normal} ಇರುತ್ತದೆ — ಅಂದರೆ {dip}% ಕಡಿಮೆ. ಈ ವಾರ {cust} ಗ್ರಾಹಕರು ಬಂದಿದ್ದಾರೆ, ಸಾಮಾನ್ಯವಾಗಿ ಸುಮಾರು {cnormal} ಬರುತ್ತಾರೆ.",
    },
    "loss": {
        "en": "Sales are down {dip}% this week — you lost about {loss}. The main reason is regular customers who stopped visiting: {lapsed} of your regulars haven't come this week. Ask me what I recommend and I'll tell you how to win them back.",
        "hi": "इस हफ्ते बिक्री {dip}% कम हुई — लगभग {loss} का नुकसान। मुख्य कारण वे नियमित ग्राहक हैं जो नहीं आए: आपके {lapsed} नियमित ग्राहक इस हफ्ते नहीं आए। पूछिए कि मेरा क्या सुझाव है, मैं बताऊंगा कि उन्हें वापस कैसे लाना है।",
        "kn": "ಈ ವಾರ ಮಾರಾಟ {dip}% ಕಡಿಮೆಯಾಗಿದೆ — ಸುಮಾರು {loss} ನಷ್ಟ. ಮುಖ್ಯ ಕಾರಣ ಬರುವುದನ್ನು ನಿಲ್ಲಿಸಿದ ನಿಯಮಿತ ಗ್ರಾಹಕರು: ನಿಮ್ಮ {lapsed} ನಿಯಮಿತ ಗ್ರಾಹಕರು ಈ ವಾರ ಬಂದಿಲ್ಲ. ನನ್ನ ಸಲಹೆ ಏನು ಎಂದು ಕೇಳಿ, ಅವರನ್ನು ಮರಳಿ ತರುವುದು ಹೇಗೆ ಎಂದು ಹೇಳುತ್ತೇನೆ.",
    },
    "customers": {
        "en": "{cust} customers visited this week, compared to about {cnormal} in a normal week. {lapsed} regular customers have stopped visiting, and {cash} of them pay only in cash — so bringing them back with a Paytm offer can also add new Paytm users.",
        "hi": "इस हफ्ते {cust} ग्राहक आए, जबकि सामान्य हफ्ते में लगभग {cnormal} आते हैं। {lapsed} नियमित ग्राहकों ने आना बंद कर दिया है, और उनमें से {cash} सिर्फ नकद देते हैं — इसलिए पेटीएम ऑफर से उन्हें वापस लाने पर नए पेटीएम उपयोगकर्ता भी जुड़ सकते हैं।",
        "kn": "ಈ ವಾರ {cust} ಗ್ರಾಹಕರು ಬಂದಿದ್ದಾರೆ, ಸಾಮಾನ್ಯ ವಾರದಲ್ಲಿ ಸುಮಾರು {cnormal} ಬರುತ್ತಾರೆ. {lapsed} ನಿಯಮಿತ ಗ್ರಾಹಕರು ಬರುವುದನ್ನು ನಿಲ್ಲಿಸಿದ್ದಾರೆ, ಅವರಲ್ಲಿ {cash} ಮಂದಿ ನಗದು ಮಾತ್ರ ಕೊಡುತ್ತಾರೆ — ಆದ್ದರಿಂದ ಪೇಟಿಎಮ್ ಆಫರ್ ಮೂಲಕ ಅವರನ್ನು ಮರಳಿ ತಂದರೆ ಹೊಸ ಪೇಟಿಎಮ್ ಬಳಕೆದಾರರೂ ಸೇರುತ್ತಾರೆ.",
    },
    "day": {
        "en": "Your strongest day is {best_day} with {best_amt} in total sales, and your weakest is {worst_day} with {worst_amt}. This is across all the weeks in your data.",
        "hi": "आपका सबसे मजबूत दिन {best_day} है, कुल बिक्री {best_amt}, और सबसे कमजोर दिन {worst_day} है, कुल बिक्री {worst_amt}। यह आपके सभी हफ्तों के डेटा पर आधारित है।",
        "kn": "ನಿಮ್ಮ ಅತ್ಯಂತ ಪ್ರಬಲ ದಿನ {best_day}, ಒಟ್ಟು ಮಾರಾಟ {best_amt}, ಮತ್ತು ಅತ್ಯಂತ ದುರ್ಬಲ ದಿನ {worst_day}, ಒಟ್ಟು ಮಾರಾಟ {worst_amt}. ಇದು ನಿಮ್ಮ ಎಲ್ಲಾ ವಾರಗಳ ಡೇಟಾ ಆಧಾರಿತ.",
    },
    "slot": {
        "en": "Your best time slot is {bsd} {bs} at {bsa}, and your quietest is {wsd} {ws} at {wsa}. A small offer in the quiet slot could help fill it.",
        "hi": "आपका सबसे अच्छा समय {bsd} {bs} है, बिक्री {bsa}, और सबसे शांत समय {wsd} {ws} है, बिक्री {wsa}। शांत समय में एक छोटा ऑफर उसे भरने में मदद कर सकता है।",
        "kn": "ನಿಮ್ಮ ಅತ್ಯುತ್ತಮ ಸಮಯ {bsd} {bs}, ಮಾರಾಟ {bsa}, ಮತ್ತು ಅತ್ಯಂತ ಶಾಂತ ಸಮಯ {wsd} {ws}, ಮಾರಾಟ {wsa}. ಶಾಂತ ಸಮಯದಲ್ಲಿ ಸಣ್ಣ ಆಫರ್ ಅದನ್ನು ತುಂಬಲು ಸಹಾಯ ಮಾಡಬಹುದು.",
    },
    "festival_yes": {
        "en": "{name} is in {days} days, on {date}. For a {biz}, demand for {items} usually rises around this time — it's a good moment to stock up and run a festival offer.",
        "hi": "{name} {days} दिनों में है, {date} को। {biz} के लिए इस समय {items} की मांग आमतौर पर बढ़ती है — स्टॉक बढ़ाने और त्योहार ऑफर चलाने का अच्छा मौका है।",
        "kn": "{name} {days} ದಿನಗಳಲ್ಲಿ, {date} ರಂದು ಇದೆ. {biz} ಗೆ ಈ ಸಮಯದಲ್ಲಿ {items} ಬೇಡಿಕೆ ಸಾಮಾನ್ಯವಾಗಿ ಹೆಚ್ಚಾಗುತ್ತದೆ — ಸ್ಟಾಕ್ ಹೆಚ್ಚಿಸಲು ಮತ್ತು ಹಬ್ಬದ ಆಫರ್ ನಡೆಸಲು ಒಳ್ಳೆಯ ಸಮಯ.",
    },
    "festival_low": {
        "en": "{name} is in {days} days, on {date}. It's worth keeping in mind while planning your stock.",
        "hi": "{name} {days} दिनों में है, {date} को। अपना स्टॉक प्लान करते समय इसे ध्यान में रखें।",
        "kn": "{name} {days} ದಿನಗಳಲ್ಲಿ, {date} ರಂದು ಇದೆ. ನಿಮ್ಮ ಸ್ಟಾಕ್ ಯೋಜಿಸುವಾಗ ಇದನ್ನು ಗಮನದಲ್ಲಿಡಿ.",
    },
    "festival_none": {
        "en": "There's no major festival in the next 45 days.",
        "hi": "अगले 45 दिनों में कोई बड़ा त्योहार नहीं है।",
        "kn": "ಮುಂದಿನ 45 ದಿನಗಳಲ್ಲಿ ಯಾವುದೇ ದೊಡ್ಡ ಹಬ್ಬ ಇಲ್ಲ.",
    },
    "memory_yes": {
        "en": "Your last campaign was '{action}' with a {disc} discount. {rate}% of customers returned, and it worked best with {seg} customers, recovering {rev}.",
        "hi": "आपका पिछला अभियान '{action}' था, {disc} की छूट के साथ। {rate}% ग्राहक वापस आए, और यह {seg} के ग्राहकों के साथ सबसे अच्छा रहा, {rev} की वसूली हुई।",
        "kn": "ನಿಮ್ಮ ಹಿಂದಿನ ಅಭಿಯಾನ '{action}', {disc} ರಿಯಾಯಿತಿಯೊಂದಿಗೆ. {rate}% ಗ್ರಾಹಕರು ಮರಳಿ ಬಂದರು, ಮತ್ತು ಇದು {seg} ಗ್ರಾಹಕರೊಂದಿಗೆ ಅತ್ಯುತ್ತಮವಾಗಿತ್ತು, {rev} ಮರಳಿ ಪಡೆಯಲಾಯಿತು.",
    },
    "memory_none": {
        "en": "I don't have a past campaign on record yet. Once you approve and run one, I'll remember what worked.",
        "hi": "मेरे पास अभी कोई पिछला अभियान दर्ज नहीं है। जब आप कोई अभियान चलाएंगे, मैं याद रखूंगा कि क्या काम किया।",
        "kn": "ನನ್ನ ಬಳಿ ಇನ್ನೂ ಯಾವುದೇ ಹಿಂದಿನ ಅಭಿಯಾನ ದಾಖಲಾಗಿಲ್ಲ. ನೀವು ಒಂದನ್ನು ನಡೆಸಿದ ನಂತರ, ಏನು ಕೆಲಸ ಮಾಡಿತು ಎಂದು ನಾನು ನೆನಪಿಡುತ್ತೇನೆ.",
    },
    "paytm": {
        "en": "{cash} of the {lapsed} lapsed customers I'd target are cash-only. The offer only works when they pay through Paytm, so every one who comes back and redeems it becomes a new Paytm user.",
        "hi": "जिन {lapsed} पुराने ग्राहकों को मैं लक्षित करूंगा, उनमें से {cash} सिर्फ नकद देते हैं। ऑफर तभी काम करता है जब वे पेटीएम से भुगतान करें, इसलिए जो भी लौटकर इसे इस्तेमाल करेगा वह नया पेटीएम उपयोगकर्ता बन जाएगा।",
        "kn": "ನಾನು ಗುರಿಯಾಗಿಸುವ {lapsed} ಹಳೆಯ ಗ್ರಾಹಕರಲ್ಲಿ {cash} ಮಂದಿ ನಗದು ಮಾತ್ರ ಕೊಡುತ್ತಾರೆ. ಅವರು ಪೇಟಿಎಮ್ ಮೂಲಕ ಪಾವತಿಸಿದಾಗ ಮಾತ್ರ ಆಫರ್ ಕೆಲಸ ಮಾಡುತ್ತದೆ, ಆದ್ದರಿಂದ ಮರಳಿ ಬಂದು ಬಳಸುವ ಪ್ರತಿಯೊಬ್ಬರೂ ಹೊಸ ಪೇಟಿಎಮ್ ಬಳಕೆದಾರರಾಗುತ್ತಾರೆ.",
    },
    "recommend": {
        "en": "Sales are down {dip}%. I compared three ways to recover. {action} looks strongest — targeting {target} customers, expected to bring back about {opp}, roughly {rec}% of the {loss} you lost. The other options are {a2} at {o2} and {a3} at {o3}. A {disc} offer stays within your {budget} budget and {maxdisc} discount limits.",
        "hi": "बिक्री {dip}% कम है। मैंने ठीक करने के तीन तरीके देखे। {action} सबसे मजबूत लग रहा है — {target} ग्राहकों को लक्षित करके, लगभग {opp} वापस आने की उम्मीद है, जो आपके {loss} के नुकसान का लगभग {rec}% है। बाकी विकल्प हैं {a2}, {o2} के साथ, और {a3}, {o3} के साथ। {disc} की छूट आपके {budget} के बजट और {maxdisc} की छूट सीमा के भीतर है।",
        "kn": "ಮಾರಾಟ {dip}% ಕಡಿಮೆಯಾಗಿದೆ. ಇದನ್ನು ಸರಿಪಡಿಸಲು ನಾನು ಮೂರು ಮಾರ್ಗಗಳನ್ನು ಹೋಲಿಸಿದೆ. {action} ಅತ್ಯಂತ ಪ್ರಬಲವಾಗಿ ಕಾಣುತ್ತದೆ — {target} ಗ್ರಾಹಕರನ್ನು ಗುರಿಯಾಗಿಸಿ, ಸುಮಾರು {opp} ಮರಳಿ ಪಡೆಯುವ ನಿರೀಕ್ಷೆ ಇದೆ, ಇದು ನಿಮ್ಮ {loss} ನಷ್ಟದ ಸುಮಾರು {rec}%. ಇತರ ಆಯ್ಕೆಗಳು {a2}, {o2} ಜೊತೆ, ಮತ್ತು {a3}, {o3} ಜೊತೆ. {disc} ರಿಯಾಯಿತಿ ನಿಮ್ಮ {budget} ಬಜೆಟ್ ಮತ್ತು {maxdisc} ರಿಯಾಯಿತಿ ಮಿತಿಯೊಳಗೆ ಇದೆ.",
    },
}

# Segment names as they appear in memory ("Afternoon") -> spoken form
def _seg(name, lang):
    return SLOT_NAME_TRANSLATIONS.get(name, {}).get(lang, str(name).lower())


def _festival_answer(lang):
    hit = check_upcoming_festival(__import__("datetime").date.today(), days_ahead=45)
    if not hit:
        return T["festival_none"][lang]
    fest_date, name, days = hit
    biz = BUSINESS_TYPES["4"]  # General Store / Kirana — same default as the dashboard
    key = "festival_yes" if name in HIGH_DEMAND_FESTIVALS else "festival_low"
    return T[key][lang].format(
        name=name, days=days, date=fest_date.strftime("%d %B"),
        biz=biz["name"], items=biz["festival_items"],
    )


def _memory_answer(lang):
    rec = _read_local_memory()
    if not rec:
        return T["memory_none"][lang]
    return T["memory_yes"][lang].format(
        action=ACTION_TRANSLATIONS.get(rec.get("action"), {}).get(lang, rec.get("action")),
        disc=_inr(rec.get("discount", 0)),
        rate=f"{rec.get('return_rate', 0):.0f}",
        seg=_seg(rec.get("best_segment", ""), lang),
        rev=_inr(rec.get("revenue_recovered", 0)),
    )


def _recommend_answer(s, lang):
    options = generate_next_best_actions(s["customers"], s["transactions"])
    top, second, third = options[0], options[1], options[2]
    tr = lambda o: ACTION_TRANSLATIONS.get(o["action"], {}).get(lang, o["action"])
    recovery_pct = (top["expected_opportunity"] / s["loss"] * 100) if s["loss"] else 0
    return T["recommend"][lang].format(
        dip=f"{s['dip']:.0f}", action=tr(top),
        target=len(top["target_group"]) if top["target_group"] else s["lapsed"],
        opp=_inr(top["expected_opportunity"]), rec=f"{recovery_pct:.0f}", loss=_inr(s["loss"]),
        a2=tr(second), o2=_inr(second["expected_opportunity"]),
        a3=tr(third), o3=_inr(third["expected_opportunity"]),
        disc=_inr(OFFER_DISCOUNT), budget=_inr(MAX_CAMPAIGN_BUDGET), maxdisc=_inr(MAX_DISCOUNT_PER_OFFER),
    )


def answer_question(text, lang="en"):
    """
    Main entry point used by the Flask endpoint.
    Returns {"answer": str, "intent": str, "lang": "en"|"hi"|"kn"}.
    """
    lang = detect_lang(text, lang)
    intent = detect_intent(text)

    if intent in ("greeting", "help"):
        return {"answer": T[intent][lang], "intent": intent, "lang": lang}
    if intent == "festival":
        return {"answer": _festival_answer(lang), "intent": intent, "lang": lang}
    if intent == "memory":
        return {"answer": _memory_answer(lang), "intent": intent, "lang": lang}

    s = _snapshot()
    common = dict(
        sales=_inr(s["sales"]), normal=_inr(s["normal_sales"]), dip=f"{s['dip']:.0f}",
        loss=_inr(s["loss"]), cust=s["cust_this"], cnormal=f"{s['cust_normal']:.0f}",
        lapsed=s["lapsed"], cash=s["cash_only"],
    )

    if intent == "recommend":
        answer = _recommend_answer(s, lang)
    elif intent == "day":
        answer = T["day"][lang].format(
            best_day=_day(s["best_day"], lang), best_amt=_inr(s["best_day_amt"]),
            worst_day=_day(s["worst_day"], lang), worst_amt=_inr(s["worst_day_amt"]),
        )
    elif intent == "slot":
        answer = T["slot"][lang].format(
            bsd=_day(s["best_slot_day"], lang), bs=_slot(s["best_slot"], lang), bsa=_inr(s["best_slot_amt"]),
            wsd=_day(s["worst_slot_day"], lang), ws=_slot(s["worst_slot"], lang), wsa=_inr(s["worst_slot_amt"]),
        )
    else:  # sales, loss, customers, paytm
        answer = T[intent][lang].format(**common)

    return {"answer": answer, "intent": intent, "lang": lang}


if __name__ == "__main__":
    # Quick terminal test:  python engine/voice_agent.py
    for q in ["What are my sales this week?", "Why are sales down?", "Which is my best day?",
              "What do you recommend?", "इस हफ्ते की बिक्री कितनी है?", "ಈ ವಾರದ ಮಾರಾಟ ಎಷ್ಟು?"]:
        r = answer_question(q, "en")
        print(f"\nQ: {q}\n[{r['intent']}/{r['lang']}] {r['answer']}")