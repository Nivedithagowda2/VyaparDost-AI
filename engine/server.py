"""
VyaparDost — local dashboard server.

Serves the frontend (frontend/dashboard.html) and a small REST API that
computes live numbers from the same CSVs and modules run_demo.py uses
(decision_engine, memory) — so the dashboard is never showing hardcoded
placeholder data.

The Voice tab now has TWO parts:
  1. "Talk to VyaparDost" — a live voice agent. The browser records the
     merchant's voice, /api/voice/stt turns it into text (Sarvam), 
     /api/voice/ask answers it from the real data (voice_agent.py), and
     /api/voice/tts speaks the answer (Sarvam). Typing works too.
  2. "Last terminal run" — the saved report from `python engine/run_demo.py`
     (data/last_run_report.json), which is still where the approval +
     campaign launch flow lives.

Usage:
    pip install flask --break-system-packages
    python engine/server.py
    -> open http://127.0.0.1:5000 in a browser
"""

import base64
import calendar
import io
import json
import os
import sys
import wave
from collections import defaultdict
from datetime import date

from flask import Flask, Response, jsonify, send_from_directory, request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from decision_engine import load_csv, compute_weekly_sales, compute_sales_dip, DATA_DIR
from run_demo import (
    weekly_customer_counts, analyze_sales_pattern, check_upcoming_festival,
    BUSINESS_TYPES,
)
from memory import recall_last_campaign_insight
from voice_agent import answer_question
import sarvam_voice as sv
import payment_check as pc

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".env"))
except ImportError:
    pass

FRONTEND_DIR = os.path.normpath(
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "frontend")
)

app = Flask(__name__)


def _load_data():
    customers = load_csv(os.path.join(DATA_DIR, "customers.csv"))
    transactions = load_csv(os.path.join(DATA_DIR, "transactions.csv"))
    return customers, transactions


def _monthly_totals(transactions):
    """
    Groups revenue by calendar month. Flags a month as partial if the
    data doesn't actually cover that month's full first-to-last day
    range, so the frontend can label "Jul (partial)" honestly instead
    of implying every bar is a complete month.
    """
    by_month = defaultdict(float)
    dates_by_month = defaultdict(list)
    for t in transactions:
        d = date.fromisoformat(t["date"])
        key = (d.year, d.month)
        by_month[key] += float(t["amount"])
        dates_by_month[key].append(d)

    result = []
    for (y, m) in sorted(by_month.keys()):
        days = dates_by_month[(y, m)]
        first_of_month = date(y, m, 1)
        last_day_num = calendar.monthrange(y, m)[1]
        last_of_month = date(y, m, last_day_num)
        is_partial = min(days) > first_of_month or max(days) < last_of_month
        label = date(y, m, 1).strftime("%b %Y") + (" (partial)" if is_partial else "")
        result.append({"label": label, "value": round(by_month[(y, m)], 2), "partial": is_partial})
    return result


@app.route("/")
def index():
    return send_from_directory(FRONTEND_DIR, "dashboard.html")


@app.route("/api/overview")
def api_overview():
    customers, transactions = _load_data()

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

    pattern = analyze_sales_pattern(transactions)
    best_day, best_day_amt = pattern["best_day"]
    worst_day, worst_day_amt = pattern["worst_day"]
    (best_slot_day, best_slot_name), best_slot_amt = pattern["best_slot"]
    (worst_slot_day, worst_slot_name), worst_slot_amt = pattern["worst_slot"]

    day_totals = {
        day: {
            "Morning": round(pattern["by_day_slot"].get((day, "Morning"), 0.0), 2),
            "Afternoon": round(pattern["by_day_slot"].get((day, "Afternoon"), 0.0), 2),
            "Evening": round(pattern["by_day_slot"].get((day, "Evening"), 0.0), 2),
        }
        for day, _ in pattern["day_totals"]
    }

    return jsonify({
        "this_week": {"customers": customers_this_week, "sales": round(last_total, 2)},
        "normal_week": {"customers": round(customers_normal, 1) if customers_normal else None,
                         "sales": round(prev_total, 2)},
        "loss_amount": round(loss_amount, 2) if loss_amount else None,
        "dip_pct": round(dip_pct, 1),
        "best_day": {"name": best_day, "amount": round(best_day_amt, 2)},
        "worst_day": {"name": worst_day, "amount": round(worst_day_amt, 2)},
        "best_slot": {"day": best_slot_day, "slot": best_slot_name, "amount": round(best_slot_amt, 2)},
        "worst_slot": {"day": worst_slot_day, "slot": worst_slot_name, "amount": round(worst_slot_amt, 2)},
        "day_totals": day_totals,
    })


@app.route("/api/trends")
def api_trends():
    _, transactions = _load_data()
    weekly_totals = compute_weekly_sales(transactions)
    weekly = [{"label": wk.strftime("%d %b"), "value": round(amt, 2)} for wk, amt in sorted(weekly_totals.items())]
    monthly = _monthly_totals(transactions)
    return jsonify({"weekly": weekly, "monthly": monthly})


@app.route("/api/festival")
def api_festival():
    _, transactions = _load_data()
    business_name = request.args.get("business", "General Store / Kirana")
    business = next((b for b in BUSINESS_TYPES.values() if b["name"] == business_name), BUSINESS_TYPES["4"])

    from run_demo import HIGH_DEMAND_FESTIVALS
    today_real = date.today()
    hit = check_upcoming_festival(today_real, days_ahead=45)
    if not hit:
        return jsonify({"available": False})

    fest_date, fest_name, days_until = hit
    return jsonify({
        "available": True,
        "name": fest_name,
        "date": fest_date.isoformat(),
        "days_until": days_until,
        "is_high_demand": fest_name in HIGH_DEMAND_FESTIVALS,
        "suggested_items": business["festival_items"],
        "business_name": business["name"],
    })


@app.route("/api/memory")
def api_memory():
    text, source = recall_last_campaign_insight()
    if not text:
        return jsonify({"available": False})
    return jsonify({"available": True, "text": text, "source": source})


@app.route("/api/last-run")
def api_last_run():
    report_path = os.path.join(DATA_DIR, "last_run_report.json")
    if not os.path.exists(report_path):
        return jsonify({"available": False})
    try:
        with open(report_path, "r", encoding="utf-8") as f:
            report = json.load(f)
        report["available"] = True
        return jsonify(report)
    except Exception as e:
        return jsonify({"available": False, "error": str(e)})


# ---------------------------------------------------------------------------
# VOICE AGENT ENDPOINTS  (browser mic -> text -> answer -> spoken audio)
# ---------------------------------------------------------------------------
LANG_TO_SARVAM = {"en": "en-IN", "hi": "hi-IN", "kn": "kn-IN"}


def _merge_wavs(wav_chunks):
    """Sarvam may return long text as several WAV files; join them properly."""
    if len(wav_chunks) == 1:
        return wav_chunks[0]
    out = io.BytesIO()
    with wave.open(io.BytesIO(wav_chunks[0]), "rb") as first:
        params = first.getparams()
    with wave.open(out, "wb") as w:
        w.setparams(params)
        for chunk in wav_chunks:
            with wave.open(io.BytesIO(chunk), "rb") as r:
                w.writeframes(r.readframes(r.getnframes()))
    return out.getvalue()


@app.route("/api/voice/status")
def api_voice_status():
    """Lets the page know whether real Sarvam voice is available."""
    return jsonify({"sarvam": bool(sv.SARVAM_API_KEY)})


@app.route("/api/voice/ask", methods=["POST"])
def api_voice_ask():
    """Question text in -> answer text out, built from the real data."""
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Empty question"}), 400
    try:
        return jsonify(answer_question(text, body.get("lang", "en")))
    except Exception as e:
        return jsonify({"error": f"Could not answer: {e}"}), 500


@app.route("/api/voice/stt", methods=["POST"])
def api_voice_stt():
    """Speech-to-text: browser sends a 16 kHz mono WAV, Sarvam returns text."""
    if not sv.SARVAM_API_KEY:
        return jsonify({"error": "SARVAM_API_KEY is not set in .env"}), 503
    audio = request.files.get("audio")
    if audio is None:
        return jsonify({"error": "No audio received"}), 400
    lang = LANG_TO_SARVAM.get(request.form.get("lang", "en"), "en-IN")
    try:
        import requests
        resp = requests.post(
            sv.SARVAM_STT_ENDPOINT,
            headers={"api-subscription-key": sv.SARVAM_API_KEY},
            files={"file": ("speech.wav", audio.read(), "audio/wav")},
            data={"model": sv.SARVAM_STT_MODEL, "language_code": lang, "mode": "transcribe"},
            timeout=30,
        )
        resp.raise_for_status()
        transcript = (resp.json().get("transcript") or "").strip()
        if not transcript:
            return jsonify({"error": "No speech detected"}), 422
        return jsonify({"transcript": transcript})
    except Exception as e:
        return jsonify({"error": f"Sarvam speech-to-text failed: {e}"}), 502


@app.route("/api/voice/tts", methods=["POST"])
def api_voice_tts():
    """Text-to-speech: returns WAV audio the browser can play directly."""
    if not sv.SARVAM_API_KEY:
        return jsonify({"error": "SARVAM_API_KEY is not set in .env"}), 503
    body = request.get_json(silent=True) or {}
    text = (body.get("text") or "").strip()
    if not text:
        return jsonify({"error": "Empty text"}), 400
    lang = LANG_TO_SARVAM.get(body.get("lang", "en"), "en-IN")
    try:
        import requests
        resp = requests.post(
            sv.SARVAM_TTS_ENDPOINT,
            headers={"api-subscription-key": sv.SARVAM_API_KEY, "Content-Type": "application/json"},
            json={
                "text": text[:2400],
                "target_language_code": lang,
                "speaker": sv.SARVAM_SPEAKER,
                "model": sv.SARVAM_TTS_MODEL,
            },
            timeout=30,
        )
        resp.raise_for_status()
        parts = resp.json().get("audios") or []
        if not parts:
            return jsonify({"error": "Sarvam returned no audio"}), 502
        wav = _merge_wavs([base64.b64decode(p) for p in parts])
        return Response(wav, mimetype="audio/wav")
    except Exception as e:
        return jsonify({"error": f"Sarvam text-to-speech failed: {e}"}), 502


# ---------------------------------------------------------------------------
# PAYMENT CHECK  (fraud protection — fake / recycled screenshot detection)
# ---------------------------------------------------------------------------
@app.route("/api/payment/sms-webhook", methods=["POST"])
def api_payment_sms_webhook():
    """
    THE EASY AUTOMATION PATH. Point a phone-automation app (MacroDroid,
    Tasker, etc.) at this URL, forwarding the raw SMS text your bank/UPI
    app sends whenever a payment is credited — no regex setup needed on
    the phone, all parsing happens here so it can be fixed centrally.
    Accepts either JSON {"sms": "..."} or a plain form field "sms".
    """
    body = request.get_json(silent=True) or {}
    text = body.get("sms") or request.form.get("sms") or request.values.get("sms") or ""
    if not text.strip():
        return jsonify({"ok": False, "error": "No 'sms' text received"}), 400
    entry = pc.receive_from_sms(text)
    if entry is None:
        return jsonify({"ok": False, "error": "Could not find an amount in this SMS — send it to Claude to fix the pattern", "sms": text[:300]}), 422
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/payment/webhook", methods=["POST"])
def api_payment_webhook():
    """
    THE REAL ENTRY POINT. Point your live Paytm webhook URL here once you
    have a Paytm for Business account with API access:
      1. Sign up at business.paytm.com and complete KYC.
      2. In Dashboard -> Developer Settings, get your Merchant ID (MID)
         and Merchant Key, and register a webhook URL.
      3. Paytm requires that URL to be a public HTTPS address — a
         localhost URL will not work, so for testing before you deploy
         anywhere, run `ngrok http 5000` and register the ngrok URL.
      4. Paytm signs every webhook call with a checksum using your
         Merchant Key — verify it before trusting the payload (this is
         where that check belongs; it's a straightforward HMAC/checksum
         verification, using Paytm's official checksum utility for
         whichever SDK you use).
    Until then, this endpoint exists and works, but nothing calls it —
    use /api/payment/simulate to demo the same effect.
    """
    body = request.get_json(silent=True) or {}
    amount = body.get("amount")
    txn_id = body.get("txn_id") or body.get("TXNID") or body.get("ORDERID")
    if amount is None:
        return jsonify({"error": "amount is required"}), 400
    entry = pc.receive_payment(amount, txn_id=txn_id, source="webhook")
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/payment/simulate", methods=["POST"])
def api_payment_simulate():
    """
    Demo-only: stands in for the real webhook above. Lets you demo the
    ✅ Received path without a live Paytm feed.
    """
    body = request.get_json(silent=True) or {}
    amount = body.get("amount")
    txn_id = body.get("txn_id")
    if amount is None:
        return jsonify({"error": "amount is required"}), 400
    entry = pc.simulate_incoming_payment(amount, txn_id=txn_id)
    return jsonify({"ok": True, "entry": entry})


@app.route("/api/payment/peek", methods=["POST"])
def api_payment_peek():
    """
    Read-only check used by the frontend's short auto-retry window (see
    payment_check.peek_payment). Never claims a payment, never logs a
    fraud attempt — purely "has it landed yet?" for polling.
    """
    body = request.get_json(silent=True) or {}
    amount = body.get("amount")
    txn_id = body.get("txn_id")
    if amount is None:
        return jsonify({"error": "amount is required"}), 400
    found = pc.peek_payment(amount, txn_id=txn_id)
    return jsonify({"found": found})


@app.route("/api/payment/check", methods=["POST"])
def api_payment_check():
    """The actual fraud check: does a real payment (amount + optional txn ID) exist?"""
    body = request.get_json(silent=True) or {}
    amount = body.get("amount")
    txn_id = body.get("txn_id")
    if amount is None:
        return jsonify({"error": "amount is required"}), 400
    result = pc.check_payment(amount, txn_id=txn_id)
    result["summary"] = pc.fraud_summary()
    return jsonify(result)


@app.route("/api/payment/fraud-log")
def api_payment_fraud_log():
    return jsonify(pc.fraud_summary())


@app.route("/api/payment/latest")
def api_payment_latest():
    """
    Polled by the dashboard every few seconds so a new payment can be
    announced on screen automatically, with nobody typing anything —
    this is what a real Paytm webhook push effectively gives you live.
    """
    after = request.args.get("after")
    entries = pc.unclaimed_since(after)
    return jsonify({"entries": entries, "server_time": pc._now().isoformat()})


if __name__ == "__main__":
    dashboard_path = os.path.join(FRONTEND_DIR, "dashboard.html")
    if not os.path.exists(dashboard_path):
        print(f"WARNING: dashboard.html not found at: {dashboard_path}")
        print("Make sure the file sits at frontend/dashboard.html, directly next to your engine/ folder.")
    else:
        print(f"Serving dashboard from: {dashboard_path}")
    port = int(os.environ.get("PORT", 5000))
    print(f"VyaparDost dashboard running at http://127.0.0.1:{port}")
    print("(Run `python engine/run_demo.py` separately in another terminal for the voice-guided flow)")
    print("(0.0.0.0 binding below lets your phone reach /api/payment/webhook over WiFi — see the SMS-forwarding setup)")
    app.run(host="0.0.0.0", port=port, debug=False)