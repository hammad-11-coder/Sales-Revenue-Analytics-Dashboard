#!/usr/bin/env python3
"""Generate the SYNTHETIC retail dataset used by this project.

Everything produced here is fictional. Company names, customer names, prices and
order volumes are random draws from a fixed seed and say nothing about any real
business.

Two layers are produced:

1. A *clean ground-truth* dataset (never written to disk) generated from business
   assumptions: seasonality, growth, customer value skew, category margins.
2. A *raw* dataset written to ``data/raw`` in which realistic data-quality defects
   have been injected at known rates (duplicates, mixed date formats, bad
   quantities, orphan keys, ...). ``data/raw/defect_manifest.json`` records
   exactly how many of each defect were injected, so the cleaning pipeline in
   ``clean_data.py`` can be tested against a known answer.

Usage:
    python python/generate_data.py                 # seed 42 -> data/raw
    python python/generate_data.py --seed 7 --out /tmp/raw
"""
from __future__ import annotations

import argparse
import calendar
import json
from pathlib import Path

import numpy as np
import pandas as pd

DEFAULT_SEED = 42
FIRST_MONTH = (2024, 1)          # (year, month) of the first month in the dataset
N_MONTHS = 24                    # 24 full months: Jan 2024 .. Dec 2025
BASE_ORDERS_PER_MONTH = 600      # before seasonality and growth
MONTHLY_GROWTH = 0.012           # ~15% year-over-year order growth
N_CUSTOMERS = 2200
N_PRE_PERIOD_CUSTOMERS = 1300    # customers who signed up before the data window

# Festive-season uplift in Oct/Nov, soft Feb/Jun.
SEASONALITY = {1: 0.92, 2: 0.86, 3: 0.95, 4: 0.94, 5: 0.97, 6: 0.88,
               7: 0.90, 8: 1.00, 9: 1.04, 10: 1.30, 11: 1.22, 12: 1.10}

REGION_WEIGHTS = {"West": 0.30, "South": 0.27, "North": 0.25, "East": 0.10, "Central": 0.08}
# region, state, city, weight within the region
CITIES = [
    ("North", "Delhi", "New Delhi", 3), ("North", "Haryana", "Gurugram", 2),
    ("North", "Chandigarh", "Chandigarh", 1), ("North", "Rajasthan", "Jaipur", 2),
    ("North", "Uttar Pradesh", "Lucknow", 2),
    ("South", "Karnataka", "Bengaluru", 4), ("South", "Tamil Nadu", "Chennai", 3),
    ("South", "Telangana", "Hyderabad", 3), ("South", "Kerala", "Kochi", 1),
    ("East", "West Bengal", "Kolkata", 3), ("East", "Odisha", "Bhubaneswar", 1),
    ("East", "Bihar", "Patna", 1), ("East", "Assam", "Guwahati", 1),
    ("West", "Maharashtra", "Mumbai", 4), ("West", "Maharashtra", "Pune", 3),
    ("West", "Gujarat", "Ahmedabad", 2), ("West", "Gujarat", "Surat", 1),
    ("West", "Goa", "Panaji", 1),
    ("Central", "Madhya Pradesh", "Bhopal", 2), ("Central", "Madhya Pradesh", "Indore", 2),
    ("Central", "Chhattisgarh", "Raipur", 1), ("Central", "Madhya Pradesh", "Jabalpur", 1),
]

CATEGORIES = ["Technology", "Furniture", "Office Supplies", "Home & Kitchen", "Apparel"]

# category, subcategory, product name, price low, price high (INR list price), margin low, margin high
CATALOG = [
    ("Technology", "Smartphones", "Nexa Phone 5G 128GB", 12000, 24000, 0.16, 0.22),
    ("Technology", "Smartphones", "Nexa Phone Pro 256GB", 38000, 65000, 0.16, 0.22),
    ("Technology", "Smartphones", "Orbit S20 Smartphone", 22000, 42000, 0.16, 0.22),
    ("Technology", "Smartphones", "Lumio Edge 5G", 16000, 30000, 0.16, 0.22),
    ("Technology", "Smartphones", "Veloce Neo Phone", 9000, 15000, 0.16, 0.22),
    ("Technology", "Laptops", "Aria Book 14 Laptop", 42000, 62000, 0.14, 0.20),
    ("Technology", "Laptops", "Aria Book Pro 16", 75000, 95000, 0.14, 0.20),
    ("Technology", "Laptops", "Kinetic Slim 15 Laptop", 38000, 55000, 0.14, 0.20),
    ("Technology", "Laptops", "Zephyr Gaming Laptop", 70000, 92000, 0.14, 0.20),
    ("Technology", "Laptops", "Veloce Air 13 Ultrabook", 52000, 78000, 0.14, 0.20),
    ("Technology", "Accessories", "Wireless Earbuds Lite", 900, 2500, 0.35, 0.45),
    ("Technology", "Accessories", "Noise-Cancel Headphones", 3000, 9000, 0.35, 0.45),
    ("Technology", "Accessories", "65W GaN Charger", 900, 2200, 0.35, 0.45),
    ("Technology", "Accessories", "Bluetooth Speaker Mini", 1200, 4000, 0.35, 0.45),
    ("Technology", "Accessories", "Mechanical Keyboard", 2500, 7000, 0.35, 0.45),
    ("Technology", "Accessories", "Ergo Wireless Mouse", 600, 2000, 0.35, 0.45),
    ("Technology", "Accessories", "USB-C Hub 7-in-1", 1500, 3500, 0.35, 0.45),
    ("Technology", "Accessories", "10000mAh Power Bank", 800, 1800, 0.35, 0.45),
    ("Furniture", "Chairs", "Ergonomic Mesh Office Chair", 6000, 14000, 0.14, 0.22),
    ("Furniture", "Chairs", "Executive Leather Chair", 12000, 22000, 0.14, 0.22),
    ("Furniture", "Chairs", "Gaming Chair Pro", 8000, 16000, 0.14, 0.22),
    ("Furniture", "Chairs", "Visitor Chair Set of 2", 4000, 8000, 0.14, 0.22),
    ("Furniture", "Tables", "Standing Desk Electric", 18000, 35000, 0.14, 0.22),
    ("Furniture", "Tables", "Walnut Writing Desk", 9000, 18000, 0.14, 0.22),
    ("Furniture", "Tables", "Conference Table 6-Seater", 24000, 38000, 0.14, 0.22),
    ("Furniture", "Tables", "Compact Study Table", 6000, 11000, 0.14, 0.22),
    ("Furniture", "Storage", "5-Shelf Bookcase", 4500, 9000, 0.14, 0.22),
    ("Furniture", "Storage", "Steel Filing Cabinet", 6000, 12000, 0.14, 0.22),
    ("Furniture", "Storage", "Wardrobe 3-Door", 14000, 25000, 0.14, 0.22),
    ("Furniture", "Storage", "Shoe Rack Cabinet", 3000, 6500, 0.14, 0.22),
    ("Office Supplies", "Paper", "A4 Copier Paper Ream 500", 250, 450, 0.35, 0.45),
    ("Office Supplies", "Paper", "Premium Notebook Pack", 300, 900, 0.35, 0.45),
    ("Office Supplies", "Paper", "Sticky Notes Bulk Pack", 150, 500, 0.35, 0.45),
    ("Office Supplies", "Paper", "Spiral Notepad Set", 200, 600, 0.35, 0.45),
    ("Office Supplies", "Writing & Art", "Gel Pen Box of 50", 250, 700, 0.35, 0.45),
    ("Office Supplies", "Writing & Art", "Permanent Marker Set", 150, 450, 0.35, 0.45),
    ("Office Supplies", "Writing & Art", "Highlighter Pack of 10", 120, 380, 0.35, 0.45),
    ("Office Supplies", "Writing & Art", "Mechanical Pencil Set", 180, 520, 0.35, 0.45),
    ("Office Supplies", "Binders & Storage", "Heavy Duty Binder 2-inch", 200, 600, 0.35, 0.45),
    ("Office Supplies", "Binders & Storage", "Document Folder Organizer", 400, 1200, 0.35, 0.45),
    ("Office Supplies", "Binders & Storage", "Desk Organizer Set", 500, 1500, 0.35, 0.45),
    ("Office Supplies", "Binders & Storage", "Label Maker", 1500, 3500, 0.35, 0.45),
    ("Office Supplies", "Printing", "Printer Ink Cartridge Black", 1200, 2800, 0.20, 0.28),
    ("Office Supplies", "Printing", "Toner Cartridge Laser", 3500, 9000, 0.20, 0.28),
    ("Home & Kitchen", "Appliances", "Air Fryer 4L", 4500, 9500, 0.28, 0.38),
    ("Home & Kitchen", "Appliances", "Mixer Grinder 750W", 2500, 6000, 0.28, 0.38),
    ("Home & Kitchen", "Appliances", "Electric Kettle 1.8L", 900, 2200, 0.28, 0.38),
    ("Home & Kitchen", "Appliances", "Induction Cooktop", 2200, 5000, 0.28, 0.38),
    ("Home & Kitchen", "Appliances", "Robot Vacuum Cleaner", 9000, 14000, 0.28, 0.38),
    ("Home & Kitchen", "Cookware", "Non-Stick Cookware Set", 1500, 4500, 0.28, 0.38),
    ("Home & Kitchen", "Cookware", "Pressure Cooker 5L", 1400, 3200, 0.28, 0.38),
    ("Home & Kitchen", "Cookware", "Cast Iron Skillet", 1200, 2800, 0.28, 0.38),
    ("Home & Kitchen", "Cookware", "Stainless Steel Tiffin Set", 600, 1800, 0.28, 0.38),
    ("Home & Kitchen", "Home Decor", "LED Table Lamp", 700, 2500, 0.28, 0.38),
    ("Home & Kitchen", "Home Decor", "Wall Clock Modern", 600, 2200, 0.28, 0.38),
    ("Home & Kitchen", "Home Decor", "Scented Candle Set", 400, 1500, 0.28, 0.38),
    ("Home & Kitchen", "Home Decor", "Cotton Bedsheet King", 900, 3200, 0.28, 0.38),
    ("Apparel", "Menswear", "Cotton Casual Shirt", 700, 2200, 0.50, 0.60),
    ("Apparel", "Menswear", "Slim Fit Denim Jeans", 1200, 3500, 0.50, 0.60),
    ("Apparel", "Menswear", "Formal Trousers", 1100, 3200, 0.50, 0.60),
    ("Apparel", "Menswear", "Polo T-Shirt Pack of 3", 800, 2400, 0.50, 0.60),
    ("Apparel", "Womenswear", "Printed Kurta Set", 900, 3500, 0.50, 0.60),
    ("Apparel", "Womenswear", "Silk Blend Saree", 2500, 6000, 0.50, 0.60),
    ("Apparel", "Womenswear", "Cotton Palazzo Pants", 600, 1800, 0.50, 0.60),
    ("Apparel", "Womenswear", "Casual Maxi Dress", 1200, 3800, 0.50, 0.60),
    ("Apparel", "Footwear", "Running Shoes Air", 2200, 6500, 0.50, 0.60),
    ("Apparel", "Footwear", "Leather Formal Shoes", 2500, 7000, 0.50, 0.60),
    ("Apparel", "Footwear", "Slip-On Sneakers", 1200, 3200, 0.50, 0.60),
    ("Apparel", "Footwear", "Sports Sandals", 800, 2200, 0.50, 0.60),
]

SEGMENTS = ["Consumer", "Corporate", "Small Business"]
SEGMENT_P = [0.60, 0.25, 0.15]
SEGMENT_ITEMS_LAMBDA = {"Consumer": 0.7, "Corporate": 1.3, "Small Business": 1.0}
# category mix of order lines by customer segment (order follows CATEGORIES)
CATEGORY_MIX = {
    "Consumer": [0.22, 0.08, 0.08, 0.30, 0.32],
    "Corporate": [0.38, 0.22, 0.30, 0.06, 0.04],
    "Small Business": [0.24, 0.14, 0.38, 0.14, 0.10],
}
QTY_CHOICES = {
    "Technology": ([1, 2, 3], [0.85, 0.12, 0.03]),
    "Furniture": ([1, 2, 4], [0.80, 0.15, 0.05]),
    "Office Supplies": ([1, 2, 3, 5, 10], [0.35, 0.25, 0.20, 0.12, 0.08]),
    "Home & Kitchen": ([1, 2, 3], [0.70, 0.22, 0.08]),
    "Apparel": ([1, 2, 3, 4], [0.50, 0.30, 0.14, 0.06]),
}
DISCOUNT_LEVELS = [0.0, 0.05, 0.10, 0.15, 0.20, 0.25, 0.30]
DISCOUNT_P = {
    "Technology": [0.30, 0.25, 0.22, 0.12, 0.07, 0.03, 0.01],
    "Furniture": [0.12, 0.18, 0.22, 0.20, 0.14, 0.09, 0.05],
    "Office Supplies": [0.35, 0.25, 0.20, 0.10, 0.06, 0.03, 0.01],
    "Home & Kitchen": [0.20, 0.20, 0.22, 0.18, 0.10, 0.07, 0.03],
    "Apparel": [0.10, 0.15, 0.20, 0.20, 0.18, 0.12, 0.05],
}
# (2024 factor, 2025 factor). Furniture costs inflate faster than its prices -> margin squeeze.
PRICE_ADJ = {"Technology": (1.00, 1.01), "Furniture": (1.00, 1.02), "Office Supplies": (1.00, 1.04),
             "Home & Kitchen": (1.00, 1.03), "Apparel": (1.00, 1.05)}
COST_ADJ = {"Technology": (1.00, 1.01), "Furniture": (1.00, 1.06), "Office Supplies": (1.00, 1.04),
            "Home & Kitchen": (1.00, 1.03), "Apparel": (1.00, 1.05)}
CHANNELS = ["Online", "Marketplace", "Mobile App", "Retail Store"]
CHANNEL_P = [0.38, 0.24, 0.22, 0.16]
SHIP_BASE_LAG = {"West": 1, "South": 1, "North": 2, "East": 3, "Central": 3}

FIRST_NAMES = ["Aarav", "Vivaan", "Aditya", "Arjun", "Reyansh", "Kabir", "Ishaan", "Rohan", "Karan", "Siddharth",
               "Rahul", "Amit", "Vikram", "Nikhil", "Varun", "Manish", "Deepak", "Sanjay", "Rajesh", "Anil",
               "Priya", "Ananya", "Diya", "Kavya", "Meera", "Neha", "Pooja", "Riya", "Sneha", "Shruti",
               "Aditi", "Isha", "Nisha", "Tanvi", "Swati", "Divya", "Anjali", "Kriti", "Sakshi", "Pallavi",
               "Farhan", "Imran", "Zoya", "Sana", "Ayesha", "Harpreet", "Gurpreet", "Simran", "Joseph", "Maria"]
LAST_NAMES = ["Sharma", "Verma", "Gupta", "Mehta", "Shah", "Patel", "Desai", "Joshi", "Kulkarni", "Deshmukh",
              "Patil", "Pawar", "Iyer", "Nair", "Menon", "Reddy", "Naidu", "Rao", "Pillai", "Krishnan",
              "Banerjee", "Chatterjee", "Mukherjee", "Das", "Ghosh", "Sen", "Bose", "Roy", "Singh", "Kaur",
              "Chopra", "Malhotra", "Kapoor", "Khanna", "Bhatia", "Arora", "Saxena", "Agarwal", "Mishra", "Tiwari",
              "Pandey", "Yadav", "Thakur", "Chauhan", "Khan", "Ansari", "Qureshi", "Siddiqui", "Fernandes", "Pereira"]


def _month_list() -> list[tuple[int, int]]:
    y, m = FIRST_MONTH
    out = []
    for _ in range(N_MONTHS):
        out.append((y, m))
        m += 1
        if m == 13:
            y, m = y + 1, 1
    return out


def _round_price(x: float) -> int:
    return int(round(x / 10) * 10) if x >= 1000 else int(round(x))


# --------------------------------------------------------------------------------------
# Layer 1: clean ground truth
# --------------------------------------------------------------------------------------
def build_regions() -> pd.DataFrame:
    return pd.DataFrame(
        [(i + 1, r, s, c) for i, (r, s, c, _) in enumerate(CITIES)],
        columns=["region_id", "region", "state", "city"],
    )


def build_products(rng: np.random.Generator) -> pd.DataFrame:
    rows = []
    for i, (cat, sub, name, lo, hi, mlo, mhi) in enumerate(CATALOG, start=1):
        price = _round_price(lo * (hi / lo) ** rng.random())
        margin = rng.uniform(mlo, mhi)
        rows.append((f"P{i:03d}", name, cat, sub, price, round(price * (1 - margin), 2)))
    return pd.DataFrame(rows, columns=["product_id", "product_name", "category", "subcategory",
                                       "unit_price", "unit_cost"])


def build_customers(rng: np.random.Generator, regions: pd.DataFrame) -> pd.DataFrame:
    region_names = list(REGION_WEIGHTS)
    region_p = np.array([REGION_WEIGHTS[r] for r in region_names])
    combos = [(f, l) for f in FIRST_NAMES for l in LAST_NAMES]
    pick = rng.choice(len(combos), size=N_CUSTOMERS, replace=False)

    rows = []
    for i in range(N_CUSTOMERS):
        region = region_names[rng.choice(len(region_names), p=region_p)]
        sub = regions[regions.region == region]
        w = np.array([c[3] for c in CITIES if c[0] == region], dtype=float)
        region_id = int(sub.region_id.iloc[rng.choice(len(sub), p=w / w.sum())])
        if i < N_PRE_PERIOD_CUSTOMERS:
            signup = pd.Timestamp("2023-03-01") + pd.Timedelta(days=int(rng.integers(0, 305)))
        else:
            signup = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(rng.integers(0, 700)))
        f, l = combos[pick[i]]
        rows.append((f"C{i + 1:04d}", f"{f} {l}", SEGMENTS[rng.choice(3, p=SEGMENT_P)], region_id, signup))
    return pd.DataFrame(rows, columns=["customer_id", "customer_name", "segment", "home_region_id", "signup_date"])


def build_transactions(rng: np.random.Generator, regions: pd.DataFrame, products: pd.DataFrame,
                       customers: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    region_name = dict(zip(regions.region_id, regions.region))
    cust_weight = rng.lognormal(0.0, 1.1, size=len(customers))   # heavy-tailed customer value
    signup = customers.signup_date.to_numpy()
    cust_seg = customers.segment.to_numpy()
    cust_region = customers.home_region_id.to_numpy()

    cat_idx = {c: np.where(products.category.to_numpy() == c)[0] for c in CATEGORIES}
    pop = rng.lognormal(0.0, 0.6, size=len(products)) * products.unit_price.to_numpy() ** -0.25
    cat_p = {c: pop[cat_idx[c]] / pop[cat_idx[c]].sum() for c in CATEGORIES}

    order_rows, item_rows = [], []
    for t, (y, m) in enumerate(_month_list()):
        month_start = pd.Timestamp(y, m, 1)
        n_days = calendar.monthrange(y, m)[1]
        n_orders = int(rng.poisson(BASE_ORDERS_PER_MONTH * SEASONALITY[m] * (1 + MONTHLY_GROWTH) ** t))
        eligible = np.where(signup < np.datetime64(month_start))[0]
        p = cust_weight[eligible] / cust_weight[eligible].sum()
        cust_pick = rng.choice(eligible, size=n_orders, p=p)
        days = np.arange(1, n_days + 1)
        dow = np.array([pd.Timestamp(y, m, d).dayofweek for d in days])
        pd_w = np.where(dow >= 5, 1.3, 1.0)
        day_pick = rng.choice(days, size=n_orders, p=pd_w / pd_w.sum())

        for k in range(n_orders):
            ci = cust_pick[k]
            seg = cust_seg[ci]
            rid = int(cust_region[ci])
            region = region_name[rid]
            order_date = pd.Timestamp(y, m, int(day_pick[k]))
            channel = CHANNELS[rng.choice(4, p=CHANNEL_P)]
            n_items = min(6, 1 + int(rng.poisson(SEGMENT_ITEMS_LAMBDA[seg])))

            lines, chosen, cats_in_order = [], set(), set()
            for _ in range(n_items):
                cat = CATEGORIES[rng.choice(5, p=CATEGORY_MIX[seg])]
                pi = int(cat_idx[cat][rng.choice(len(cat_idx[cat]), p=cat_p[cat])])
                if pi in chosen:
                    continue
                chosen.add(pi)
                cats_in_order.add(cat)
                qv, qp = QTY_CHOICES[cat]
                qty = int(qv[rng.choice(len(qv), p=qp)])
                if seg == "Corporate" and rng.random() < 0.25:
                    qty = min(50, qty * int(rng.integers(2, 6)))
                yi = 0 if y == FIRST_MONTH[0] else 1
                prod = products.iloc[pi]
                price = int(round(prod.unit_price * PRICE_ADJ[cat][yi]))
                cost = round(float(prod.unit_cost) * COST_ADJ[cat][yi], 2)
                d_idx = int(rng.choice(7, p=DISCOUNT_P[cat]))
                p_bump = 1 - ((1 - (0.25 if region == "East" else 0.0))
                              * (1 - (0.30 if m in (10, 11) else 0.0))
                              * (1 - (0.20 if channel == "Marketplace" else 0.0)))
                if rng.random() < p_bump:
                    d_idx = min(d_idx + 1, 6)
                lines.append((prod.product_id, qty, price, cost, DISCOUNT_LEVELS[d_idx]))

            p_ret = 0.07 if cats_in_order & {"Apparel", "Technology"} else 0.035
            u = rng.random()
            status = "Cancelled" if u < 0.05 else ("Returned" if u < 0.05 + p_ret else "Completed")
            if status == "Cancelled":
                ship = pd.NaT
            else:
                ship = order_date + pd.Timedelta(days=SHIP_BASE_LAG[region] + int(rng.integers(0, 3)))
            order_rows.append((order_date, ship, customers.customer_id.iloc[ci], rid, channel, status, len(item_rows)))
            for ln in lines:
                item_rows.append((len(order_rows) - 1, *ln))

    orders = pd.DataFrame(order_rows, columns=["order_date", "ship_date", "customer_id", "region_id",
                                               "sales_channel", "order_status", "_first_item"])
    orders["_tmp"] = np.arange(len(orders))
    orders = orders.sort_values(["order_date", "_tmp"], kind="stable").reset_index(drop=True)
    orders["order_id"] = [f"ORD-{d.year}-{n:06d}" for d, n in zip(orders.order_date,
                          orders.groupby(orders.order_date.dt.year).cumcount() + 1)]
    id_by_tmp = dict(zip(orders._tmp, orders.order_id))

    items = pd.DataFrame(item_rows, columns=["_tmp", "product_id", "quantity", "unit_price", "unit_cost", "discount"])
    items["order_id"] = items._tmp.map(id_by_tmp)
    order_rank = {oid: i for i, oid in enumerate(orders.order_id)}
    items["_o"] = items.order_id.map(order_rank)
    items = items.sort_values(["_o"], kind="stable").reset_index(drop=True)
    items.insert(0, "order_item_id", np.arange(1, len(items) + 1))
    items = items[["order_item_id", "order_id", "product_id", "quantity", "unit_price", "unit_cost", "discount"]]
    orders = orders[["order_id", "order_date", "ship_date", "customer_id", "region_id", "sales_channel", "order_status"]]
    return orders, items


def build_truth(seed: int = DEFAULT_SEED) -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(seed)
    regions = build_regions()
    products = build_products(rng)
    customers = build_customers(rng, regions)
    orders, items = build_transactions(rng, regions, products, customers)
    return {"regions": regions, "products": products, "customers": customers,
            "orders": orders, "order_items": items}


# --------------------------------------------------------------------------------------
# Layer 2: inject known defects
# --------------------------------------------------------------------------------------
class _Claimer:
    """Hands out disjoint random row positions so each injected defect is counted exactly once."""

    def __init__(self, rng: np.random.Generator):
        self.rng, self.used = rng, set()

    def claim(self, candidates, k: int) -> np.ndarray:
        cand = np.array([i for i in candidates if i not in self.used])
        if k > len(cand):
            raise ValueError(f"cannot claim {k} rows from {len(cand)} candidates")
        pick = np.sort(self.rng.choice(cand, size=k, replace=False))
        self.used.update(int(i) for i in pick)
        return pick


def inject_defects(truth: dict[str, pd.DataFrame], seed: int = DEFAULT_SEED):
    rng = np.random.default_rng(seed + 1)
    manifest: dict = {"seed": seed}
    manifest["truth_rows"] = {k: int(len(v)) for k, v in truth.items()}

    # ---------------- orders ----------------
    orders = truth["orders"].copy()
    n = len(orders)
    orders["order_date_true"] = orders.order_date
    orders["order_date"] = orders.order_date.dt.strftime("%Y-%m-%d")
    orders["ship_date"] = orders.ship_date.dt.strftime("%Y-%m-%d")
    cl = _Claimer(rng)
    all_o = np.arange(n)
    ship_ok = np.where(orders.ship_date.notna().to_numpy())[0]

    miss_cust = cl.claim(all_o, round(0.0015 * n))
    orders.loc[miss_cust, "customer_id"] = np.nan
    manifest["orders_missing_customer_id"] = int(len(miss_cust))

    alt_od = cl.claim(all_o, round(0.03 * n))
    half = len(alt_od) // 2
    d = pd.to_datetime(orders.loc[alt_od, "order_date"])
    orders.loc[alt_od[:half], "order_date"] = d.iloc[:half].dt.strftime("%d/%m/%Y").to_numpy()
    orders.loc[alt_od[half:], "order_date"] = d.iloc[half:].dt.strftime("%d-%b-%Y").to_numpy()
    manifest["orders_alt_format_order_date"] = int(len(alt_od))

    alt_sd = cl.claim(ship_ok, round(0.02 * n))
    d = pd.to_datetime(orders.loc[alt_sd, "ship_date"])
    h2 = len(alt_sd) // 2
    orders.loc[alt_sd[:h2], "ship_date"] = d.iloc[:h2].dt.strftime("%d/%m/%Y").to_numpy()
    orders.loc[alt_sd[h2:], "ship_date"] = d.iloc[h2:].dt.strftime("%d-%b-%Y").to_numpy()
    manifest["orders_alt_format_ship_date"] = int(len(alt_sd))

    variants = {"Completed": ["completed", "COMPLETED", " Completed "],
                "Cancelled": ["Canceled", "cancelled", "CANCELLED"],
                "Returned": ["returned", "RETURNED"]}
    st_rows = cl.claim(all_o, round(0.04 * n))
    for i in st_rows:
        opts = variants[orders.at[i, "order_status"]]
        orders.at[i, "order_status"] = opts[int(rng.integers(0, len(opts)))]
    manifest["orders_status_variants"] = int(len(st_rows))

    sb = cl.claim(ship_ok, round(0.002 * n))
    for i in sb:
        orders.at[i, "ship_date"] = (orders.at[i, "order_date_true"]
                                     - pd.Timedelta(days=int(rng.integers(1, 6)))).strftime("%Y-%m-%d")
    manifest["orders_ship_before_order"] = int(len(sb))

    mc = cl.claim(all_o, round(0.005 * n))
    orders.loc[mc, "sales_channel"] = np.nan
    manifest["orders_missing_sales_channel"] = int(len(mc))

    dup_o = cl.claim(all_o, round(0.004 * n))
    orders = orders.drop(columns="order_date_true")
    # (order_date_true dropped before duplication below)
    orders = pd.concat([orders, orders.iloc[dup_o]], ignore_index=True)
    manifest["orders_duplicate_rows"] = int(len(dup_o))

    miss_cust_ids = set(truth["orders"].order_id.iloc[miss_cust])

    # ---------------- order items ----------------
    items = truth["order_items"].copy()
    m_items = len(items)
    in_bad_order = items.order_id.isin(miss_cust_ids).to_numpy()
    manifest["items_in_orders_missing_customer"] = int(in_bad_order.sum())
    elig = np.where(~in_bad_order)[0]
    ci = _Claimer(rng)

    q = ci.claim(elig, round(0.0015 * m_items))
    items.loc[q, "quantity"] = np.where(np.arange(len(q)) % 2 == 0, 0, -1)
    manifest["items_nonpositive_quantity"] = int(len(q))

    items["unit_price"] = items.unit_price.astype(float)
    bp = ci.claim(elig, round(0.001 * m_items))
    for j, i in enumerate(bp):
        items.at[i, "unit_price"] = -abs(items.at[i, "unit_price"]) if j % 2 == 0 else np.nan
    manifest["items_bad_unit_price"] = int(len(bp))

    mcost = ci.claim(elig, round(0.003 * m_items))
    items.loc[mcost, "unit_cost"] = np.nan
    manifest["items_missing_unit_cost"] = int(len(mcost))

    elig_set = set(elig.tolist())
    disc_ok = np.where(items.discount.to_numpy() >= 0.05)[0]
    dp = ci.claim([i for i in disc_ok if i in elig_set], round(0.004 * m_items))
    items.loc[dp, "discount"] = (items.loc[dp, "discount"] * 100).round(0)
    manifest["items_discount_as_percent"] = int(len(dp))

    nd = ci.claim(elig, round(0.0005 * m_items))
    items.loc[nd, "discount"] = -0.05
    manifest["items_negative_discount"] = int(len(nd))

    up = ci.claim(elig, round(0.001 * m_items))
    items.loc[up, "product_id"] = "P999"
    manifest["items_unknown_product"] = int(len(up))

    dup_i = ci.claim(elig, round(0.003 * m_items))
    items = pd.concat([items, items.iloc[dup_i]], ignore_index=True)
    manifest["items_duplicate_rows"] = int(len(dup_i))

    n_orph = round(0.001 * m_items)
    src = rng.choice(elig, size=n_orph, replace=False)
    orph = truth["order_items"].iloc[src].copy()
    orph["order_item_id"] = np.arange(m_items + 1, m_items + 1 + n_orph)
    orph["order_id"] = [f"ORD-9999-{i + 1:06d}" for i in range(n_orph)]
    items = pd.concat([items, orph], ignore_index=True)
    manifest["items_orphan_order_reference"] = int(n_orph)

    # ---------------- customers ----------------
    cust = truth["customers"].copy()
    cust["signup_date"] = cust.signup_date.dt.strftime("%Y-%m-%d")
    nc = len(cust)
    cc = _Claimer(rng)
    mseg = cc.claim(np.arange(nc), round(0.01 * nc))
    cust.loc[mseg, "segment"] = np.nan
    manifest["customers_missing_segment"] = int(len(mseg))
    vseg = cc.claim(np.arange(nc), round(0.05 * nc))
    for i in vseg:
        v = cust.at[i, "segment"]
        cust.at[i, "segment"] = [v.lower(), v.upper(), f" {v} "][int(rng.integers(0, 3))]
    manifest["customers_segment_variants"] = int(len(vseg))
    wn = cc.claim(np.arange(nc), round(0.01 * nc))
    for i in wn:
        cust.at[i, "customer_name"] = "  " + cust.at[i, "customer_name"].replace(" ", "  ") + " "
    manifest["customers_name_whitespace"] = int(len(wn))
    dup_c = cc.claim(np.arange(nc), round(0.003 * nc))
    cust = pd.concat([cust, cust.iloc[dup_c]], ignore_index=True)
    manifest["customers_duplicate_rows"] = int(len(dup_c))

    # ---------------- products ----------------
    prod = truth["products"].copy()
    npd = len(prod)
    pc = _Claimer(rng)
    vcat = pc.claim(np.arange(npd), round(0.06 * npd))
    for i in vcat:
        v = prod.at[i, "category"]
        prod.at[i, "category"] = [v.lower(), v.upper(), f"{v} "][int(rng.integers(0, 3))]
    manifest["products_category_variants"] = int(len(vcat))
    vname = pc.claim(np.arange(npd), round(0.05 * npd))
    for i in vname:
        prod.at[i, "product_name"] = prod.at[i, "product_name"] + "  "
    manifest["products_name_trailing_space"] = int(len(vname))

    raw = {"regions": truth["regions"].copy(), "products": prod, "customers": cust,
           "orders": orders, "order_items": items}
    return raw, manifest


def write_raw(out_dir: Path, seed: int = DEFAULT_SEED) -> dict:
    out_dir.mkdir(parents=True, exist_ok=True)
    truth = build_truth(seed)
    raw, manifest = inject_defects(truth, seed)
    for name, df in raw.items():
        df.to_csv(out_dir / f"{name}.csv", index=False)
    (out_dir / "defect_manifest.json").write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
    return manifest


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seed", type=int, default=DEFAULT_SEED, help="random seed (default 42)")
    ap.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "data" / "raw",
                    help="output directory for raw CSVs")
    args = ap.parse_args()
    manifest = write_raw(args.out, args.seed)
    print(f"Wrote raw SYNTHETIC data to {args.out} (seed={args.seed})")
    for k, v in manifest["truth_rows"].items():
        print(f"  clean truth rows  {k:12s} {v:>8,}")
    injected = {k: v for k, v in manifest.items() if k not in ("seed", "truth_rows")}
    print(f"  injected defect types: {len(injected)}; total injected cells/rows: {sum(injected.values()):,}")


if __name__ == "__main__":
    main()
