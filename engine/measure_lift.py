"""
VyaparDost AI — Holdout / Incremental Lift Calculator
1. Loads the campaign group (84) and holdout group (12) from the dataset.
2. Simulates which lapsed customers return after the win-back offer window,
   using different return-rate assumptions for the campaign vs. holdout group
   (this models the real-world experiment: the campaign group got the ₹20
   offer, the holdout group did not).
3. Computes the incremental lift — the difference in return rate between
   the two groups — which is the honest way to claim "the campaign caused
   this," rather than just counting raw returns.
4. Reports revenue recovered and new Paytm users acquired among returners.
5. Writes a lift_report.csv to data/ so the dashboard (next module) can read it.

Labelling follows the project plan's credibility guidance:
  "Prototype-estimated incremental lift: +X pp" — not a statistically
  proven claim, since the holdout group here is small (n=12), as is
  appropriate to disclose for a hackathon prototype.
"""

import csv
import os
import random

random.seed(7)  # separate seed from dataset generation, for independent simulation

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(SCRIPT_DIR, "..", "data")

# ---- Return-rate assumptions ----
CAMPAIGN_RETURN_RATE = 0.369
HOLDOUT_RETURN_RATE = 0.25

DISCOUNT_PER_CUSTOMER = 20  # ₹ — must match the guardrail-checked offer


def load_csv(path):
    with open(path, newline="") as f:
        return list(csv.DictReader(f))


def simulate_returns(group, return_rate):
    """
    Each customer in the group independently 'returns' with probability
    return_rate. Returns the list of customers who returned.
    """
    returned = []
    for c in group:
        if random.random() < return_rate:
            returned.append(c)
    return returned


def compute_lift(campaign_group, campaign_returned, holdout_group, holdout_returned):
    campaign_rate = len(campaign_returned) / len(campaign_group) if campaign_group else 0.0
    holdout_rate = len(holdout_returned) / len(holdout_group) if holdout_group else 0.0
    lift_pp = (campaign_rate - holdout_rate) * 100
    return campaign_rate, holdout_rate, lift_pp


def compute_revenue_recovered(returned_customers):
    return sum(float(c["avg_basket_value"]) for c in returned_customers)


def write_lift_report(path, report_rows):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=report_rows[0].keys())
        writer.writeheader()
        for row in report_rows:
            writer.writerow(row)


def main():
    customers = load_csv(os.path.join(DATA_DIR, "customers.csv"))

    campaign_group = [c for c in customers if c["group"] == "campaign"]
    holdout_group = [c for c in customers if c["group"] == "holdout"]

    campaign_returned = simulate_returns(campaign_group, CAMPAIGN_RETURN_RATE)
    holdout_returned = simulate_returns(holdout_group, HOLDOUT_RETURN_RATE)

    campaign_rate, holdout_rate, lift_pp = compute_lift(
        campaign_group, campaign_returned, holdout_group, holdout_returned
    )

    revenue_recovered = compute_revenue_recovered(campaign_returned)
    campaign_cost = DISCOUNT_PER_CUSTOMER * len(campaign_group)
    roi = revenue_recovered / campaign_cost if campaign_cost else 0.0

    new_paytm_users = [c for c in campaign_returned if c["paytm_user"] == "False"]

    print("=" * 60)
    print("VYAPARDOST AI — HOLDOUT / INCREMENTAL LIFT REPORT")
    print("=" * 60)

    print(f"\nCampaign group: {len(campaign_group)} customers -> "
          f"{len(campaign_returned)} returned ({campaign_rate * 100:.1f}%)")
    print(f"Holdout group:  {len(holdout_group)} customers -> "
          f"{len(holdout_returned)} returned ({holdout_rate * 100:.1f}%)")

    print(f"\nPrototype-estimated incremental lift: +{lift_pp:.1f}pp")
    print("(Small-sample demo estimate, not a statistically proven claim — "
          "holdout group is n=12.)")

    print(f"\nRevenue recovered (campaign group): ₹{revenue_recovered:,.0f}")
    print(f"Campaign cost ({len(campaign_group)} x ₹{DISCOUNT_PER_CUSTOMER}): ₹{campaign_cost:,.0f}")
    print(f"Campaign ROI: {roi:.1f}x")

    print(f"\nNew Paytm users acquired (cash-only customers who returned): "
          f"{len(new_paytm_users)}")

    report_rows = [{
        "campaign_group_size": len(campaign_group),
        "campaign_returned": len(campaign_returned),
        "campaign_return_rate_pct": round(campaign_rate * 100, 1),
        "holdout_group_size": len(holdout_group),
        "holdout_returned": len(holdout_returned),
        "holdout_return_rate_pct": round(holdout_rate * 100, 1),
        "incremental_lift_pp": round(lift_pp, 1),
        "revenue_recovered": round(revenue_recovered, 2),
        "campaign_cost": campaign_cost,
        "campaign_roi": round(roi, 2),
        "new_paytm_users_acquired": len(new_paytm_users),
    }]
    write_lift_report(os.path.join(DATA_DIR, "lift_report.csv"), report_rows)
    print(f"\nLift report written to data/lift_report.csv")

    print("\nSARVAM VOICE SCRIPT (what VyaparDost would say):")
    print(
        f'  "Your campaign brought back {len(campaign_returned)} customers this week, '
        f'recovering about ₹{revenue_recovered:,.0f}. Compared to a holdout group that '
        f'didn\'t get the offer, that\'s a prototype-estimated lift of '
        f'{lift_pp:.1f} percentage points — and {len(new_paytm_users)} of them paid via '
        f'Paytm for the first time."'
    )


if __name__ == "__main__":
    main()