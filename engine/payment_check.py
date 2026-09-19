"""
VyaparDost AI — Payment Check (fraud protection)

The real problem this solves: a customer shows the merchant a payment
screen — sometimes a genuine one, sometimes an edited screenshot, a
cancelled transaction, or a fake "demo mode" payment app — and the
merchant hands over goods before the money has actually landed.

The only real proof of payment is the credit showing in the merchant's
own account, not a screen the customer holds up. So this module never
looks at any image or claim — it only ever answers one question:
"has a payment of this amount (and, if given, this transaction ID)
actually landed?"

THREE ways data gets into the ledger:
  1. /api/payment/webhook  — the REAL entry point. This is what a live
     Paytm merchant account calls automatically the instant a payment
     lands (see the note in server.py for exactly what's needed to
     wire this up for real).
  2. /api/payment/simulate — the DEMO stand-in for #1, since this
     project runs on a synthetic dataset with no live Paytm feed.
  3. Nothing else. The dashboard's polling (/api/payment/latest) only
     READS the ledger — it can't add fake entries.

Storage: two small JSON files next to the CSVs.
  data/live_ledger.json  — recent payments (real webhook or simulated)
  data/fraud_log.json    — every check that did NOT find a real payment
"""

import json
import os
import random
import re
import string
import uuid
from datetime import datetime, timedelta

from decision_engine import DATA_DIR

LEDGER_PATH = os.path.join(DATA_DIR, "live_ledger.json")
FRAUD_LOG_PATH = os.path.join(DATA_DIR, "fraud_log.json")

MATCH_WINDOW_MINUTES = 10   # how far back a matching payment still counts
AMOUNT_TOLERANCE = 1.0      # ₹ — allow tiny rounding differences


def _now():
    return datetime.now()


def _load_json(path):
    if not os.path.exists(path):
        return []
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return []


def _save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


def load_ledger():
    return _load_json(LEDGER_PATH)


def load_fraud_log():
    return _load_json(FRAUD_LOG_PATH)


def _fake_txn_id():
    return "TXN" + "".join(random.choices(string.digits, k=6))


def receive_payment(amount, txn_id=None, source="webhook"):
    """
    Adds a new incoming payment to the ledger. This is the single real
    entry point — called either by the real Paytm webhook (production)
    or by the /api/payment/simulate demo button (prototype).
    """
    ledger = load_ledger()
    entry = {
        "id": uuid.uuid4().hex[:8],
        "txn_id": txn_id or _fake_txn_id(),
        "amount": round(float(amount), 2),
        "received_at": _now().isoformat(),
        "claimed": False,
        "claimed_at": None,
        "source": source,  # "webhook" (real) or "simulated" (demo)
    }
    ledger.append(entry)
    _save_json(LEDGER_PATH, ledger)
    return entry


# kept for backward compatibility with the demo button's old name
def simulate_incoming_payment(amount, txn_id=None):
    return receive_payment(amount, txn_id=txn_id, source="simulated")


def _log_fraud_attempt(amount, txn_id, result, note):
    log = load_fraud_log()
    log.append({
        "id": uuid.uuid4().hex[:8],
        "amount": round(float(amount), 2),
        "txn_id": txn_id,
        "checked_at": _now().isoformat(),
        "result": result,   # "not_found" or "already_used"
        "note": note,
    })
    _save_json(FRAUD_LOG_PATH, log)
    return log


def peek_payment(amount, txn_id=None):
    """
    Read-only lookup used for the frontend's short auto-retry window,
    so a payment that's a few seconds behind (SMS delay, phone/server
    hiccup) doesn't get wrongly logged as a fraud attempt just because
    the check happened slightly too early. Does NOT claim the entry and
    does NOT write to the fraud log — it only answers "does a matching,
    unclaimed payment exist right now?" so the caller knows whether to
    keep waiting. The real check_payment() below is still the only
    function that actually claims a payment or logs a fraud attempt.
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return False

    txn_id_clean = (txn_id or "").strip().upper() or None
    ledger = load_ledger()
    now = _now()
    cutoff = now - timedelta(minutes=MATCH_WINDOW_MINUTES)

    for entry in ledger:
        if entry["claimed"]:
            continue
        if txn_id_clean:
            if entry["txn_id"].upper() == txn_id_clean:
                return True
        else:
            if abs(entry["amount"] - amount) <= AMOUNT_TOLERANCE:
                if datetime.fromisoformat(entry["received_at"]) >= cutoff:
                    return True
    return False


def check_payment(amount, txn_id=None):
    """
    The core check. If txn_id is given, it must match exactly — this is
    what actually stops two different customers both claiming the same
    amount, or a customer reusing someone else's real transaction ID.
    If txn_id is left blank, matching falls back to amount + time window
    (weaker, but still catches "nothing like this was ever paid").

    Returns one of:
      received      -> a genuine, unclaimed payment matched. Safe to
                        hand over the goods.
      already_used  -> this payment WAS received, but has already been
                        matched to an earlier sale (reused screenshot).
      not_found     -> no matching payment exists at all. Do not
                        release goods yet.
    """
    try:
        amount = float(amount)
    except (TypeError, ValueError):
        return {"status": "error", "message": "Enter a valid amount"}

    txn_id = (txn_id or "").strip().upper() or None
    ledger = load_ledger()
    now = _now()
    cutoff = now - timedelta(minutes=MATCH_WINDOW_MINUTES)

    def matches(entry):
        if txn_id:
            return entry["txn_id"].upper() == txn_id
        return abs(entry["amount"] - amount) <= AMOUNT_TOLERANCE

    # 1) unclaimed + matches + (if no txn_id given) recent enough
    for entry in ledger:
        if entry["claimed"] or not matches(entry):
            continue
        if not txn_id:
            if datetime.fromisoformat(entry["received_at"]) < cutoff:
                continue
        entry["claimed"] = True
        entry["claimed_at"] = now.isoformat()
        _save_json(LEDGER_PATH, ledger)
        received_at = datetime.fromisoformat(entry["received_at"])
        return {
            "status": "received",
            "amount": entry["amount"],
            "txn_id": entry["txn_id"],
            "received_minutes_ago": round((now - received_at).total_seconds() / 60, 1),
        }

    # 2) already claimed before -> reused screenshot / replayed txn id
    for entry in ledger:
        if not entry["claimed"] or not matches(entry):
            continue
        note = (f"Transaction {entry['txn_id']} was already used for an earlier sale."
                if txn_id else f"₹{amount:.0f} matches a transaction already used for an earlier sale.")
        _log_fraud_attempt(amount, txn_id, "already_used", note)
        return {
            "status": "already_used",
            "amount": amount,
            "txn_id": entry["txn_id"],
            "originally_claimed_at": entry["claimed_at"],
        }

    # 3) nothing matches at all
    note = (f"No payment found for transaction ID {txn_id}." if txn_id
            else f"No ₹{amount:.0f} payment received in the last {MATCH_WINDOW_MINUTES} minutes.")
    _log_fraud_attempt(amount, txn_id, "not_found", note)
    return {"status": "not_found", "amount": amount, "txn_id": txn_id, "window_minutes": MATCH_WINDOW_MINUTES}


def fraud_summary():
    log = load_fraud_log()
    now = _now()
    this_month = [
        e for e in log
        if datetime.fromisoformat(e["checked_at"]).month == now.month
        and datetime.fromisoformat(e["checked_at"]).year == now.year
    ]
    return {
        "count_this_month": len(this_month),
        "amount_saved_this_month": round(sum(e["amount"] for e in this_month), 2),
        "count_all_time": len(log),
        "amount_saved_all_time": round(sum(e["amount"] for e in log), 2),
        "recent": sorted(log, key=lambda e: e["checked_at"], reverse=True)[:20],
    }


def unclaimed_since(after_iso):
    """
    Used by the dashboard's live-notification polling: any payment that
    landed after `after_iso` and hasn't been claimed by a check yet.
    This is what lets the page announce a payment with no one typing
    anything — the same thing a real Paytm webhook push would drive.
    """
    ledger = load_ledger()
    if not after_iso:
        return [e for e in ledger if not e["claimed"]]
    cutoff = datetime.fromisoformat(after_iso)
    return [
        e for e in ledger
        if not e["claimed"] and datetime.fromisoformat(e["received_at"]) > cutoff
    ]


# ---------------------------------------------------------------------------
# SMS parsing — the realistic automation path.
#
# A real Paytm/bank UPI credit SMS looks something like:
#   "Rs.450.00 credited to your A/c ...1234 on 19-09-26 by UPI Ref No 512847293841."
#   "You have received Rs 450 via UPI. UPI Ref No: 512847293841 - Paytm"
# A phone-automation app (e.g. MacroDroid) forwards the WHOLE SMS text
# here — no regex configuration needed on the phone — and this function
# does the actual extraction, so it can be fixed centrally if a
# particular bank's wording doesn't match.
# ---------------------------------------------------------------------------
_AMOUNT_PATTERNS = [
    r"(?:rs\.?|inr)\s*([\d,]+(?:\.\d+)?)\s*(?:has been\s*)?(?:credited|received)",
    r"(?:credited|received)\D{0,15}(?:rs\.?|inr)\s*([\d,]+(?:\.\d+)?)",
]
_TXN_ID_PATTERNS = [
    r"upi\s*ref(?:erence)?\.?\s*(?:no\.?)?\s*[:\-]?\s*(\w+)",
    r"ref(?:erence)?\s*(?:no\.?|id)\.?\s*[:\-]?\s*(\w+)",
    r"txn\s*id\.?\s*[:\-]?\s*(\w+)",
]


def parse_sms(text):
    """Returns (amount, txn_id) — either may be None if not found."""
    t = text.lower()
    amount = None
    for pat in _AMOUNT_PATTERNS:
        m = re.search(pat, t)
        if m:
            amount = float(m.group(1).replace(",", ""))
            break
    txn_id = None
    for pat in _TXN_ID_PATTERNS:
        m = re.search(pat, t, re.IGNORECASE)
        if m:
            txn_id = m.group(1).upper()
            break
    return amount, txn_id


def receive_from_sms(text):
    """
    Parses a forwarded SMS and, if an amount was found, adds it to the
    ledger exactly like a real webhook would. Returns the ledger entry,
    or None if no amount could be parsed (e.g. it wasn't a payment SMS).
    """
    amount, txn_id = parse_sms(text)
    if amount is None:
        return None
    entry = receive_payment(amount, txn_id=txn_id, source="sms")
    entry["raw_sms"] = text[:300]
    return entry