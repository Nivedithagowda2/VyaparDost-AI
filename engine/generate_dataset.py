"""
VyaparDost AI — Synthetic Dataset Generator
Generates a believable transaction history for a fictional merchant
("Sharma Kirana Store") with:
  - 8 weeks of daily sales
  - An engineered sales dip in the final week (~22%) driven by customer churn
  - A customer table with repeat-purchase history, paytm_user flag,
    and campaign / holdout group assignment for the Next Best Action demo
"""

import csv
import os
import random
from datetime import date, timedelta

random.seed(42)

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = os.path.join(SCRIPT_DIR, "..", "data")
os.makedirs(OUT_DIR, exist_ok=True)
START_DATE = date(2026, 7, 20)   # 8 weeks of history
NUM_WEEKS = 8
NUM_CUSTOMERS = 620

FIRST_NAMES = [
    "Ramesh", "Sunita", "Anil", "Priya", "Manoj", "Kavita", "Suresh", "Deepa",
    "Vikram", "Neha", "Ashok", "Rekha", "Sanjay", "Pooja", "Rajesh", "Meera",
    "Vinod", "Shalini", "Arun", "Nisha", "Prakash", "Divya", "Ravi", "Anita",
]
LAST_NAMES = [
    "Sharma", "Gupta", "Verma", "Reddy", "Nair", "Iyer", "Patel", "Kumar",
    "Singh", "Rao", "Joshi", "Mehta", "Das", "Pillai", "Chauhan", "Bhatt",
]

PRODUCT_CATEGORIES = [
    ("Groceries", 40, 350),
    ("Dairy", 20, 180),
    ("Snacks", 15, 120),
    ("Household", 30, 400),
    ("Beverages", 25, 200),
]


def make_customer_id(i):
    return f"CUST{i:04d}"


def generate_customers(n):
    customers = []
    for i in range(1, n + 1):
        name = f"{random.choice(FIRST_NAMES)} {random.choice(LAST_NAMES)}"
        paytm_user = random.random() < 0.55  # 55% already Paytm users
        is_regular = random.random() < 0.66
        customers.append({
            "customer_id": make_customer_id(i),
            "name": name,
            "paytm_user": paytm_user,
            "is_regular": is_regular,
            "avg_basket_value": round(random.uniform(120, 650), 2),
            "preferred_slot": random.choice(["Morning", "Afternoon", "Evening"]),
        })
    return customers


def assign_lapse_and_groups(customers):
    regulars = [c for c in customers if c["is_regular"]]
    random.shuffle(regulars)

    num_lapsed = 96
    lapsed = regulars[:num_lapsed]
    holdout = lapsed[-12:]
    campaign_pool = lapsed[:-12]

    lapsed_ids = {c["customer_id"] for c in lapsed}
    holdout_ids = {c["customer_id"] for c in holdout}
    campaign_ids = {c["customer_id"] for c in campaign_pool}

    for c in customers:
        c["will_lapse"] = c["customer_id"] in lapsed_ids
        c["group"] = (
            "holdout" if c["customer_id"] in holdout_ids
            else "campaign" if c["customer_id"] in campaign_ids
            else "n/a"
        )
    return customers


def generate_transactions(customers):
    transactions = []
    txn_id = 1
    total_days = NUM_WEEKS * 7
    lapse_start_day = total_days - 7  # final week only

    for day_offset in range(total_days):
        current_date = START_DATE + timedelta(days=day_offset)
        for c in customers:
            visits_today = False
            if c["is_regular"]:
                if c["will_lapse"] and day_offset >= lapse_start_day:
                    visits_today = False
                else:
                    visits_today = random.random() < 0.22
            else:
                visits_today = random.random() < 0.05

            if visits_today:
                category, lo, hi = random.choice(PRODUCT_CATEGORIES)
                amount = round(random.uniform(lo, hi), 2)
                transactions.append({
                    "txn_id": f"TXN{txn_id:05d}",
                    "date": current_date.isoformat(),
                    "customer_id": c["customer_id"],
                    "category": category,
                    "amount": amount,
                    "paid_via_paytm": c["paytm_user"] and random.random() < 0.9,
                    "time_slot": c["preferred_slot"],
                })
                txn_id += 1
    return transactions


def write_csv(path, rows, fieldnames):
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for r in rows:
            writer.writerow(r)


def main():
    customers = generate_customers(NUM_CUSTOMERS)
    customers = assign_lapse_and_groups(customers)
    transactions = generate_transactions(customers)

    write_csv(
        os.path.join(OUT_DIR, "customers.csv"),
        customers,
        ["customer_id", "name", "paytm_user", "is_regular", "avg_basket_value",
         "preferred_slot", "will_lapse", "group"],
    )
    write_csv(
        os.path.join(OUT_DIR, "transactions.csv"),
        transactions,
        ["txn_id", "date", "customer_id", "category", "amount",
         "paid_via_paytm", "time_slot"],
    )

    lapsed = [c for c in customers if c["will_lapse"]]
    campaign_group = [c for c in lapsed if c["group"] == "campaign"]
    holdout_group = [c for c in lapsed if c["group"] == "holdout"]
    cash_only_in_campaign = [c for c in campaign_group if not c["paytm_user"]]

    print(f"Customers generated: {len(customers)}")
    print(f"Transactions generated: {len(transactions)}")
    print(f"Lapsed regulars (churn signal): {len(lapsed)}")
    print(f"  Campaign group: {len(campaign_group)}")
    print(f"  Holdout group: {len(holdout_group)}")
    print(f"  Cash-only customers in campaign group (acquisition targets): {len(cash_only_in_campaign)}")


if __name__ == "__main__":
    main()