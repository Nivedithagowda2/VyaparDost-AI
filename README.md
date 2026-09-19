# VyaparDost AI

**The AI Business Partner that finds growth and acts on it.**

Built for the **Paytm Build for India AI Hackathon — Bengaluru Finale (Track 1: Merchant Growth AI)**, Team Multiverse.

VyaparDost is an AI business partner for a small merchant (kirana store, sweet shop, etc.). It watches transaction data, tells the merchant in their own language what's happening and why, gets their voice approval before doing anything, executes a real campaign, measures its true incremental impact against a holdout group, remembers what worked, and protects the merchant from fake-payment fraud — all backed by real sponsor technology (Sarvam, n8n, Cognee), not mocked stand-ins.

---

## The core loop

```
Merchant's sales dip
       ↓
VyaparDost detects it, and also surfaces the sales pattern (best/worst day & time-slot)
       ↓
Checks the real calendar for an upcoming festival opportunity
       ↓
Recalls what worked in the last campaign (Cognee memory)
       ↓
Compares 2–3 possible actions, ranks by expected ₹ opportunity
       ↓
Checks guardrails (budget / discount / frequency limits)
       ↓
Recommends the strongest option — explained by voice, in Hindi/English/Kannada
       ↓
Merchant approves by speaking into the mic ("शुरू करो")
       ↓
n8n (real workflow) segments customers and executes the campaign
       ↓
Customer sees a Paytm-native offer screen, pays, redeems
       ↓
Impact measured against a holdout group — incremental lift, not just raw sales
       ↓
Cognee remembers what worked — feeds into the next recommendation
```

Execution is **approval-gated** — nothing customer-facing ever fires without the merchant's spoken "yes." This is deliberately not "zero-touch."

---

## What's actually real vs. simulated (full honesty)

| Piece | Status |
|---|---|
| Sarvam speech-to-text & text-to-speech | **Real** — live API calls, real microphone recording |
| n8n workflow execution | **Real** — live webhook to an actual n8n Cloud workflow |
| Cognee memory (store + recall) | **Real** — live API calls to a Cognee Cloud tenant |
| Sales data, festival calendar, day/time patterns | **Real** — computed live from the CSVs / actual 2026 calendar dates |
| Paytm offer screen, QR code | **Simulated** — a realistic mockup; not a live Paytm merchant integration |
| Campaign return rate / holdout lift | **Simulated** — synthetic dataset, no waiting period; numbers are reproducible (fixed random seed) for a consistent demo |
| Payment Check fraud protection | **Real logic**, demoed via a manual "simulate payment" button; a genuine SMS-forwarding automation path (via a phone-automation app) also exists and has been tested against real bank SMS formats |

---

## Feature-by-feature

### 1. Detect
Reads the transaction CSV, computes this week's sales/customers vs. the normal baseline, and states the ₹ loss and % dip in plain language.

### 2. Sales Pattern
Breaks revenue down by **day of week × time slot** (Morning/Afternoon/Evening) — tells the merchant exactly which day and which hour is strongest and weakest, not just "sales are down."

### 3. Upcoming Opportunity
Checks a real, verified 2026 Indian festival calendar (Diwali, Navratri, Ganesh Chaturthi, Onam, etc.) up to 45 days ahead, and — based on the merchant's declared business type (sweet shop, cosmetic store, hotel, general store, stationery store) — suggests specific items likely to see a demand spike, with enough lead time to actually stock up.

### 4. Learn (Cognee memory)
Before recommending anything, checks Cognee's knowledge graph for what happened in the last campaign (which action, which discount, which customer segment responded best) and folds that into the new recommendation. Falls back to a local JSON record if Cognee is briefly unreachable, so a live demo never goes silent.

### 5. Decide — Next Best Action + Guardrails
Generates 3 ranked options with an estimated ₹ opportunity each, recommends the strongest, and checks it against hard guardrails:
- Max campaign budget: **₹2,000**
- Max discount per offer: **₹50**
- No more than one message per customer every 14 days

Only the top-ranked action is ever executed — the other two exist for transparency, not for parallel execution.

### 6. Speak & Approve (Sarvam)
Speaks the full recommendation — including the sales pattern, the festival nudge, the memory recall, and the specific numbers behind the recommendation — in the merchant's chosen language (English / Hindi / Kannada), listens via the real microphone, transcribes with Sarvam's speech-to-text, and fuzzy-matches the reply against approval phrases (so minor mishears like "lach" instead of "launch" still work). Nothing fires without a clear "yes."

### 7. Act (n8n)
On approval, POSTs the real target customer list to a live n8n Cloud workflow, which segments cash-only vs. existing Paytm users and builds the offer. The real webhook response — not a printed string — confirms execution.

### 8. Mock Paytm Offer / QR Screen
A phone-mockup web page (`frontend/paytm_offer_screen.html`) showing what the customer sees: the offer, a real scannable QR code, and a "Simulate scan & pay" button that flips to a payment-success state — clearly labeled as a simulated screen, not a live Paytm integration.

### 9. Measure — Holdout-Based Incremental Lift
Compares the campaign group's return rate against a holdout group that received no offer, to estimate genuine **incremental** lift — not just raw attributed revenue. Also reports revenue recovered, campaign ROI, and new Paytm users acquired (cash-only customers who had to pay via Paytm to redeem).

### 10. Paytm Impact
A distinct section measuring what the campaign is worth **to Paytm**, not just the merchant — projected new-user transaction volume added to Paytm's platform, at a stated conservative assumption.

### 11. Dashboard (web UI)
A local web dashboard (`frontend/dashboard.html`, served by `engine/server.py`) with six tabs:
- **Overview** — this week's KPIs, best/worst day & slot, full day×slot table
- **Sales Trends** — live weekly and monthly revenue charts
- **Upcoming Festival** — the live festival opportunity, with business-type-specific suggestions
- **Udhaar Book** — a customer credit tracker: log who owes what and by when, send a WhatsApp reminder with a pay link, or show a payment QR in person. Stored locally in the browser only.
- **Voice Agent** — ask VyaparDost questions in plain text or by voice ("why are sales down?", "which is my best day?") and get answers computed live from the real data, spoken back via Sarvam; also shows the transcript of the last terminal-run voice session
- **Payment Check** — see below

### 12. Payment Check (fraud protection)
Solves a real problem: a customer shows a payment screen that might be fake, edited, or an old reused screenshot. This module never trusts a screen — it only trusts the merchant's own transaction ledger. Type the claimed amount (and transaction ID/UTR if shown) and it checks against real received payments, correctly distinguishing:
- ✅ **Received** — a genuine, unclaimed payment — safe to hand over goods
- 🔁 **Already used** — this payment was real, but already matched to an earlier sale (reused screenshot)
- ⚠️ **Not found** — no such payment ever landed

A short auto-retry window (up to 15s) absorbs real-world SMS/network delay without wrongly logging a false fraud attempt. A genuine automation path exists too: a phone-automation app (e.g. MacroDroid) forwards real bank/UPI SMS text to `/api/payment/sms-webhook`, which parses the amount and transaction ID server-side — tested against multiple real bank SMS formats.

---

## Architecture & sponsor technology

| Layer | Technology | Role |
|---|---|---|
| Decide | Custom decision engine (`decision_engine.py`) | Next Best Action ranking + guardrail checks |
| Speak & Approve | **Sarvam AI** | Speech-to-text, text-to-speech, in English/Hindi/Kannada |
| Act | **n8n** (Cloud workflow) | Customer segmentation, campaign execution |
| Learn | **Cognee** (Cloud, knowledge graph) | Remembers past campaigns and outcomes |
| Signals | Synthetic dataset (`generate_dataset.py`) | Transactions, customers, festival calendar |
| Customer touchpoint | Mock Paytm offer/QR screen | Simulated redemption experience |
| Dashboard backend | Flask (`server.py`) | Live REST API over the same CSVs and modules |
| Dashboard frontend | Plain HTML/CSS/JS + Chart.js | Sales trends, festival, udhaar book, voice agent, payment check |

---

## Project structure

```
vyapardost-ai/
├── .env                          # API keys (see Setup below)
├── data/
│   ├── customers.csv
│   ├── transactions.csv
│   ├── last_run_report.json      # written by run_demo.py, read by the dashboard
│   ├── local_memory.json         # Cognee fallback record
│   ├── live_ledger.json          # Payment Check: received payments
│   └── fraud_log.json            # Payment Check: blocked fraud attempts
├── engine/
│   ├── generate_dataset.py       # builds the synthetic dataset
│   ├── decision_engine.py        # Detect + Decide + Guardrails
│   ├── sarvam_voice.py           # Speak & Approve (Sarvam STT/TTS)
│   ├── measure_lift.py           # Measure (holdout-based lift)
│   ├── memory.py                 # Learn (Cognee integration)
│   ├── voice_agent.py            # Dashboard's Q&A "brain"
│   ├── payment_check.py          # Fraud protection ledger + SMS parsing
│   ├── server.py                 # Flask backend + dashboard server
│   └── run_demo.py               # Full terminal-based voice-guided demo
├── frontend/
│   ├── dashboard.html            # Main web dashboard
│   └── paytm_offer_screen.html   # Mock customer-facing offer/QR screen
└── docs/
    ├── VyaparDost_Project_Plan.md
    ├── VyaparDost_AI.pptx
    └── VyaparDost_AI.pdf
```

---

## Setup

### 1. Install dependencies
```
pip install flask requests python-dotenv --break-system-packages
pip install sounddevice numpy --break-system-packages   # for real microphone input
```

### 2. Create `.env` in the project root
```
SARVAM_API_KEY="your-sarvam-key"
SARVAM_RECORD_SECONDS=6

N8N_WEBHOOK_URL=https://your-workspace.app.n8n.cloud/webhook/vyapardost-campaign

COGNEE_BASE_URL=https://your-tenant.aws.cognee.ai
COGNEE_API_KEY="your-cognee-key"
COGNEE_TENANT_ID="your-tenant-id"
```

### 3. Generate the synthetic dataset (only needed once)
```
python engine/generate_dataset.py
```

---

## Running it

**Two things run side by side, in two separate terminals:**

### Terminal 1 — the dashboard
```
python engine/server.py
```
Open **http://127.0.0.1:5000** (or your laptop's LAN IP, from another device on the same WiFi — the server binds to `0.0.0.0` so the Payment Check SMS webhook can be reached from a phone).

### Terminal 2 — the full voice-guided demo
```
python engine/run_demo.py
```
Walks through the entire loop end to end: language selection → business type → Detect → Sales Pattern → Upcoming Opportunity → Learn (Cognee recall) → Decide → Guardrails → Recovery Plan → Speak & Approve (real mic) → Act (real n8n) → Measure → Paytm Impact → Learn (Cognee store). Writes `data/last_run_report.json` at the end, which the dashboard's Voice Agent tab reads.

---

## Demo script (suggested flow for judges)

1. Show the dashboard's **Overview** tab — this week's dip, best/worst day and time slot
2. Switch to **Upcoming Festival** — show the real, calendar-verified opportunity
3. Run `run_demo.py` live — pick a language, speak the approval out loud
4. Show the **Mock Paytm offer screen** — click "Simulate scan & pay" to complete the customer-side story
5. Back in the terminal — Measure and Paytm Impact numbers appear, then Cognee stores the result
6. Run `run_demo.py` again — show the **Learn** step recalling the previous campaign live
7. Switch to the dashboard's **Payment Check** tab — demonstrate fake/reused-screenshot detection using the Simulate button
8. Close on the **Udhaar Book** — a genuinely useful merchant tool beyond the core pitch

---

## Known limitations (stated honestly)

- The campaign return rate and holdout lift use a **fixed random seed** for reproducible demo numbers — they'll be identical every run unless the seed in `measure_lift.py` is changed.
- The Paytm offer/QR screen and payment links are **simulated** — not connected to a real Paytm merchant account.
- Live SMS-based payment automation (via a phone-automation app) depends on both devices sharing a WiFi network without client isolation — many public/hackathon venue WiFi networks block this, so the dashboard's **Simulate** button is the recommended path for live demos.
- Udhaar Book reminders are visual (flagged "Due Today"/"Overdue" when the dashboard is open) — not background push notifications, since that would require a server-side job scheduler.

---

## Why this fits Track 1

- **"AI business partner"** — recommends, explains, and acts, not just informs
- **"Think beyond payments"** — growth, retention, festival planning, fraud protection, credit tracking
- **"Trusted copilot"** — hard guardrails + mandatory voice approval before any customer-facing action
- **Rigor** — incremental lift via a holdout group, not just raw attributed revenue, openly labeled as a small-sample prototype estimate
- **Paytm-specific upside** — a dedicated Paytm Impact projection, separate from merchant ROI, showing new-user transaction volume added to Paytm's own platform

---

Built by **Niveditha**, Team Multiverse.
