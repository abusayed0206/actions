#!/usr/bin/env python3
"""
DAC -> FRA cheapest one-way flight deals, sent to Telegram.

Scrapes Google Flights (via fast-flights) once per day in the search window,
keeping only same-ticket itineraries (no separate-PNR / self-transfer combos)
where every layover is either short enough to wait out at the gate
(<=MAX_LAYOVER_MINUTES) or long enough to qualify for a known airline free
transit-hotel program (see HOTEL_PROGRAMS) -- anything awkwardly in between
is dropped. Reports the TOP_N cheapest fares found across the whole window.

Env vars:
    TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID  - required to actually send.
    DRY_RUN=1                             - print the report instead of sending.
    If the Telegram env vars are absent, it always falls back to dry-run.
"""

import os
import time
from datetime import date, datetime, timedelta, timezone

import requests
from fast_flights import FlightQuery, Passengers, create_query, get_flights
from fast_flights.exceptions import FlightsNotFound

FROM_AIRPORT = "DAC"
TO_AIRPORT = "FRA"
SEARCH_START = date.today()
SEARCH_END = date(2026, 10, 10)
MAX_LAYOVER_MINUTES = 360  # 6h
CURRENCY = "BDT"
TOP_N = 10
REQUEST_DELAY_SECONDS = 1.5  # be polite to Google between per-day scrapes

TELEGRAM_MESSAGE_LIMIT = 4096

# Not queryable via Google Flights scraping — airline policy, researched manually,
# not re-verified per run. (connecting_airport -> (airline, min_minutes, max_minutes, label))
# Economy-class free transit-hotel windows:
#   Qatar Airways STPC (Doha):        8h-24h
#   Emirates Dubai Connect (Dubai):   10h-26h
#   Turkish Airlines free hotel (IST):12h-24h  (their free Touristanbul *tour*, no
#                                                hotel, starts earlier at 6h)
HOTEL_PROGRAMS = {
    "DOH": ("Qatar Airways", 8 * 60, 24 * 60, "free STPC transit hotel"),
    "DXB": ("Emirates", 10 * 60, 26 * 60, "free Dubai Connect hotel"),
    "IST": ("Turkish Airlines", 12 * 60, 24 * 60, "free transit hotel"),
}

# Student fares aren't a Google Flights search option — they need a verified account +
# ID/visa/acceptance-letter uploaded directly on the airline's own site, applied at
# booking, on top of the public prices shown below.
NOTES = (
    "ℹ️ *Notes*\n"
    "• 🏨-tagged layovers likely qualify for a free airline transit hotel — request it "
    "via Manage Booking after ticketing.\n"
    "• Student fares (need your uploaded ID, applied when you book direct):\n"
    "  – Qatar Airways Student Club: 10% (1st flight) → 15% → 20% (3rd/4th), ages 18-30, "
    "register at qatarairways.com/student-club\n"
    "  – Turkish Airlines: ~15% international, ages 12-34, register student passenger "
    "type in Miles&Smiles (~7 business days approval) before booking\n"
    "  – Emirates: 10% Economy / 5% Business, promo code STUDENT, needs Skywards "
    "membership, ID checked at check-in"
)


def daterange(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def search_day(d: date):
    """Return (Flights results, Query) for one departure date, or ([], None) on failure.

    Deliberately no server-side layover cap here: we need to see long layovers too,
    to check them against HOTEL_PROGRAMS in passes_layover_policy().
    """
    query = create_query(
        flights=[
            FlightQuery(
                date=d.isoformat(),
                from_airport=FROM_AIRPORT,
                to_airport=TO_AIRPORT,
            )
        ],
        trip="one-way",
        seat="economy",
        passengers=Passengers(adults=1),
        currency=CURRENCY,
        hide_separate_and_self_transfer=True,
    )
    try:
        return get_flights(query), query
    except FlightsNotFound:
        return [], query
    except Exception as e:
        print(f"  [warn] {d}: {e}")
        return [], query


def leg_dt(simple_dt) -> datetime:
    y, mo, da = simple_dt.date
    h, mi = simple_dt.time
    return datetime(y, mo, da, h, mi)


def fmt_hm(minutes: int) -> str:
    return f"{minutes // 60}h{minutes % 60:02d}m"


def layovers(flight) -> list[tuple[int, str]]:
    """List of (minutes, connecting_airport_code) between consecutive legs."""
    legs = flight.flights
    out = []
    for i in range(len(legs) - 1):
        arr = leg_dt(legs[i].arrival)
        next_dep = leg_dt(legs[i + 1].departure)
        minutes = int((next_dep - arr).total_seconds() // 60)
        out.append((minutes, legs[i].to_airport.code))
    return out


def hotel_program(minutes: int, code: str):
    """Descriptive label if this layover plausibly qualifies for a free transit hotel."""
    program = HOTEL_PROGRAMS.get(code)
    if program and program[1] <= minutes <= program[2]:
        airline, _lo, _hi, label = program
        return f"{airline} {label}"
    return None


def valid_flight(flight) -> bool:
    """False if any leg has malformed departure/arrival data (rare scraper quirk,
    e.g. a missing hour in Google's payload) -- unsafe to format or date-math on."""
    try:
        for leg in flight.flights:
            leg_dt(leg.departure)
            leg_dt(leg.arrival)
        return True
    except (TypeError, ValueError):
        return False


def passes_layover_policy(flight) -> bool:
    """Keep only if every layover is short enough to wait out, or long enough to
    earn a known free transit hotel. Drops awkward in-between layovers."""
    if not valid_flight(flight):
        return False
    for minutes, code in layovers(flight):
        if minutes <= MAX_LAYOVER_MINUTES:
            continue
        if hotel_program(minutes, code):
            continue
        return False
    return True


def collect_deals():
    """Scrape every day in the window, return list of (Flights, date, Query)."""
    deals = []
    for d in daterange(SEARCH_START, SEARCH_END):
        results, query = search_day(d)
        kept = [f for f in results if passes_layover_policy(f)]
        deals.extend((flight, d, query) for flight in kept)
        print(f"  {d}: {len(kept)}/{len(results)} same-PNR fares pass layover policy")
        time.sleep(REQUEST_DELAY_SECONDS)
    return deals


def format_itinerary(rank: int, flight, d: date, query) -> str:
    legs = flight.flights
    lines = [
        f"*{rank}. {flight.airlines[0] if flight.airlines else flight.type}* — ৳{flight.price:,} BDT",
        f"📅 Depart {d.strftime('%d %b %Y')}",
    ]
    for i, leg in enumerate(legs):
        dep, arr = leg_dt(leg.departure), leg_dt(leg.arrival)
        day_shift = "" if dep.date() == d else f" (+{(dep.date() - d).days}d)"
        lines.append(
            f"🛫 {leg.from_airport.code} {dep:%H:%M}{day_shift} → "
            f"{leg.to_airport.code} {arr:%H:%M} ({fmt_hm(leg.duration)})"
        )
        if i < len(legs) - 1:
            next_dep = leg_dt(legs[i + 1].departure)
            layover_min = int((next_dep - arr).total_seconds() // 60)
            code = leg.to_airport.code
            tag = ""
            if layover_min > MAX_LAYOVER_MINUTES:
                program = hotel_program(layover_min, code)
                tag = f" — 🏨 {program}" if program else ""
            lines.append(f"⏳ Layover: {fmt_hm(layover_min)} in {code}{tag}")
    total_min = int((leg_dt(legs[-1].arrival) - leg_dt(legs[0].departure)).total_seconds() // 60)
    lines.append(f"🕒 Total travel time: {fmt_hm(total_min)}")
    lines.append(f"🔗 [View on Google Flights]({query.url()})")
    return "\n".join(lines)


def build_message(deals) -> str:
    header = (
        f"✈️ *{FROM_AIRPORT} → {TO_AIRPORT} — Cheapest one-way fares*\n"
        f"{SEARCH_START:%d %b} – {SEARCH_END:%d %b %Y} · Economy · 1 adult\n"
        f"_Same ticket only (no separate PNR) · layover ≤ 6h, or longer only if it "
        f"earns a free transit hotel_\n"
    )

    if not deals:
        return header + "\nNo matching fares found in this window."

    deals.sort(key=lambda t: t[0].price)
    top = deals[:TOP_N]

    body = "\n\n".join(
        format_itinerary(i + 1, flight, d, query) for i, (flight, d, query) in enumerate(top)
    )
    footer = f"\n\n_Updated: {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC_"
    return header + "\n" + body + "\n\n" + NOTES + footer


def chunk_message(text: str, limit: int = TELEGRAM_MESSAGE_LIMIT):
    """Split into <=limit chunks on line boundaries (Telegram's per-message text cap)."""
    if len(text) <= limit:
        return [text]
    chunks, current = [], ""
    for line in text.split("\n"):
        candidate = f"{current}\n{line}" if current else line
        if len(candidate) > limit:
            chunks.append(current)
            current = line
        else:
            current = candidate
    if current:
        chunks.append(current)
    return chunks


def send_telegram(text: str):
    token = os.environ["TELEGRAM_BOT_TOKEN"]
    chat_id = os.environ["TELEGRAM_CHAT_ID"]
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    for chunk in chunk_message(text):
        resp = requests.post(
            url,
            data={
                "chat_id": chat_id,
                "text": chunk,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            },
        )
        if resp.status_code != 200:
            print(f"  [warn] Telegram send failed: {resp.status_code} {resp.text}")


def main():
    if SEARCH_START > SEARCH_END:
        print(f"Search window closed ({SEARCH_END} has passed). Nothing to do.")
        return

    print(f"Searching {FROM_AIRPORT}->{TO_AIRPORT}, {SEARCH_START} to {SEARCH_END} ...")
    deals = collect_deals()
    message = build_message(deals)

    print("\n" + "=" * 60)
    print(f"Message length: {len(message)} chars "
          f"({'OK' if len(message) <= TELEGRAM_MESSAGE_LIMIT else 'will be split'})")
    print("=" * 60)
    print(message)
    print("=" * 60)

    dry_run = os.environ.get("DRY_RUN") == "1" or not (
        os.environ.get("TELEGRAM_BOT_TOKEN") and os.environ.get("TELEGRAM_CHAT_ID")
    )
    if dry_run:
        print("\n[dry run] Not sending to Telegram (set TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID and unset DRY_RUN to send).")
    else:
        send_telegram(message)
        print("\nSent to Telegram.")


if __name__ == "__main__":
    main()
