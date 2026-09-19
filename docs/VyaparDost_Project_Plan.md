# VyaparDost AI — Project Build Plan (v2)
**Paytm Build for India AI Hackathon — Bengaluru Finale — Track 1: Merchant Growth AI**
Team Multiverse • Built by Niveditha

---

## 1. One-Line Pitch
**The AI Business Partner that finds growth and acts on it.**

VyaparDost AI proactively detects a merchant's growth opportunities, weighs multiple possible actions, explains its recommendation by voice, gets merchant approval, executes the campaign through a Paytm-native offer experience, estimates incremental impact using a holdout group, and remembers what worked for next time.

*(Note: execution is approval-gated, so the merchant stays in control — this is deliberately not "zero-touch.")*

**Final one-sentence description:** VyaparDost is an AI business partner that continuously detects merchant growth opportunities, compares the next-best actions, gets merchant approval by voice, executes the chosen campaign, estimates incremental impact, and remembers what worked.

---

## 2. The Problem
A busy kirana merchant has transaction data but no time to read dashboards, no marketing skill to design offers, and no staff to act on either. The result: lapsed customers, weak time-slots, and missed revenue stay invisible until it's too late.

> The gap isn't "more analytics." The gap is **proactive execution**.

---

## 3. The Solution — Core Loop
```
Merchant sales dip
        ↓
VyaparDost detects the opportunity
        ↓
Compares possible actions (Next Best Action)
        ↓
Checks guardrails (budget / discount / frequency limits)
        ↓
Recommends the strongest option, by voice
        ↓
Merchant approves by voice ("Haan, bhej do")
        ↓
n8n executes the campaign via a Paytm-native offer experience
        ↓
Customer returns and pays digitally
        ↓
Impact measured against a holdout group (incremental lift, not just raw sales)
        ↓
Cognee remembers what worked
        ↓
Next recommendation gets smarter
```

**Full loop:** Detect → Decide → Speak → Approve → Act → Acquire → Measure → Learn

---

## 4. Feature Modules

### 4.1 Detect — Transaction Signal Engine
- Reads synthetic merchant transaction data (sales, repeat rate, time-slot performance, churn)
- Flags anomalies: sales dips, lapsed customers, weak hours

### 4.2 Decide — Next Best Action + Guardrails
- Generates **2–3 ranked action options** with an estimated ₹ opportunity for each
  - e.g. Win back lapsed customers → ₹31K · Promote evening products → ₹18K · Weekend offer → ₹12K
- Recommends the strongest option with a stated reason
- **AI Guardrails (safety layer):**
  - Maximum campaign budget: ₹2,000
  - Maximum discount per offer: ₹50
  - No more than one message per customer every 14 days
- **Flow:** AI recommends → guardrail check → merchant approval → n8n executes
- This directly answers "what prevents the AI from making a bad decision?" — better than "human in the loop" alone

### 4.3 Speak & Approve — Sarvam Voice + Merchant Control
- Speech-to-text: understands merchant's spoken approval ("Haan, bhej do")
- Text-to-speech: speaks the insight and recommendation back in the merchant's own language
- **Merchant approval is the mandatory control gate** — nothing customer-facing fires without it

### 4.4 Act — n8n + Paytm-Native Offer Flow
- Offer is framed as Paytm-native, not generic: *"₹20 off your next purchase at Sharma Kirana — when you pay via Paytm."*
- Executed through a **Paytm-native payment/offer experience** — a mock offer/QR screen for the prototype, clearly labeled as simulated (not a live Paytm production API integration)
- n8n orchestrates: customer segmentation → offer generation → mocked "send" step

### 4.5 Acquire — New Paytm User Loop (secondary outcome)
- Every lapsed customer is tagged `paytm_user: true/false` in the dataset
- **Existing Paytm users** → standard win-back offer
- **Cash-only customers** → offer gated to require Paytm payment to redeem — a genuine acquisition hook
- Positioned as a **secondary benefit**, not the headline: the primary pitch stays "we help Paytm merchants grow"; this shows Paytm benefits too, as a bonus of the same mechanism

### 4.6 Measure — Revenue + Incremental Lift
- Standard KPIs: customers targeted, customers returned, revenue recovered, campaign ROI, new Paytm users acquired
- **Incremental Revenue Proof (holdout/control group):**
  - e.g. 84 customers → campaign group; 12 similar customers → holdout group
  - Campaign group: 31/84 returned = 36.9%
  - Holdout group: 3/12 returned = 25%
  - **Prototype-estimated incremental lift: +11.9pp** (small-sample demo estimate, not a statistically proven claim)
- Pitch line: *"VyaparDost doesn't just count sales after a campaign — it compares against a similar holdout group to estimate incremental impact."*
- This is a materially stronger answer than raw attributed revenue and pre-empts the judge question "how do you know the campaign caused this?"

### 4.7 Learn — Cognee Persistent Memory (must-have, lightweight)
- Stores past campaigns, outcomes, and merchant preferences
- **One visible memory moment in the demo is enough to prove it works:**
  - First campaign: ₹20 offer → 31 customers returned
  - Next recommendation: *"Previous ₹20 campaign produced a strong response among evening customers — I recommend the same segment."*
- Upgraded from "optional" to **must-have** since Cognee is one of the three named ecosystem sponsor technologies

---

## 5. Technical Architecture & Sponsor Role Mapping

| Layer | Technology | Role |
|---|---|---|
| Decide | VyaparDost AI (decision engine) | **Decide** — Next Best Action ranking + guardrail checks |
| Speak & Approve | Sarvam AI | **Speak** — Indian-language STT, translation, TTS |
| Act | n8n | **Act** — Segmentation, campaign trigger, tracking |
| Learn | Cognee | **Remember** — merchant context, past offers, outcomes |
| Signals | Synthetic dataset | Sales, repeat rate, time-slots, churn, `paytm_user` flag |
| Customer touchpoint | Mock Paytm-native offer/QR screen | Redemption + Paytm payment gating (simulated) |
| Frontend | Dashboard UI | Live demo visualization incl. holdout comparison |

**Control principle:** AI recommends → guardrails constrain → merchant approves → n8n executes.

---

## 6. Build Priority (2-Day Timeline)

| Priority | Component | Status |
|---|---|---|
| 🔴 1 | Synthetic dataset (transactions, customers, `paytm_user` flag, holdout group) | Build first — everything depends on it |
| 🔴 2 | Next Best Action scoring + guardrail checks | Low effort, high judge impact |
| 🔴 3 | Sarvam voice integration (STT + TTS) | Core differentiator |
| 🟡 4 | Cognee memory — one visible "remembered" moment | **Upgraded to must-have** — named sponsor tech |
| 🟡 5 | n8n workflow (mocked campaign send) | After voice works |
| 🟡 6 | Mock Paytm-native offer/QR screen + Paytm-user gating | Visual only, no backend needed |
| 🟢 7 | Results dashboard incl. holdout/lift comparison | Polish, but strengthens Measure story a lot |
| — | Soundbox-as-growth-channel | Roadmap slide only — say "designed for a future Soundbox-integrated experience," never "runs on Paytm Soundbox" |
| — | Merchant referral network, rewards ledger, lending cross-sell | Roadmap slide only, not built |

*No major new features after this list — execution quality now matters more than additional ideas.*

---

## 7. Demo Script (Live Flow)
1. Show **Sharma Kirana's** dashboard: sales down 22% this week
2. VyaparDost speaks: *"Sales are down 22%. I found three ways to recover it — reactivating your lapsed customers looks strongest at ₹31K. This fits within budget and discount guardrails. Shall I launch it?"*
3. Merchant responds by voice: *"Haan, bhej do."*
4. n8n visibly triggers the campaign; mock Paytm-native offer screen shown to "customer"
5. Simulated customer "returns" and pays — transaction reappears live in the dashboard
6. Results shown: 84 targeted → 31 returned (36.9%) vs. 12-customer holdout group at 25% → **prototype-estimated incremental lift: +11.9pp**, plus revenue, ROI, and new Paytm users acquired
7. Cognee moment: *"Previous ₹20 campaign worked best with evening customers — I recommend the same segment next time."*
8. Close on the roadmap line: *"Today Soundbox says '₹500 received.' Tomorrow it says 'Your campaign brought back 31 customers today.'"*

---

## 8. Two-Sided Value Story
```
                 VYAPARDOST
                      │
           ┌──────────┴──────────┐
           ▼                     ▼
    Merchant Growth         Paytm Growth
           │                     │
    More repeat sales      New digital users
           │                     │
           └──────────┬──────────┘
                       ▼
            More transaction activity
```
**Primary story:** "We help Paytm merchants grow."
**Secondary story:** "And when eligible non-Paytm customers convert through the offer, Paytm benefits too."

---

## 9. Why This Wins on Track 1's Own Terms
- **"AI business partner"** → recommends, explains, and acts — not just informs
- **"Think beyond payments"** → growth, retention, marketing — not a payments feature
- **"Trusted copilot"** → guardrails + mandatory voice approval before any customer-facing action
- **"Scalable for millions"** → rides on Soundbox + Paytm's existing merchant rails
- **Rigor** → incremental lift via holdout group, not just raw attributed revenue
- **Bonus** → the New Paytm User Acquisition angle answers "how does this help Paytm" without becoming the whole pitch
