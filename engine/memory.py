"""
VyaparDost — Learn module (Cognee memory).

Stores what happened in each campaign (action, discount, best-performing
segment, return rate) and recalls it before the next recommendation, so
VyaparDost can say something like:
    "Previous ₹20 campaign worked best with evening customers —
     I recommend the same segment again."

Real Cognee (add -> cognify -> search) is used when configured. A local
JSON file is ALWAYS also written as a fallback, so a live demo never
goes silent just because of a network hiccup or a slow cognify run —
the same pattern already used for the n8n webhook and Sarvam voice calls
elsewhere in this project.
"""

import json
import os
from datetime import datetime

try:
    import requests
except ImportError:
    requests = None

COGNEE_BASE_URL = os.environ.get("COGNEE_BASE_URL", "").strip().rstrip("/")
COGNEE_API_KEY = os.environ.get("COGNEE_API_KEY", "").strip()
COGNEE_TENANT_ID = os.environ.get("COGNEE_TENANT_ID", "").strip()
COGNEE_DATASET = os.environ.get("COGNEE_DATASET", "vyapardost_campaigns").strip()

LOCAL_MEMORY_FILE = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "..", "data", "local_memory.json"
)


def _cognee_configured():
    return bool(COGNEE_BASE_URL and COGNEE_API_KEY and requests is not None)


def _headers():
    headers = {"Content-Type": "application/json", "X-Api-Key": COGNEE_API_KEY}
    if COGNEE_TENANT_ID:
        headers["X-Tenant-Id"] = COGNEE_TENANT_ID
    return headers


def _multipart_headers():
    """
    Cognee's /api/v1/add ONLY accepts multipart/form-data (confirmed via
    its OpenAPI spec) — it does not read a JSON body at all, which is
    exactly why sending datasetName inside json={} was silently ignored
    ("Either datasetId or datasetName must be provided" even though it
    was "provided", just in the wrong format). No Content-Type header
    here — requests sets the correct multipart boundary automatically
    when using the files= parameter, and forcing application/json here
    would break that.
    """
    headers = {"X-Api-Key": COGNEE_API_KEY}
    if COGNEE_TENANT_ID:
        headers["X-Tenant-Id"] = COGNEE_TENANT_ID
    return headers


def _write_local_memory(record):
    try:
        os.makedirs(os.path.dirname(LOCAL_MEMORY_FILE), exist_ok=True)
        with open(LOCAL_MEMORY_FILE, "w", encoding="utf-8") as f:
            json.dump(record, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"  (local memory fallback write failed: {e})")


def _read_local_memory():
    try:
        with open(LOCAL_MEMORY_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _raise_with_detail(resp):
    """
    requests' default HTTPError message ("409 Client Error: Conflict
    for url: ...") hides Cognee's actual explanation. Cognee's own
    error bodies carry a 'detail' field naming the real cause (and
    sometimes a 'remediation' hint) — this surfaces that instead of
    the generic message, so failures are diagnosable instead of
    guessed at.
    """
    try:
        resp.raise_for_status()
    except requests.exceptions.HTTPError as e:
        try:
            body = resp.json()
            detail = body.get("detail") or body.get("error") or body
            remediation = body.get("remediation")
        except Exception:
            detail = resp.text
            remediation = None
        msg = f"{resp.status_code}: {detail}"
        if remediation:
            msg += f" | Fix: {remediation}"
        raise RuntimeError(msg) from e


def store_campaign_memory(action, discount, target_count, return_rate,
                           best_segment, revenue_recovered):
    """
    Stores this campaign's result. Tries real Cognee (add + cognify)
    first, always writes the local fallback regardless of whether the
    Cognee call succeeds. Returns True if the real Cognee call
    succeeded, False if only the local fallback was written.
    """
    summary = (
        f"VyaparDost campaign record ({datetime.now().isoformat(timespec='seconds')}): "
        f"action='{action}', discount=Rs.{discount}, "
        f"customers_targeted={target_count}, return_rate={return_rate:.1f}%, "
        f"best_performing_segment='{best_segment}', "
        f"revenue_recovered=Rs.{revenue_recovered:.0f}."
    )
    record = {
        "action": action,
        "discount": discount,
        "target_count": target_count,
        "return_rate": return_rate,
        "best_segment": best_segment,
        "revenue_recovered": revenue_recovered,
        "summary": summary,
    }
    _write_local_memory(record)

    if not _cognee_configured():
        return False

    try:
        add_resp = requests.post(
            f"{COGNEE_BASE_URL}/api/v1/add",
            files={
                # "data" expects an actual UploadFile — plain text strings
                # go through the separate "raw_data" field instead, per
                # Cognee's docs ("Add and Remember String Inputs").
                "raw_data": (None, summary),
                "datasetName": (None, COGNEE_DATASET),
            },
            headers=_multipart_headers(), timeout=20,
        )
        _raise_with_detail(add_resp)

        cognify_resp = requests.post(
            f"{COGNEE_BASE_URL}/api/v1/cognify",
            json={"datasets": [COGNEE_DATASET]},
            headers=_headers(), timeout=30,
        )
        _raise_with_detail(cognify_resp)
        return True
    except Exception as e:
        print(f"  (Cognee store failed, local memory still saved: {e})")
        return False


def _extract_search_text(data):
    """
    Cognee's completion-style response shape can vary by version/search
    type. Tries a few plausible shapes defensively; returns None rather
    than guessing wrong, so the caller can fall back to local memory
    instead of printing something nonsensical during a live demo.
    """
    if isinstance(data, str):
        return data.strip() or None
    if isinstance(data, list) and data:
        first = data[0]
        if isinstance(first, str):
            return first.strip() or None
        if isinstance(first, dict):
            for key in ("text", "answer", "result", "content"):
                if first.get(key):
                    return str(first[key]).strip()
    if isinstance(data, dict):
        # Real observed shape from this Cognee Cloud tenant:
        # {"dataset_id": ..., "dataset_name": ..., "search_result": ["..."]}
        if "search_result" in data:
            return _extract_search_text(data["search_result"])
        for key in ("result", "answer", "response", "completion"):
            val = data.get(key)
            if isinstance(val, str) and val.strip():
                return val.strip()
            if isinstance(val, list) and val:
                return _extract_search_text(val)
    return None


def _natural_local_sentence(record):
    """
    The local fallback record stores a machine-readable summary
    (action='...', discount=Rs.20, ...) meant for Cognee ingestion —
    fine to store, but wrong to speak aloud verbatim. This builds an
    actual sentence from the same fields for when Cognee itself isn't
    reachable and we fall back to the local record.
    """
    return (
        f"Your last campaign, '{record['action']}' with a ₹{record['discount']} discount, "
        f"had a {record['return_rate']:.1f}% return rate and worked best with "
        f"{record['best_segment']} customers, recovering ₹{record['revenue_recovered']:,.0f}."
    )


def recall_last_campaign_insight():
    """
    Returns (insight_text, source) where source is "cognee" or "local",
    or (None, None) if there's genuinely no prior campaign on record yet
    (e.g. the very first run). Tries real Cognee search first; falls
    back to a natural-language sentence built from the local JSON
    record on any failure or unrecognized response shape.
    """
    if _cognee_configured():
        try:
            resp = requests.post(
                f"{COGNEE_BASE_URL}/api/v1/search",
                json={
                    "query": "What discount and customer segment worked best "
                             "in the most recent VyaparDost campaign record?",
                    "search_type": "GRAPH_COMPLETION",
                    "datasets": [COGNEE_DATASET],
                },
                headers=_headers(), timeout=20,
            )
            _raise_with_detail(resp)
            text = _extract_search_text(resp.json())
            if text:
                return text, "cognee"
        except Exception as e:
            print(f"  (Cognee recall failed, falling back to local memory: {e})")

    record = _read_local_memory()
    if record:
        return _natural_local_sentence(record), "local"
    return None, None


def recall_last_campaign_record():
    """
    Structured version of the last campaign (from the local record,
    which is always written) — used to build the natural-language
    "I recommend the same segment again" line without depending on
    Cognee's completion phrasing.
    """
    return _read_local_memory()