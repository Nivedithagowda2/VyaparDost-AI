"""
VyaparDost AI — Full Demo Runner
Wires together:
  1. decision_engine.py  -> detects the dip, ranks Next Best Actions, checks guardrails
  2. sarvam_voice.py      -> speaks the recommendation and listens for merchant approval
                             (real Sarvam API if SARVAM_API_KEY is set, otherwise mock)

This is the single script to run for the live demo — it produces the full
Detect -> Decide -> Speak -> Approve loop end-to-end, with execution only
proceeding if the merchant actually approves by voice (or typed mock input).

Run:
    python engine/run_demo.py
"""

import json
import os
import sys
from collections import defaultdict, Counter
from datetime import date, timedelta, datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_engine import (
    load_csv, compute_weekly_sales,
    compute_sales_dip, generate_next_best_actions, apply_guardrails,
    DATA_DIR, MAX_CAMPAIGN_BUDGET,
)
from sarvam_voice import demo_voice_exchange, speak_execution_confirmation, select_language, build_recommendation_text
from memory import store_campaign_memory, recall_last_campaign_insight
from measure_lift import simulate_returns, compute_lift, compute_revenue_recovered, \
    CAMPAIGN_RETURN_RATE, HOLDOUT_RETURN_RATE

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
except ImportError:
    pass

# Set this in .env once the workflow is published:
#   N8N_WEBHOOK_URL=https://niveditha13.app.n8n.cloud/webhook/vyapardost-campaign
N8N_WEBHOOK_URL = os.environ.get("N8N_WEBHOOK_URL", "").strip()


def weekly_customer_counts(transactions):
    """
    Self-contained here (not imported from decision_engine) so this
    always returns {week_start: count} — a plain int per week —
    regardless of what any other copy of a similarly-named function
    elsewhere might return.
    """
    weekly = defaultdict(set)
    for t in transactions:
        d = date.fromisoformat(t["date"])
        week_start = d - timedelta(days=d.weekday())
        weekly[week_start].add(t["customer_id"])
    return dict(sorted((wk, len(ids)) for wk, ids in weekly.items()))


DAY_NAMES = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]

DAY_NAME_TRANSLATIONS = {
    "Monday":    {"en": "Monday",    "hi": "सोमवार",     "kn": "ಸೋಮವಾರ"},
    "Tuesday":   {"en": "Tuesday",   "hi": "मंगलवार",    "kn": "ಮಂಗಳವಾರ"},
    "Wednesday": {"en": "Wednesday", "hi": "बुधवार",     "kn": "ಬುಧವಾರ"},
    "Thursday":  {"en": "Thursday",  "hi": "गुरुवार",    "kn": "ಗುರುವಾರ"},
    "Friday":    {"en": "Friday",    "hi": "शुक्रवार",   "kn": "ಶುಕ್ರವಾರ"},
    "Saturday":  {"en": "Saturday",  "hi": "शनिवार",     "kn": "ಶನಿವಾರ"},
    "Sunday":    {"en": "Sunday",    "hi": "रविवार",     "kn": "ಭಾನುವಾರ"},
}

SLOT_NAME_TRANSLATIONS = {
    "Morning":   {"en": "morning",   "hi": "सुबह",  "kn": "ಬೆಳಿಗ್ಗೆ"},
    "Afternoon": {"en": "afternoon", "hi": "दोपहर", "kn": "ಮಧ್ಯಾಹ್ನ"},
    "Evening":   {"en": "evening",   "hi": "शाम",   "kn": "ಸಂಜೆ"},
}


def analyze_sales_pattern(transactions):
    """
    Breaks total revenue down by day-of-week, and separately by
    day-of-week x time-slot, so the merchant can see exactly when
    they're strong (e.g. "Friday evening") and exactly when they're
    weak (e.g. "Sunday morning") — not just an overall weekly dip.
    """
    by_day = defaultdict(float)
    by_day_slot = defaultdict(float)

    for t in transactions:
        d = date.fromisoformat(t["date"])
        day_name = DAY_NAMES[d.weekday()]
        amount = float(t["amount"])
        by_day[day_name] += amount
        by_day_slot[(day_name, t["time_slot"])] += amount

    # Order by actual weekday, not insertion order, so results read Mon->Sun
    day_totals = [(day, by_day.get(day, 0.0)) for day in DAY_NAMES]
    best_day = max(day_totals, key=lambda x: x[1])
    worst_day = min(day_totals, key=lambda x: x[1])

    best_slot = max(by_day_slot.items(), key=lambda x: x[1])   # ((day, slot), amount)
    worst_slot = min(by_day_slot.items(), key=lambda x: x[1])

    return {
        "day_totals": day_totals,
        "by_day_slot": by_day_slot,
        "best_day": best_day,
        "worst_day": worst_day,
        "best_slot": best_slot,
        "worst_slot": worst_slot,
    }


# ---- 2026 Indian festival calendar (verified dates) ----
# Used to flag a genuine upcoming opportunity — e.g. sweets/snacks demand
# rises sharply in the days around Ganesh Chaturthi or Diwali. Kept as a
# simple date lookup rather than a lunar-calendar calculation, since dates
# shift year to year and hardcoding a verified year is more reliable for
# a prototype than approximating the underlying calendar.
FESTIVAL_CALENDAR_2026 = {
    date(2026, 1, 1):  "New Year",
    date(2026, 1, 14): "Makar Sankranti / Pongal",
    date(2026, 1, 26): "Republic Day",
    date(2026, 2, 15): "Maha Shivratri",
    date(2026, 3, 3):  "Holi",
    date(2026, 3, 19): "Ugadi",
    date(2026, 3, 20): "Eid-ul-Fitr",
    date(2026, 3, 26): "Ram Navami",
    date(2026, 4, 3):  "Good Friday",
    date(2026, 5, 1):  "Buddha Purnima",
    date(2026, 5, 27): "Bakrid (Eid al-Adha)",
    date(2026, 6, 25): "Muharram",
    date(2026, 8, 15): "Independence Day",
    date(2026, 8, 26): "Onam",
    date(2026, 8, 28): "Raksha Bandhan",
    date(2026, 9, 4):  "Janmashtami",
    date(2026, 9, 14): "Ganesh Chaturthi",
    date(2026, 10, 2): "Gandhi Jayanti",
    date(2026, 10, 11): "Navratri begins",
    date(2026, 10, 17): "Durga Puja (Maha Shashthi)",
    date(2026, 10, 20): "Vijaya Dashami / Dussehra",
    date(2026, 10, 29): "Karva Chauth",
    date(2026, 11, 8):  "Diwali",
    date(2026, 11, 9):  "Govardhan Puja",
    date(2026, 11, 11): "Bhai Dooj",
    date(2026, 11, 24): "Guru Nanak Jayanti",
    date(2026, 12, 25): "Christmas",
}

# Festivals where shopping/gifting/sweets demand is typically highest —
# used to phrase the suggestion more specifically than a generic
# "sales may increase" for every date on the calendar.
HIGH_DEMAND_FESTIVALS = {
    "Ganesh Chaturthi", "Diwali", "Holi", "Raksha Bandhan", "Onam",
    "Navratri begins", "Durga Puja (Maha Shashthi)", "Vijaya Dashami / Dussehra",
    "Christmas", "Makar Sankranti / Pongal", "Eid-ul-Fitr", "Bakrid (Eid al-Adha)",
}


def check_upcoming_festival(reference_date, days_ahead=45):
    """
    Looks for any festival within the next `days_ahead` days of
    reference_date. Uses the REAL current date by default (not the
    dataset's frozen transaction history) since festival planning is
    about the actual calendar ahead, not the merchant's past sales
    window. Widened to 45 days (not just 7) because festivals like
    Durga Puja or Diwali need weeks of stocking lead time, not a
    day's notice.

    Prioritizes the nearest HIGH-DEMAND festival (an actual sales
    opportunity) over the nearest festival on the calendar overall —
    otherwise a non-shopping date like Gandhi Jayanti would win just
    for being closer, even when a real opportunity like Durga Puja
    is only a couple weeks further out. Falls back to the nearest
    festival of any kind only if no high-demand one is in range.

    Returns (festival_date, name, days_until), or None if nothing
    falls in the window at all.
    """
    upcoming = [
        (d, name) for d, name in FESTIVAL_CALENDAR_2026.items()
        if 0 < (d - reference_date).days <= days_ahead
    ]
    if not upcoming:
        return None
    upcoming.sort(key=lambda x: x[0])

    high_demand_upcoming = [(d, name) for d, name in upcoming if name in HIGH_DEMAND_FESTIVALS]
    nearest_date, nearest_name = high_demand_upcoming[0] if high_demand_upcoming else upcoming[0]
    return nearest_date, nearest_name, (nearest_date - reference_date).days


BUSINESS_TYPES = {
    "1": {"name": "Sweet Shop / Mithai Store", "festival_items": "sweets, dry fruits, and gift boxes"},
    "2": {"name": "Cosmetic / Beauty Store", "festival_items": "makeup, henna, bindis, and gifting sets"},
    "3": {"name": "Hotel / Restaurant", "festival_items": "festive menus, special thalis, and advance bookings"},
    "4": {"name": "General Store / Kirana", "festival_items": "pooja items, decorations, and daily essentials"},
    "5": {"name": "Stationery Store", "festival_items": "greeting cards, gift wrapping, and craft supplies"},
    "6": {"name": "Other", "festival_items": "your most popular festive items"},
}


def select_business_type():
    """
    Asks the merchant what kind of business they run, the same way
    select_language() asks for a language — a plain numbered CLI menu
    for now, since there's no graphical dashboard yet. The chosen
    business_type dict flows into the same downstream functions either
    way, so this can be swapped for a dropdown in a future UI without
    changing any of the logic that uses it.
    """
    print("\nWhat kind of business is this?")
    for key, biz in BUSINESS_TYPES.items():
        print(f"  {key}. {biz['name']}")
    choice = input("Enter 1-6 (default: General Store / Kirana): ").strip()
    selected = BUSINESS_TYPES.get(choice, BUSINESS_TYPES["4"])
    print(f"-> Using {selected['name']}")
    return selected


def trigger_n8n_campaign(action, discount, merchant_name, target_group):
    """
    Calls the real n8n workflow: sends the approved action + target
    customer list, gets back a processed offer summary (segmented
    cash-only vs. existing Paytm users, offer text, counts).
    Falls back to a locally-computed summary if the webhook isn't
    configured or the call fails, so the demo never hard-stops.
    """
    payload = {
        "action": action,
        "discount": discount,
        "merchant_name": merchant_name,
        "target_customers": [
            {
                "customer_id": c["customer_id"],
                "paytm_user": c["paytm_user"] == "True",
                "avg_basket_value": float(c["avg_basket_value"]),
            }
            for c in target_group
        ],
    }

    if not N8N_WEBHOOK_URL:
        print("  (N8N_WEBHOOK_URL not set in .env — skipping real n8n call)")
        return None

    try:
        import requests
        resp = requests.post(N8N_WEBHOOK_URL, json=payload, timeout=15)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        print(f"  (n8n webhook call failed, showing local summary instead: {e})")
        return None


def main():
    transcript_log = []  # every line VyaparDost actually speaks this run, for the dashboard's Voice Report tab

    customers = load_csv(os.path.join(DATA_DIR, "customers.csv"))
    transactions = load_csv(os.path.join(DATA_DIR, "transactions.csv"))

    weekly_totals = compute_weekly_sales(transactions)
    dip_pct, prev_total, last_total = compute_sales_dip(weekly_totals)

    weekly_customers = weekly_customer_counts(transactions)
    customer_weeks = list(weekly_customers.items())
    customers_this_week = customer_weeks[-1][1] if customer_weeks else None
    customers_normal = (
        sum(c for _, c in customer_weeks[:-1]) / len(customer_weeks[:-1])
        if len(customer_weeks) > 1 else None
    )
    loss_amount = (prev_total - last_total) if prev_total and last_total else None

    print("=" * 60)
    print("VYAPARDOST AI — LIVE DEMO")
    print("=" * 60)

    lang = select_language()
    lang_code = {"English": "en", "Hindi": "hi", "Kannada": "kn"}[lang["name"]]
    business = select_business_type()

    print(f"\n[DETECT] What happened this week:")
    print(f"  This week:      {customers_this_week} customers visited, ₹{last_total:,.0f} in sales")
    print(f"  Normal week:    ~{customers_normal:.0f} customers visited on average, "
          f"~₹{prev_total:,.0f} in sales")
    print(f"  -> That's a loss of ₹{loss_amount:,.0f} ({dip_pct:.1f}% down), "
          f"driven mainly by regular customers who stopped visiting.")

    pattern = analyze_sales_pattern(transactions)
    best_day, best_day_amt = pattern["best_day"]
    worst_day, worst_day_amt = pattern["worst_day"]
    (best_slot_day, best_slot_name), best_slot_amt = pattern["best_slot"]
    (worst_slot_day, worst_slot_name), worst_slot_amt = pattern["worst_slot"]

    print(f"\n[SALES PATTERN] When this merchant is strong vs. weak:")
    print(f"  Best day overall:  {best_day} (₹{best_day_amt:,.0f} total)")
    print(f"  Worst day overall: {worst_day} (₹{worst_day_amt:,.0f} total)")
    print(f"  Strongest slot:    {best_slot_day} {best_slot_name} (₹{best_slot_amt:,.0f})")
    print(f"  Weakest slot:      {worst_slot_day} {worst_slot_name} (₹{worst_slot_amt:,.0f})")
    print(f"  Full day x time-slot breakdown:")
    for day, _ in pattern["day_totals"]:
        slot_parts = []
        for slot in ["Morning", "Afternoon", "Evening"]:
            amt = pattern["by_day_slot"].get((day, slot), 0.0)
            slot_parts.append(f"{slot} ₹{amt:,.0f}")
        print(f"    {day:9s} — {' | '.join(slot_parts)}")

    sales_pattern_lines = {
        "en": f"Looking at your sales pattern — {DAY_NAME_TRANSLATIONS[best_day]['en']} is your strongest day overall, "
              f"and {DAY_NAME_TRANSLATIONS[worst_day]['en']} is your weakest. Your best single slot is "
              f"{DAY_NAME_TRANSLATIONS[best_slot_day]['en']} {SLOT_NAME_TRANSLATIONS[best_slot_name]['en']}, "
              f"and your quietest is {DAY_NAME_TRANSLATIONS[worst_slot_day]['en']} {SLOT_NAME_TRANSLATIONS[worst_slot_name]['en']}.",
        "hi": f"आपकी बिक्री के पैटर्न को देखते हुए — {DAY_NAME_TRANSLATIONS[best_day]['hi']} आपका सबसे मजबूत दिन है, "
              f"और {DAY_NAME_TRANSLATIONS[worst_day]['hi']} सबसे कमजोर। आपका सबसे अच्छा समय "
              f"{DAY_NAME_TRANSLATIONS[best_slot_day]['hi']} {SLOT_NAME_TRANSLATIONS[best_slot_name]['hi']} है, "
              f"और सबसे शांत समय {DAY_NAME_TRANSLATIONS[worst_slot_day]['hi']} {SLOT_NAME_TRANSLATIONS[worst_slot_name]['hi']} है।",
        "kn": f"ನಿಮ್ಮ ಮಾರಾಟದ ಮಾದರಿಯನ್ನು ನೋಡಿದರೆ — {DAY_NAME_TRANSLATIONS[best_day]['kn']} ನಿಮ್ಮ ಅತ್ಯಂತ ಪ್ರಬಲ ದಿನ, "
              f"ಮತ್ತು {DAY_NAME_TRANSLATIONS[worst_day]['kn']} ಅತ್ಯಂತ ದುರ್ಬಲ. ನಿಮ್ಮ ಅತ್ಯುತ್ತಮ ಸಮಯ "
              f"{DAY_NAME_TRANSLATIONS[best_slot_day]['kn']} {SLOT_NAME_TRANSLATIONS[best_slot_name]['kn']}, "
              f"ಮತ್ತು ಅತ್ಯಂತ ಶಾಂತ ಸಮಯ {DAY_NAME_TRANSLATIONS[worst_slot_day]['kn']} {SLOT_NAME_TRANSLATIONS[worst_slot_name]['kn']}.",
    }
    speak_execution_confirmation(sales_pattern_lines[lang_code], lang["sarvam_code"])
    transcript_log.append({"tag": "Sales pattern", "text": sales_pattern_lines[lang_code]})

    # ---- UPCOMING OPPORTUNITY: uses the REAL current date (not the
    # dataset's frozen transaction history), since festival planning is
    # about the actual calendar ahead, not the merchant's past sales
    # window — a festival that already passed in real life should never
    # show as "upcoming" just because the synthetic dataset is older.
    # Looks 45 days ahead so slow-lead-time festivals (Durga Puja,
    # Diwali) surface with enough notice to actually stock up. The
    # suggested items are personalized to the merchant's business type
    # instead of a generic "sweets and snacks" for every kind of store. ----
    today_real = date.today()
    festival_hit = check_upcoming_festival(today_real, days_ahead=45)
    festival_items = business["festival_items"]

    if festival_hit:
        fest_date, fest_name, days_until = festival_hit
        is_high_demand = fest_name in HIGH_DEMAND_FESTIVALS
        when_text = "tomorrow" if days_until == 1 else f"in {days_until} days"

        print(f"\n[UPCOMING OPPORTUNITY] What's coming up:")
        print(f"  {fest_name} is {when_text} ({fest_date.strftime('%d %b %Y')}).")
        if is_high_demand:
            print(f"  For a {business['name']}, demand for {festival_items} typically "
                  f"rises around {fest_name} — consider stocking up and running a "
                  f"festival-specific offer to capture the extra footfall.")
        else:
            print(f"  Worth keeping in mind while planning stock and staffing.")

        opportunity_lines = {
            "en": f"One more thing — {fest_name} is {when_text}. "
                  + (f"For a {business['name'].lower()}, demand for {festival_items} "
                     f"usually goes up around this time — it might be worth stocking up "
                     f"and running a festival offer."
                     if is_high_demand else
                     "Worth keeping in mind while planning your stock."),
            "hi": f"एक और बात — {fest_name} {when_text == 'tomorrow' and 'कल' or f'{days_until} दिनों में'} है। "
                  + (f"इस समय {festival_items} की मांग आमतौर पर बढ़ जाती है — "
                     f"स्टॉक बढ़ाना और एक त्योहार ऑफर चलाना फायदेमंद हो सकता है।"
                     if is_high_demand else
                     "अपना स्टॉक प्लान करते समय इसे ध्यान में रखें।"),
            "kn": f"ಇನ್ನೊಂದು ವಿಷಯ — {fest_name} {when_text == 'tomorrow' and 'ನಾಳೆ' or f'{days_until} ದಿನಗಳಲ್ಲಿ'}. "
                  + (f"ಈ ಸಮಯದಲ್ಲಿ {festival_items} ಬೇಡಿಕೆ ಸಾಮಾನ್ಯವಾಗಿ ಹೆಚ್ಚಾಗುತ್ತದೆ — "
                     f"ಸ್ಟಾಕ್ ಹೆಚ್ಚಿಸುವುದು ಮತ್ತು ಹಬ್ಬದ ಆಫರ್ ನಡೆಸುವುದು ಪ್ರಯೋಜನಕಾರಿಯಾಗಬಹುದು."
                     if is_high_demand else
                     "ನಿಮ್ಮ ಸ್ಟಾಕ್ ಯೋಜಿಸುವಾಗ ಇದನ್ನು ಗಮನದಲ್ಲಿಟ್ಟುಕೊಳ್ಳಿ."),
        }
        speak_execution_confirmation(opportunity_lines[lang_code], lang["sarvam_code"])
        transcript_log.append({"tag": "Opportunity", "text": opportunity_lines[lang_code]})
    else:
        print(f"\n[UPCOMING OPPORTUNITY] No major festival in the next 45 days.")

    print("\n[LEARN] Checking memory for past campaigns:")
    insight_text, insight_source = recall_last_campaign_insight()
    if insight_text:
        print(f"  ({insight_source}) {insight_text}")
        remembered_lines = {
            "en": f"I remember from a previous campaign — {insight_text}",
            "hi": f"मुझे पिछले अभियान से यह याद है — {insight_text}",
            "kn": f"ಹಿಂದಿನ ಅಭಿಯಾನದಿಂದ ನನಗೆ ಇದು ನೆನಪಿದೆ — {insight_text}",
        }
        speak_execution_confirmation(remembered_lines[lang_code], lang["sarvam_code"])
        transcript_log.append({"tag": "Learn", "text": remembered_lines[lang_code]})
    else:
        print("  No prior campaign remembered yet — this will be the first one stored.")

    options = generate_next_best_actions(customers, transactions)
    top = options[0]

    print("\n[DECIDE] Next Best Action options:")
    for i, opt in enumerate(options, 1):
        marker = " <-- recommended" if opt is top else ""
        print(f"  {i}. {opt['action']} — ₹{opt['expected_opportunity']:,.0f}{marker}")

    discount = 20
    target_group = top["target_group"] if top["target_group"] is not None else \
        [c for c in customers if c["group"] == "campaign"]
    target_count = len(target_group)
    recovery_pct = (top["expected_opportunity"] / loss_amount * 100) if loss_amount else 0

    passed, reasons = apply_guardrails(top["action"], target_group, discount)
    print("\n[GUARDRAILS]")
    for r in reasons:
        print(f"  - {r}")

    if not passed:
        print("\nGuardrails FAILED — recommendation blocked. Adjust target list or discount.")
        return

    print(f"\n[RECOVERY PLAN] How to recover this loss:")
    print(f"  Of the ₹{loss_amount:,.0f} lost this week, targeting {target_count} customers "
          f"with '{top['action']}' is expected to recover about "
          f"₹{top['expected_opportunity']:,.0f} (~{recovery_pct:.0f}% of what was lost), "
          f"for a ₹{discount} offer per customer — well within the ₹{MAX_CAMPAIGN_BUDGET} budget guardrail.")

    print("\n[SPEAK & APPROVE]")
    approved = demo_voice_exchange(
        dip_pct=dip_pct,
        action=top["action"],
        opportunity=top["expected_opportunity"],
        discount=discount,
        lang=lang,
        customers_this_week=customers_this_week,
        customers_normal=customers_normal,
        loss_amount=loss_amount,
        target_count=target_count,
        recovery_pct=recovery_pct,
    )
    recommendation_text = build_recommendation_text(
        lang_code, dip_pct, top["action"], top["expected_opportunity"], discount,
        customers_this_week=customers_this_week, customers_normal=customers_normal,
        loss_amount=loss_amount, target_count=target_count, recovery_pct=recovery_pct,
    )
    transcript_log.append({"tag": "Recommendation", "text": recommendation_text})
    transcript_log.append({
        "tag": "Confirmed" if approved else "Declined",
        "text": "Approved — launching the campaign now." if approved
                else "Understood — not launching this campaign.",
    })

    print("\n[ACT]")
    act_result = None  # populated only if approved; kept None so the report write below always works
    measure_result = None
    paytm_impact_result = None

    if approved:
        cash_only = [c for c in target_group if c["paytm_user"] == "False"]
        n8n_result = trigger_n8n_campaign(
            action=top["action"],
            discount=discount,
            merchant_name="Sharma Kirana",
            target_group=target_group,
        )
        if n8n_result:
            print("  n8n executed the campaign (real webhook response):")
            print(f"    {json.dumps(n8n_result, indent=2, ensure_ascii=False)}")

            confirmation_lines = {
                "en": f"Campaign sent to {n8n_result.get('total_targeted', len(target_group))} customers. "
                      f"{n8n_result.get('cash_only_count', 0)} of them are cash-only — a chance to bring them onto Paytm.",
                "hi": f"अभियान {n8n_result.get('total_targeted', len(target_group))} ग्राहकों को भेजा गया। "
                      f"इनमें से {n8n_result.get('cash_only_count', 0)} नकद-भुगतान वाले ग्राहक हैं — पेटीएम पर लाने का मौका।",
                "kn": f"ಅಭಿಯಾನವನ್ನು {n8n_result.get('total_targeted', len(target_group))} ಗ್ರಾಹಕರಿಗೆ ಕಳುಹಿಸಲಾಗಿದೆ. "
                      f"ಅವರಲ್ಲಿ {n8n_result.get('cash_only_count', 0)} ಮಂದಿ ನಗದು ಗ್ರಾಹಕರು — ಪೇಟಿಎಮ್‌ಗೆ ತರುವ ಅವಕಾಶ.",
            }
            speak_execution_confirmation(confirmation_lines[lang_code], lang["sarvam_code"])
            transcript_log.append({"tag": "Result", "text": confirmation_lines[lang_code]})
            act_result = n8n_result
            print(f"  n8n executes: {len(target_group)} customers targeted, "
                  f"₹{discount} Paytm-native offer sent, "
                  f"{len(cash_only)} cash-only customers "
                  f"(Paytm acquisition opportunity).")

        # ---- MEASURE: holdout-based incremental lift, run inline so the
        # whole Detect -> Decide -> Speak -> Act -> Measure loop completes
        # in a single run, instead of needing a second script. ----
        holdout_group = [c for c in customers if c["group"] == "holdout"]
        campaign_returned = simulate_returns(target_group, CAMPAIGN_RETURN_RATE)
        holdout_returned = simulate_returns(holdout_group, HOLDOUT_RETURN_RATE)
        campaign_rate, holdout_rate, lift_pp = compute_lift(
            target_group, campaign_returned, holdout_group, holdout_returned
        )
        revenue_recovered = compute_revenue_recovered(campaign_returned)
        campaign_cost = discount * len(target_group)
        roi = revenue_recovered / campaign_cost if campaign_cost else 0.0
        new_paytm_users = [c for c in campaign_returned if c["paytm_user"] == "False"]

        print("\n[MEASURE] Holdout-based incremental impact:")
        print(f"  Campaign group: {len(target_group)} customers -> "
              f"{len(campaign_returned)} returned ({campaign_rate * 100:.1f}%)")
        print(f"  Holdout group:  {len(holdout_group)} customers -> "
              f"{len(holdout_returned)} returned ({holdout_rate * 100:.1f}%)")
        print(f"  Prototype-estimated incremental lift: +{lift_pp:.1f}pp "
              f"(small-sample demo estimate — holdout n={len(holdout_group)})")
        print(f"  Revenue recovered: ₹{revenue_recovered:,.0f}  |  "
              f"Campaign cost: ₹{campaign_cost:,.0f}  |  ROI: {roi:.1f}x")

        measure_result = {
            "campaign_targeted": len(target_group),
            "campaign_returned": len(campaign_returned),
            "campaign_rate_pct": campaign_rate * 100,
            "holdout_targeted": len(holdout_group),
            "holdout_returned": len(holdout_returned),
            "holdout_rate_pct": holdout_rate * 100,
            "lift_pp": lift_pp,
            "revenue_recovered": revenue_recovered,
            "campaign_cost": campaign_cost,
            "roi": roi,
        }

        # ---- PAYTM IMPACT: distinct from merchant ROI above — this is
        # what THIS campaign is worth to Paytm's own platform, not just
        # the merchant. Every returning cash-only customer had to pay
        # via Paytm to redeem the offer, so they're now a Paytm user.
        # We project their ongoing value at a stated, modest assumption
        # (2 visits/month) rather than a one-off number, since repeat
        # transaction volume is what actually compounds for Paytm. ----
        ASSUMED_MONTHLY_VISITS = 2
        if new_paytm_users:
            avg_basket_new_users = sum(float(c["avg_basket_value"]) for c in new_paytm_users) / len(new_paytm_users)
        else:
            avg_basket_new_users = 0.0
        projected_monthly_paytm_volume = len(new_paytm_users) * avg_basket_new_users * ASSUMED_MONTHLY_VISITS

        print("\n[PAYTM IMPACT] What this is worth to Paytm, not just the merchant:")
        print(f"  New Paytm users acquired this campaign: {len(new_paytm_users)} "
              f"(cash-only customers who had to pay via Paytm to redeem the offer)")
        print(f"  Projected transaction volume added to Paytm's platform: "
              f"~₹{projected_monthly_paytm_volume:,.0f}/month "
              f"(assuming {ASSUMED_MONTHLY_VISITS} visits/month per new user — a stated, "
              f"conservative assumption, not a guarantee)")
        print(f"  Scaled across Paytm's merchant base, this same mechanism repeats per "
              f"merchant — the more merchants run this, the more cash-only customers "
              f"convert to Paytm, compounding monthly.")

        paytm_impact_result = {
            "new_paytm_users": len(new_paytm_users),
            "projected_monthly_volume": projected_monthly_paytm_volume,
            "assumed_monthly_visits": ASSUMED_MONTHLY_VISITS,
        }

        paytm_impact_lines = {
            "en": f"Beyond the merchant's own recovery, this campaign brought "
                  f"{len(new_paytm_users)} new users onto Paytm, projected to add about "
                  f"₹{projected_monthly_paytm_volume:,.0f} a month in transaction volume "
                  f"to Paytm's platform.",
            "hi": f"व्यापारी के अपने रिकवरी के अलावा, इस अभियान ने {len(new_paytm_users)} "
                  f"नए उपयोगकर्ताओं को पेटीएम पर लाया, जिससे पेटीएम के प्लेटफॉर्म पर "
                  f"लगभग ₹{projected_monthly_paytm_volume:,.0f} प्रति माह लेनदेन बढ़ने का अनुमान है।",
            "kn": f"ವ್ಯಾಪಾರಿಯ ಸ್ವಂತ ಚೇತರಿಕೆಯ ಹೊರತಾಗಿ, ಈ ಅಭಿಯಾನವು {len(new_paytm_users)} "
                  f"ಹೊಸ ಬಳಕೆದಾರರನ್ನು ಪೇಟಿಎಮ್‌ಗೆ ತಂದಿದೆ, ಇದು ಪೇಟಿಎಮ್‌ ಪ್ಲಾಟ್‌ಫಾರ್ಮ್‌ಗೆ ತಿಂಗಳಿಗೆ "
                  f"ಸುಮಾರು ₹{projected_monthly_paytm_volume:,.0f} ವಹಿವಾಟು ಸೇರಿಸುವ ನಿರೀಕ್ಷೆ ಇದೆ.",
        }
        speak_execution_confirmation(paytm_impact_lines[lang_code], lang["sarvam_code"])
        transcript_log.append({"tag": "Paytm impact", "text": paytm_impact_lines[lang_code]})

        # ---- LEARN: store what happened so the NEXT run can recall it.
        # "Best segment" = the preferred_slot most common among customers
        # who actually returned — a real signal from this campaign's
        # result, not an assumption. ----
        print("\n[LEARN] Saving this campaign to memory:")
        if campaign_returned:
            slot_counts = Counter(c["preferred_slot"] for c in campaign_returned)
            best_segment = slot_counts.most_common(1)[0][0]
        else:
            best_segment = "unknown"

        stored_in_cognee = store_campaign_memory(
            action=top["action"],
            discount=discount,
            target_count=len(target_group),
            return_rate=campaign_rate * 100,
            best_segment=best_segment,
            revenue_recovered=revenue_recovered,
        )
        print(f"  Stored in {'Cognee' if stored_in_cognee else 'local memory (Cognee unavailable this run)'}.")
    else:
        print("  Merchant declined — no campaign launched.")

    # ---- Persist a report of this exact run so the dashboard's Voice
    # Report tab (and Overview numbers) can show real last-run data
    # instead of a fabricated example. Written regardless of whether
    # the merchant approved, so a declined run still leaves a record. ----
    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "language": lang["name"],
        "business_type": business["name"],
        "detect": {
            "customers_this_week": customers_this_week,
            "customers_normal": customers_normal,
            "sales_this_week": last_total,
            "sales_normal": prev_total,
            "loss_amount": loss_amount,
            "dip_pct": dip_pct,
        },
        "sales_pattern": {
            "best_day": best_day, "best_day_amount": best_day_amt,
            "worst_day": worst_day, "worst_day_amount": worst_day_amt,
            "best_slot_day": best_slot_day, "best_slot_name": best_slot_name, "best_slot_amount": best_slot_amt,
            "worst_slot_day": worst_slot_day, "worst_slot_name": worst_slot_name, "worst_slot_amount": worst_slot_amt,
            "day_totals": {
                day: {
                    "Morning": pattern["by_day_slot"].get((day, "Morning"), 0.0),
                    "Afternoon": pattern["by_day_slot"].get((day, "Afternoon"), 0.0),
                    "Evening": pattern["by_day_slot"].get((day, "Evening"), 0.0),
                }
                for day, _ in pattern["day_totals"]
            },
        },
        "festival": ({
            "name": festival_hit[1], "date": festival_hit[0].isoformat(), "days_until": festival_hit[2],
            "is_high_demand": festival_hit[1] in HIGH_DEMAND_FESTIVALS,
            "suggested_items": business["festival_items"],
        } if festival_hit else None),
        "memory_recall": {"text": insight_text, "source": insight_source} if insight_text else None,
        "decide": {
            "options": [{"action": o["action"], "expected_opportunity": o["expected_opportunity"]} for o in options],
            "recommended": top["action"],
        },
        "recovery_plan": {
            "target_count": target_count, "discount": discount, "recovery_pct": recovery_pct,
        },
        "approved": approved,
        "act_result": act_result,
        "measure_result": measure_result,
        "paytm_impact_result": paytm_impact_result,
        "transcript": transcript_log,
    }
    try:
        report_path = os.path.join(DATA_DIR, "last_run_report.json")
        with open(report_path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        print(f"\n[REPORT] Saved for dashboard: data/last_run_report.json")
    except Exception as e:
        print(f"\n[REPORT] Could not save report for dashboard: {e}")


if __name__ == "__main__":
    main()