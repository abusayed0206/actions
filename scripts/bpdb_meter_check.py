"""
BPDB Prepaid Meter Token Check — Daily Data Collector & Analytics Generator
Fetches recharge history from the BPDB internal API, appends new records to a
CSV log, and regenerates a Markdown analytics report.

Required env var / GitHub Secret:
    BPDB_METER_NO   — 12-digit prepaid meter number

Optional env var:
    BPDB_NEXT_ACTION — SHA-1 Next-Action ID (defaults to known value)
"""

import csv
import json
import os
import re
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

# BPDB uses a non-standard CA; suppress the InsecureRequestWarning globally
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# ── Configuration ─────────────────────────────────────────────────────────────
METER_NO = os.environ.get("BPDB_METER_NO", "")
NEXT_ACTION = os.environ.get(
    "BPDB_NEXT_ACTION", "29e85b2c55c9142822fe8da82a577612d9e58bb2"
)
API_URL = "https://web.bpdbprepaid.gov.bd/bn/token-check"
HEADERS = {
    "Content-Type": "application/json",
    "Next-Action": NEXT_ACTION,
    "Accept": "text/x-component",
    "Referer": "https://web.bpdbprepaid.gov.bd/bn/token-check",
    "Origin": "https://web.bpdbprepaid.gov.bd",
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/122.0.0.0 Safari/537.36"
    ),
}

# ── File paths ─────────────────────────────────────────────────────────────────
ROOT = Path(__file__).resolve().parent.parent
FILES_DIR = ROOT / "files"
FILES_DIR.mkdir(exist_ok=True)

CSV_PATH = FILES_DIR / "bpdb_recharges.csv"
MD_PATH  = FILES_DIR / "bpdb_analytics.md"
STATS_MD_PATH = FILES_DIR / "bpdb_stats.md"

CSV_FIELDS = [
    "orderNo",
    "date",
    "meterNo",
    "customerNo",
    "operator",
    "sequence",
    "grossAmount",
    "energyCost",
    "arrearRecovery",
    "vat",
    "meterRent",
    "demandCharge",
    "rebate",
    "token",
    "monthDifference",
    "fetchedAt",
]


# ── API ────────────────────────────────────────────────────────────────────────
def fetch_meter_data(meter_no: str) -> dict:
    payload = [{"meterNo": meter_no}]
    resp = requests.post(API_URL, headers=HEADERS, json=payload, timeout=20, verify=False)
    resp.raise_for_status()

    lines = [ln for ln in resp.text.strip().splitlines() if ln]
    data_line = next((ln for ln in lines if ln.startswith("1:")), None)
    if not data_line:
        raise ValueError(f"Unexpected response format:\n{resp.text[:500]}")
    return json.loads(data_line[2:])


# ── Parsing helpers ────────────────────────────────────────────────────────────
def _txt(node) -> str:
    """Safely extract _text from an RSC node that may be empty/dict."""
    if isinstance(node, dict):
        return node.get("_text", "")
    return str(node) if node else ""


def parse_orders(data: dict) -> list[dict]:
    order_result = data["mOrderData"]["result"]
    raw_orders = order_result.get("orders", {}).get("order", [])
    # API may return a single dict (not list) when only 1 order exists
    if isinstance(raw_orders, dict):
        raw_orders = [raw_orders]

    parsed = []
    dt_now = datetime.now(timezone.utc).isoformat(timespec="seconds")

    for o in raw_orders:
        fees: dict[str, str] = {}
        fee_list = o.get("tariffFees", {}).get("tariffFee", [])
        if isinstance(fee_list, dict):
            fee_list = [fee_list]
        for fee in fee_list:
            name = _txt(fee.get("itemName", "")).strip()
            amount = _txt(fee.get("chargeAmount", "0")).strip()
            fees[name] = amount

        parsed.append(
            {
                "orderNo": _txt(o.get("orderNo")),
                "date": _txt(o.get("date")),
                "meterNo": _txt(o.get("meterNo")),
                "customerNo": _txt(o.get("customerNo")),
                "operator": _txt(o.get("operator")).replace("operator", ""),
                "sequence": _txt(o.get("sequence")),
                "grossAmount": _txt(o.get("grossAmount")),
                "energyCost": _txt(o.get("energyCost")),
                "arrearRecovery": _txt(o.get("arrearRecovery")),
                "vat": fees.get("VAT", "0"),
                "meterRent": fees.get("Meter Rent 1P", "0"),
                "demandCharge": fees.get("Demand Charge", "0"),
                "rebate": fees.get("Rebate", "0"),
                "token": _txt(o.get("tokens")),
                "monthDifference": _txt(o.get("monthDifference")),
                "fetchedAt": dt_now,
            }
        )
    return parsed


def parse_customer(data: dict) -> dict:
    r = data["mCustomerData"]["result"]
    return {
        "customerAccountNo": _txt(r.get("customerAccountNo")),
        "customerName": re.sub(r"\s+", " ", _txt(r.get("customerName")).replace("\\n", " ")).strip(),
        "customerAddress": _txt(r.get("customerAddress")),
        "customerPhone": _txt(r.get("customerPhone")).strip(",").strip(),
        "sndDivision": _txt(r.get("sndDivision")),
        "division": _txt(r.get("division")),
        "tariffCategory": _txt(r.get("tariffCategory")).strip(),
        "connectionCategory": _txt(r.get("connectionCategory")),
        "accountType": _txt(r.get("accountType")),
        "meterType": _txt(r.get("meterType")),
        "sanctionLoad": _txt(r.get("sanctionLoad")),
        "meterNumber": _txt(r.get("meterNumber")),
        "lastRechargeAmount": _txt(r.get("lastRechargeAmount")),
        "lastRechargeTime": _txt(r.get("lastRechargeTime")).rstrip(".0"),
        "totalRechargeThisMonth": _txt(r.get("totalRechargeThisMonth")),
        "installationDate": _txt(r.get("installationDate")),
    }


# ── CSV ────────────────────────────────────────────────────────────────────────
def load_existing_order_nos() -> set[str]:
    if not CSV_PATH.exists():
        return set()
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return {row["orderNo"] for row in reader}


def append_new_orders(orders: list[dict]) -> list[dict]:
    existing = load_existing_order_nos()
    new_orders = [o for o in orders if o["orderNo"] not in existing]
    if not new_orders:
        print("No new orders to add.")
        return []

    write_header = not CSV_PATH.exists()
    with CSV_PATH.open("a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        if write_header:
            writer.writeheader()
        writer.writerows(new_orders)

    print(f"Appended {len(new_orders)} new order(s) to {CSV_PATH.name}")
    return new_orders


def load_all_orders() -> list[dict]:
    if not CSV_PATH.exists():
        return []
    with CSV_PATH.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return list(reader)


# ── Analytics ──────────────────────────────────────────────────────────────────
def _f(val: str, decimals: int = 2) -> float:
    try:
        return round(float(val or 0), decimals)
    except ValueError:
        return 0.0


def build_stats_md(customer: dict, all_orders: list[dict]) -> str:
    """Compact metadata + stats summary — intended as the repo README-style card."""
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    if not all_orders:
        total_gross = avg_gross = total_vat = count = 0.0
        last_token = last_date = last_amount = "—"
        this_month_total = "—"
    else:
        all_orders_s = sorted(all_orders, key=lambda o: o["date"])
        count = len(all_orders_s)
        total_gross = sum(_f(o["grossAmount"]) for o in all_orders_s)
        total_vat   = sum(_f(o["vat"])         for o in all_orders_s)
        avg_gross   = round(total_gross / count, 2)
        last        = all_orders_s[-1]
        last_token  = last["token"]
        last_date   = last["date"]
        last_amount = f"৳ {_f(last['grossAmount']):,.2f}"
        this_month_total = f"৳ {_f(customer['totalRechargeThisMonth']):,.2f}"

    # Current month stats from CSV
    current_month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    month_orders = []
    for o in (all_orders or []):
        try:
            if datetime.strptime(o["date"], "%Y-%m-%d %H:%M:%S").strftime("%Y-%m") == current_month_key:
                month_orders.append(o)
        except ValueError:
            pass
    month_gross  = sum(_f(o["grossAmount"]) for o in month_orders)
    month_vat    = sum(_f(o["vat"])         for o in month_orders)
    month_count  = len(month_orders)

    lines = [
        "# BPDB Prepaid Meter — Stats & Metadata",
        "",
        f"> **Last updated:** {updated_at}  ",
        f"> **Source data:** [bpdb_recharges.csv](bpdb_recharges.csv) · [Full Analytics](bpdb_analytics.md)",
        "",
        "---",
        "",
        "## Customer Metadata",
        "",
        "| Field | Value |",
        "| ----- | ----- |",
        f"| **Name** | {customer['customerName']} |",
        f"| **Account No** | `{customer['customerAccountNo']}` |",
        f"| **Meter No** | `{customer['meterNumber']}` |",
        f"| **Phone** | {customer['customerPhone']} |",
        f"| **Division** | {customer['division']} |",
        f"| **S&D Zone** | {customer['sndDivision']} |",
        f"| **Tariff** | {customer['tariffCategory']} |",
        f"| **Connection** | {customer['connectionCategory']} · {customer['meterType']} |",
        f"| **Sanction Load** | {customer['sanctionLoad']} kW |",
        f"| **Account Type** | {customer['accountType']} |",
        f"| **Installation Date** | {customer['installationDate']} |",
        "",
        "---",
        "",
        "## Key Stats",
        "",
        "| Metric | Value |",
        "| ------ | ----- |",
        f"| **Total Recharges Recorded** | {int(count)} |",
        f"| **Total Amount Recharged** | ৳ {total_gross:,.2f} |",
        f"| **Average per Recharge** | ৳ {avg_gross:,.2f} |",
        f"| **Total VAT Paid (all time)** | ৳ {total_vat:,.2f} |",
        f"| **This Month Recharges** | {month_count} (৳ {month_gross:,.2f}) |",
        f"| **This Month VAT** | ৳ {month_vat:,.2f} |",
        f"| **API: Total Recharged This Month** | {this_month_total} |",
        f"| **Last Recharge Date** | {last_date} |",
        f"| **Last Recharge Amount** | {last_amount} |",
        f"| **Latest Token** | `{last_token}` |",
        "",
        "---",
        "",
        "## Data Files",
        "",
        "| File | Description |",
        "| ---- | ----------- |",
        "| [bpdb_recharges.csv](bpdb_recharges.csv) | Append-only recharge log (all records, deduplicated by `orderNo`) |",
        "| [bpdb_analytics.md](bpdb_analytics.md) | Full analytics report — monthly breakdown, operator stats, history table |",
        "| [bpdb_stats.md](bpdb_stats.md) | This file — metadata summary & key stats |",
        "",
        "---",
        "",
        "*Auto-generated by [bpdb_meter_check.py](../../scripts/bpdb_meter_check.py)*",
        "",
    ]
    return "\n".join(lines)


def build_analytics_md(customer: dict, all_orders: list[dict]) -> str:
    if not all_orders:
        return "No data available yet.\n"

    # Sort by date ascending
    all_orders = sorted(all_orders, key=lambda o: o["date"])

    total_gross = sum(_f(o["grossAmount"]) for o in all_orders)
    total_energy = sum(_f(o["energyCost"]) for o in all_orders)
    total_vat = sum(_f(o["vat"]) for o in all_orders)
    total_meter_rent = sum(_f(o["meterRent"]) for o in all_orders)
    total_demand = sum(_f(o["demandCharge"]) for o in all_orders)
    total_rebate = sum(_f(o["rebate"]) for o in all_orders)
    total_arrear = sum(_f(o["arrearRecovery"]) for o in all_orders)
    count = len(all_orders)
    avg_gross = round(total_gross / count, 2) if count else 0

    # Operator breakdown
    operator_counts: dict[str, int] = defaultdict(int)
    operator_amounts: dict[str, float] = defaultdict(float)
    for o in all_orders:
        op = o["operator"] or "Unknown"
        operator_counts[op] += 1
        operator_amounts[op] += _f(o["grossAmount"])

    # Monthly breakdown
    monthly: dict[str, dict] = defaultdict(
        lambda: {"count": 0, "gross": 0.0, "energy": 0.0, "vat": 0.0,
                 "rebate": 0.0, "meter_rent": 0.0, "demand": 0.0, "arrear": 0.0}
    )
    for o in all_orders:
        try:
            dt = datetime.strptime(o["date"], "%Y-%m-%d %H:%M:%S")
            key = dt.strftime("%Y-%m")
        except ValueError:
            key = "Unknown"
        monthly[key]["count"]      += 1
        monthly[key]["gross"]      += _f(o["grossAmount"])
        monthly[key]["energy"]     += _f(o["energyCost"])
        monthly[key]["vat"]        += _f(o["vat"])
        monthly[key]["rebate"]     += _f(o["rebate"])
        monthly[key]["meter_rent"] += _f(o["meterRent"])
        monthly[key]["demand"]     += _f(o["demandCharge"])
        monthly[key]["arrear"]     += _f(o["arrearRecovery"])

    last = all_orders[-1]
    updated_at = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    lines = [
        "# BPDB Prepaid Meter — Analytics Report",
        "",
        f"> **Last updated:** {updated_at}  ",
        f"> **Data source:** BPDB Prepaid Token Check API",
        "",
        "---",
        "",
        "## Customer Information",
        "",
        f"| Field | Value |",
        f"| ----- | ----- |",
        f"| **Name** | {customer['customerName']} |",
        f"| **Account No** | {customer['customerAccountNo']} |",
        f"| **Meter No** | {customer['meterNumber']} |",
        f"| **Phone** | {customer['customerPhone']} |",
        f"| **Division** | {customer['division']} |",
        f"| **S&D Zone** | {customer['sndDivision']} |",
        f"| **Tariff** | {customer['tariffCategory']} |",
        f"| **Connection** | {customer['connectionCategory']} |",
        f"| **Meter Type** | {customer['meterType']} |",
        f"| **Sanction Load** | {customer['sanctionLoad']} kW |",
        f"| **Account Type** | {customer['accountType']} |",
        f"| **Installation Date** | {customer['installationDate']} |",
        f"| **Last Recharge** | ৳ {customer['lastRechargeAmount']} on {customer['lastRechargeTime']} |",
        f"| **Total Recharged This Month** | ৳ {customer['totalRechargeThisMonth']} |",
        "",
        "---",
        "",
        "## Overall Statistics",
        "",
        f"| Metric | Value |",
        f"| ------ | ----- |",
        f"| **Total Recharges (recorded)** | {count} |",
        f"| **Total Amount Recharged** | ৳ {total_gross:,.2f} |",
        f"| **Average Recharge Amount** | ৳ {avg_gross:,.2f} |",
        f"| **Total Energy Cost** | ৳ {total_energy:,.2f} |",
        f"| **Total VAT Paid** | ৳ {total_vat:,.2f} |",
        f"| **Total Meter Rent** | ৳ {total_meter_rent:,.2f} |",
        f"| **Total Demand Charge** | ৳ {total_demand:,.2f} |",
        f"| **Total Rebate Earned** | ৳ {total_rebate:,.2f} |",
        f"| **Total Arrear Recovery** | ৳ {total_arrear:,.2f} |",
        f"| **Latest Token** | `{last['token']}` |",
        f"| **Latest Recharge Date** | {last['date']} |",
        "",
        "---",
        "",
        "## Monthly Breakdown",
        "",
        "| Month | # | Total (৳) | Energy (৳) | VAT (৳) | Meter Rent (৳) | Demand (৳) | Rebate (৳) | Arrear (৳) |",
        "| ----- | - | --------- | ---------- | ------- | -------------- | ---------- | ---------- | ---------- |",
    ]

    for month in sorted(monthly):
        m = monthly[month]
        lines.append(
            f"| {month} | {m['count']} "
            f"| {m['gross']:,.2f} "
            f"| {m['energy']:,.2f} "
            f"| {m['vat']:,.2f} "
            f"| {m['meter_rent']:,.2f} "
            f"| {m['demand']:,.2f} "
            f"| {m['rebate']:,.2f} "
            f"| {m['arrear']:,.2f} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Payment Operator Breakdown",
        "",
        "| Operator | Transactions | Total Amount (৳) |",
        "| -------- | ------------ | ---------------- |",
    ]
    for op in sorted(operator_counts, key=lambda x: operator_amounts[x], reverse=True):
        lines.append(
            f"| {op} | {operator_counts[op]} | {operator_amounts[op]:,.2f} |"
        )

    lines += [
        "",
        "---",
        "",
        "## Recharge History",
        "",
        "| # | Date | Amount (৳) | Energy (৳) | VAT (৳) | Rebate (৳) | Meter Rent (৳) | Operator | Token |",
        "| - | ---- | ---------- | ---------- | ------- | ---------- | -------------- | -------- | ----- |",
    ]
    for i, o in enumerate(reversed(all_orders), 1):
        lines.append(
            f"| {i} "
            f"| {o['date']} "
            f"| {_f(o['grossAmount']):,.2f} "
            f"| {_f(o['energyCost']):,.2f} "
            f"| {_f(o['vat']):,.2f} "
            f"| {_f(o['rebate']):,.2f} "
            f"| {_f(o['meterRent']):,.2f} "
            f"| {o['operator']} "
            f"| `{o['token']}` |"
        )

    lines += [
        "",
        "---",
        "",
        "*Generated automatically by [bpdb_meter_check.py](../../scripts/bpdb_meter_check.py)*",
        "",
    ]

    return "\n".join(lines)


# ── Main ───────────────────────────────────────────────────────────────────────
def main():
    if not METER_NO:
        print("ERROR: BPDB_METER_NO environment variable is not set.", file=sys.stderr)
        sys.exit(1)

    if not re.fullmatch(r"\d{12}", METER_NO):
        print(
            f"ERROR: BPDB_METER_NO '{METER_NO}' must be exactly 12 digits.",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"Fetching data for meter: {METER_NO}")
    data = fetch_meter_data(METER_NO)

    orders = parse_orders(data)
    customer = parse_customer(data)

    print(f"Customer: {customer['customerName']} | Account: {customer['customerAccountNo']}")
    print(f"Fetched {len(orders)} order(s) from API.")

    append_new_orders(orders)

    all_orders = load_all_orders()
    print(f"Total records in CSV: {len(all_orders)}")

    md_content = build_analytics_md(customer, all_orders)
    MD_PATH.write_text(md_content, encoding="utf-8")
    print(f"Analytics report written to {MD_PATH.name}")

    stats_content = build_stats_md(customer, all_orders)
    STATS_MD_PATH.write_text(stats_content, encoding="utf-8")
    print(f"Stats summary written to {STATS_MD_PATH.name}")


if __name__ == "__main__":
    main()
