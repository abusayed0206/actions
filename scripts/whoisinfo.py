import datetime
import html
import os
import re
import time

import pytz
import requests

DHAKA_TZ = pytz.timezone("Asia/Dhaka")
TELEGRAM_MAX_LENGTH = 3800
DEFAULT_ALERT_DAYS = 30
DEFAULT_WARN_DAYS = 90
DEFAULT_REQUEST_DELAY_SECONDS = 1.0
# shortcut: fixed rate (27 Oct 2026); override with the BDT_PER_USD env var when it drifts.
DEFAULT_BDT_PER_USD = 124.0
USD_PER_EUR = float(os.environ.get("USD_PER_EUR") or 1.12)

# Yearly renewal price per domain as (amount, currency).
# Cloudflare prices are at-cost from cfdomainpricing.com; .bd/.com.bd are BTCL prices.
RENEWAL_PRICES = {
    "sayed.blog": (20.20, "USD"),
    "sayed.page": (10.20, "USD"),
    "sayed.dev": (12.20, "USD"),
    "sayed.app": (14.20, "USD"),
    "abusayed.dev": (12.20, "USD"),
    "nayem.page": (10.20, "USD"),
    "abusayed.de": (3.55, "EUR"),  # Spaceship
    "kriti.app": (14.20, "USD"),  # Cloudflare rate; moving from Name.com
    "lrs.bd": (1800, "BDT"),
    "tracker.bd": (1800, "BDT"),
    "nextshop.com.bd": (1400, "BDT"),
}

# Used for the yearly cost plan when the lookup has no expiry date (DENIC hides it).
EXPIRY_FALLBACK = {
    "abusayed.de": datetime.date(2027, 10, 16),
}
COST_PLAN_LAST_YEAR = 2030

URGENCY_EMOJI = {
    "error": "❓",
    "expired": "🔥",
    "critical": "🚨",
    "warning": "🟡",
    "healthy": "✅",
    "unknown": "ℹ️",
}

# These statuses mean the domain needs attention even if its expiry date is
# still in the future (for example, a registrar hold or a grace period).
ALERT_STATUSES = {
    "available",
    "client hold",
    "clienthold",
    "free",
    "grace1",
    "grace2",
    "inactive",
    "pending delete",
    "pendingdelete",
    "redemption",
    "redemption period",
    "redemptionperiod",
    "server hold",
    "serverhold",
}


def get_dhaka_time():
    """Returns the current time in Dhaka timezone (GMT+6)."""
    return datetime.datetime.now(DHAKA_TZ)


def env_int(name, default):
    """Reads an integer environment variable, falling back to a default."""
    try:
        return int(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def env_float(name, default):
    """Reads a float environment variable, falling back to a default."""
    try:
        return float(os.environ.get(name, default))
    except (TypeError, ValueError):
        return default


def spaceship_lookup(domain, retries=2):
    """
    Fetches domain data from Spaceship's registrar API.

    DENIC does not publish expiration dates for .de domains, but Spaceship
    returns the registrar-side expiration date for domains in the account.
    Requires SPACESHIP_API_KEY and SPACESHIP_API_SECRET with domains:read.
    """
    api_key = os.environ.get("SPACESHIP_API_KEY")
    api_secret = os.environ.get("SPACESHIP_API_SECRET")

    if not api_key or not api_secret:
        print(f"ℹ️ [{domain}] Spaceship API credentials not set; using DENIC RDAP.")
        return None

    api_url = f"https://spaceship.dev/api/v1/domains/{domain}"
    headers = {
        "User-Agent": "GitHub-Actions-Domain-Monitor/1.0",
        "Accept": "application/json",
        "X-API-Key": api_key,
        "X-API-Secret": api_secret,
    }

    for attempt in range(retries):
        try:
            print(f"🔎 [{domain}] Spaceship attempt {attempt + 1}/{retries}")
            response = requests.get(api_url, timeout=30, headers=headers)
            print(f"📥 [{domain}] Spaceship HTTP {response.status_code}")

            if response.status_code != 200:
                print(f"📥 [{domain}] Spaceship response body: {response.text[:300]}")

            if response.status_code in (401, 403):
                print(
                    f"⚠️ [{domain}] Spaceship authorization failed. "
                    "Check the API key/secret and domains:read scope."
                )
                return None
            if response.status_code == 404:
                print(f"⚠️ [{domain}] Domain not found in the Spaceship account.")
                return None

            response.raise_for_status()
            data = response.json()

            events = []
            if data.get("registrationDate"):
                events.append(
                    {
                        "eventAction": "registration",
                        "eventDate": data["registrationDate"],
                    }
                )
            if data.get("expirationDate"):
                events.append(
                    {
                        "eventAction": "expiration",
                        "eventDate": data["expirationDate"],
                    }
                )

            print(
                f"✅ [{domain}] Spaceship expirationDate: "
                f"{data.get('expirationDate', 'NOT FOUND')}"
            )

            normalized = {
                "source": "spaceship",
                "ldhName": data.get("name", domain),
                "status": [data.get("lifecycleStatus") or "registered"],
                "events": events,
                "registrar": "Spaceship",
                "expiresOn": data.get("expirationDate"),
            }
            if data.get("autoRenew") is not None:
                normalized["autoRenew"] = data["autoRenew"]
            return normalized

        except requests.exceptions.RequestException as e:
            print(f"❌ [{domain}] Spaceship request error: {type(e).__name__}")
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 5
                print(
                    f"⏳ [{domain}] Waiting {wait_time}s before Spaceship retry..."
                )
                time.sleep(wait_time)

    print(
        f"💀 [{domain}] Spaceship lookup failed after {retries} attempts; "
        "using DENIC RDAP."
    )
    return None


def whois_lookup(domain, retries=3):
    """Fetches WHOIS information from the appropriate API with retry logic."""
    domain = domain.lower()

    # .de domains are queried from Spaceship's registrar API when credentials
    # are available, because DENIC itself publishes no expiry date. If that
    # fails, fall back to DENIC RDAP for status/last-changed data.
    if domain.endswith(".bd"):
        api_url = f"https://api.sayed.app/whoisbd/lookup?domain={domain}"
    elif domain.endswith(".de"):
        spaceship_data = spaceship_lookup(domain)
        if spaceship_data:
            return spaceship_data
        api_url = f"https://rdap.denic.de/domain/{domain}"
    else:
        api_url = f"https://rdap.sayed.app/api/lookup/{domain}"

    for attempt in range(retries):
        try:
            headers = {
                "User-Agent": "GitHub-Actions-Domain-Monitor/1.0",
                "Accept": "application/json",
            }

            # Add bypass token for Cloudflare (to bypass bot protection).
            # Never print the headers: this token must stay secret.
            bypass_token = os.environ.get("CF_BYPASS_TOKEN")
            if bypass_token:
                headers["X-Bypass-Token"] = bypass_token

            print(f"🔎 [{domain}] Attempt {attempt + 1}/{retries}: {api_url}")
            response = requests.get(api_url, timeout=30, headers=headers)
            print(f"📥 [{domain}] HTTP {response.status_code}")

            if response.status_code != 200:
                print(f"📥 [{domain}] Response body: {response.text[:300]}")

            # 4xx responses (except rate limiting) will not improve on retry.
            if (
                400 <= response.status_code < 500
                and response.status_code != 429
            ):
                print(f"🚫 [{domain}] HTTP {response.status_code}; not retrying.")
                return None

            response.raise_for_status()
            data = response.json()
            print(f"✅ [{domain}] Response received")
            return data

        except requests.exceptions.Timeout:
            print(f"⏰ [{domain}] Request timed out after 30s")
        except requests.exceptions.ConnectionError:
            print(f"🔌 [{domain}] Connection error")
        except requests.exceptions.HTTPError as e:
            status = (
                e.response.status_code if e.response is not None else "unknown"
            )
            print(f"🚫 [{domain}] HTTP error {status}")
        except requests.exceptions.RequestException as e:
            print(f"❌ [{domain}] Request error: {type(e).__name__}")
        except Exception as e:
            print(f"💥 [{domain}] Unexpected error: {type(e).__name__}: {e}")

        if attempt < retries - 1:
            wait_time = (attempt + 1) * 10
            print(f"⏳ [{domain}] Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
        else:
            print(f"💀 [{domain}] All {retries} attempts failed")

    return None


def parse_expiration_date(raw_date_str):
    """
    Parse expiration dates from the RDAP wrapper or BD WHOIS API.

    Formats:
    - "Tue, 12 Jan 2027 14:17:50 GMT" (RDAP)
    - "28/01/2030" (BD WHOIS)
    """
    if not raw_date_str:
        return None

    raw_date_str = str(raw_date_str).strip()
    if raw_date_str.upper() in {"N/A", "NONE", "UNKNOWN"}:
        return None

    try:
        # BD format (DD/MM/YYYY). Assume end of day in Dhaka.
        if "/" in raw_date_str:
            expiration_date = datetime.datetime.strptime(
                raw_date_str, "%d/%m/%Y"
            )
            expiration_date = expiration_date.replace(
                hour=23, minute=59, second=59
            )
            return DHAKA_TZ.localize(expiration_date)

        # RDAP format.
        clean_date = raw_date_str.replace(" GMT", "").strip()
        expiration_date = datetime.datetime.strptime(
            clean_date, "%a, %d %b %Y %H:%M:%S"
        )
        return pytz.utc.localize(expiration_date)
    except (ValueError, TypeError) as e:
        print(f"❌ Date parsing failed for '{raw_date_str}': {e}")
        return None


def parse_iso_date(raw_date_str):
    """Parse an ISO 8601 timestamp such as '2026-10-16T23:31:44+02:00'."""
    if not raw_date_str:
        return None

    raw_date_str = str(raw_date_str).strip()
    if raw_date_str.upper() in {"N/A", "NONE", "UNKNOWN"}:
        return None

    try:
        # Python 3.9/3.10 do not accept a trailing 'Z' in fromisoformat().
        parsed = datetime.datetime.fromisoformat(
            raw_date_str.replace("Z", "+00:00")
        )
        if parsed.tzinfo is None:
            if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            parsed = DHAKA_TZ.localize(parsed)
        return parsed
    except (ValueError, TypeError) as e:
        print(f"❌ ISO date parsing failed for '{raw_date_str}': {e}")
        return None


def get_event_date(events, action):
    """Returns the eventDate for an RDAP event action, if present."""
    return next(
        (
            event.get("eventDate")
            for event in events
            if isinstance(event, dict) and event.get("eventAction") == action
        ),
        None,
    )


def format_date(value, include_time=False):
    """Formats an aware datetime in Dhaka time."""
    if not value:
        return "unknown"

    local = value.astimezone(DHAKA_TZ)
    if include_time:
        return local.strftime("%d %b %Y, %I:%M %p GMT+6")
    return local.strftime("%d %b %Y")


def format_duration(delta):
    """Formats a timedelta as a compact duration, e.g. '360d 6h'."""
    total_seconds = int(abs(delta.total_seconds()))
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes = remainder // 60

    if days:
        return f"{days}d {hours}h" if hours else f"{days}d"
    if hours:
        return f"{hours}h {minutes}m" if minutes else f"{hours}h"
    return f"{minutes}m"


def status_key(status):
    """Normalizes a status for comparison with ALERT_STATUSES."""
    return re.sub(r"[\s_-]+", " ", str(status).strip().lower())


def format_statuses(statuses):
    """Formats EPP/registry statuses without long documentation URLs."""
    if isinstance(statuses, str):
        statuses = [statuses]

    cleaned = []
    for status in statuses or []:
        if not status:
            continue

        text = (
            str(status)
            .replace("-", " ")
            .replace("_", " ")
            .strip()
        )
        text = re.sub(
            r"\bgrace(\d)\b",
            r"grace period \1",
            text,
            flags=re.IGNORECASE,
        )
        text = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", text)
        text = text.title()
        if text:
            cleaned.append(html.escape(text))

    return " · ".join(dict.fromkeys(cleaned))


def format_registrar(record):
    """Formats the registrar/registrant line for a domain block."""
    registrar = str(record.get("registrar") or "").strip()
    if not registrar or registrar.lower() in {"unknown", "n/a", "none"}:
        if record.get("source") == "denic":
            return "🏢 Registry: DENIC (registrar not published)"
        return ""

    label = record.get("registrar_label") or "Registrar"
    return f"🏢 {label}: {html.escape(registrar)}"


def normalize_domain_info(domain, info):
    """Converts the different API payloads into one record used by the report."""
    record = {
        "domain": domain,
        "source": "unknown",
        "registrar": None,
        "registrar_label": "Registrar",
        "registered": None,
        "expires": None,
        "expiry_time_known": True,
        "last_changed": None,
        "statuses": [],
        "auto_renew": None,
        "error": None,
    }

    if not isinstance(info, dict) or not info:
        record["error"] = "No data returned"
        return record

    # Spaceship's registrar API (already normalized by spaceship_lookup).
    if info.get("source") == "spaceship":
        record["source"] = "spaceship"
        record["registrar"] = info.get("registrar") or "Spaceship"
        events = info.get("events") or []
        record["registered"] = parse_iso_date(
            get_event_date(events, "registration")
        )
        record["expires"] = parse_iso_date(
            info.get("expiresOn") or get_event_date(events, "expiration")
        )
        statuses = info.get("status") or []
        if isinstance(statuses, str):
            statuses = [statuses]
        record["statuses"] = [
            status
            for status in statuses
            if isinstance(status, str) and status.lower() != "registered"
        ]
        record["auto_renew"] = info.get("autoRenew")
        return record

    if info.get("success") is False:
        record["error"] = str(
            info.get("error")
            or info.get("message")
            or "WHOIS API returned an error"
        )
        return record

    # BD WHOIS API.
    data = info.get("data")
    if isinstance(data, dict) and any(
        key in data for key in ("expiry", "activation", "registrant")
    ):
        record["source"] = "bd"
        record["registrar"] = data.get("registrant")
        record["registrar_label"] = "Registrant"
        record["registered"] = parse_expiration_date(data.get("activation"))
        record["expires"] = parse_expiration_date(data.get("expiry"))
        record["expiry_time_known"] = False
        return record

    # DENIC RDAP fallback. DENIC uses "status" and normally has no expiresOn.
    if "status" in info and "statuses" not in info:
        record["source"] = "denic"
        events = info.get("events") or []
        statuses = info.get("status") or []
        if isinstance(statuses, str):
            statuses = [statuses]
        record["statuses"] = [
            status for status in statuses if isinstance(status, str)
        ]
        record["last_changed"] = parse_iso_date(
            get_event_date(events, "last changed")
        )
        record["expires"] = parse_iso_date(
            info.get("expiresOn") or get_event_date(events, "expiration")
        )
        return record

    # IANA RDAP wrapper (sayed.app API).
    if "expiresOn" in info or "domainName" in info:
        record["source"] = "rdap"
        record["registrar"] = info.get("registrar")
        record["registered"] = parse_expiration_date(info.get("registeredOn"))
        record["expires"] = parse_expiration_date(info.get("expiresOn"))
        record["last_changed"] = parse_expiration_date(
            info.get("lastUpdated")
        )
        statuses = info.get("statuses") or []
        record["statuses"] = [
            status.get("label")
            for status in statuses
            if isinstance(status, dict) and status.get("label")
        ]
        return record

    record["error"] = "Unrecognized WHOIS response"
    return record


def get_urgency(record, now, alert_days, warn_days):
    """Classifies a record by urgency."""
    if record["error"]:
        return "error"

    if any(
        status_key(status) in ALERT_STATUSES
        for status in record["statuses"]
    ):
        return "critical"

    if record["expires"] is None:
        return "unknown"

    remaining_seconds = (record["expires"] - now).total_seconds()
    if remaining_seconds <= 0:
        return "expired"
    if remaining_seconds <= alert_days * 86400:
        return "critical"
    if remaining_seconds <= warn_days * 86400:
        return "warning"
    return "healthy"


def format_domain_block(record, now, urgency):
    """Formats one compact domain block for the Telegram report."""
    domain = html.escape(record["domain"])

    if record["error"]:
        return [
            f"❓ <b>{domain}</b> — lookup failed",
            f"⚠️ {html.escape(record['error'])}",
        ]

    if record["expires"] is None:
        status_text = format_statuses(record["statuses"])
        lines = [
            f"{URGENCY_EMOJI.get(urgency, 'ℹ️')} <b>{domain}</b> — status only"
        ]
        if status_text:
            lines.append(f"🔒 {status_text}")
        if record["last_changed"]:
            lines.append(
                f"🕒 Last changed {format_date(record['last_changed'])}"
            )

        registrar_line = format_registrar(record)
        if registrar_line:
            lines.append(registrar_line)

        if not status_text and not record["last_changed"]:
            lines.append("⚠️ No expiry date returned")
        return lines

    remaining = record["expires"] - now
    if remaining.total_seconds() <= 0:
        headline = (
            f"🔥 <b>{domain}</b> — expired "
            f"{format_duration(remaining)} ago"
        )
    else:
        headline = (
            f"{URGENCY_EMOJI.get(urgency, 'ℹ️')} <b>{domain}</b> — "
            f"{format_duration(remaining)} left"
        )

    lines = [headline]
    expiry_text = format_date(
        record["expires"], include_time=record["expiry_time_known"]
    )

    if record["registered"]:
        lines.append(
            f"📅 {format_date(record['registered'])} → {expiry_text}"
        )
    else:
        lines.append(f"📅 Expires {expiry_text}")

    registrar_line = format_registrar(record)
    if registrar_line:
        lines.append(registrar_line)

    if record["auto_renew"] is not None:
        lines.append(
            f"🔄 Auto-renew: {'On' if record['auto_renew'] else 'Off'}"
        )

    status_text = format_statuses(record["statuses"])
    if status_text:
        lines.append(f"🔒 {status_text}")

    return lines


def price_usd(domain, bdt_per_usd):
    """Yearly renewal price in USD, or None when the domain has no price set."""
    price = RENEWAL_PRICES.get(domain)
    if not price:
        return None
    amount, currency = price
    if currency == "BDT":
        return amount / bdt_per_usd
    if currency == "EUR":
        return amount * USD_PER_EUR
    return amount


def format_price(domain, bdt_per_usd):
    """Formats the renewal price line for a domain block."""
    usd = price_usd(domain, bdt_per_usd)
    if usd is None:
        return ""
    amount, currency = RENEWAL_PRICES[domain]
    if currency == "BDT":
        return f"💵 ৳{amount:,.0f}/yr (≈ ${usd:.2f})"
    if currency == "EUR":
        return f"💵 €{amount:.2f}/yr (≈ ${usd:.2f})"
    return f"💵 ${usd:.2f}/yr"


def build_cost_plan(records, now, bdt_per_usd, last_year=COST_PLAN_LAST_YEAR):
    """Lists what renews in each calendar year up to last_year, from expiry dates."""
    years = {year: [] for year in range(now.year, last_year + 1)}
    for record in records:
        usd = price_usd(record["domain"], bdt_per_usd)
        expires = record["expires"] or EXPIRY_FALLBACK.get(record["domain"])
        if usd is None or expires is None:
            continue
        # Each renewal is paid at the expiry date and pushes it one year on.
        for year in range(expires.year, last_year + 1):
            if year in years:
                years[year].append((expires.month, record["domain"], usd))

    lines = [f"📆 <b>Renewal cost by year (to {last_year})</b>"]
    grand_total = 0.0
    for year, items in years.items():
        if not items:
            lines.append(f"\n<b>{year}</b> — nothing due")
            continue
        total = sum(usd for _, _, usd in items)
        grand_total += total
        lines.append(
            f"\n<b>{year}</b> — <b>${total:,.2f}</b> "
            f"(≈ ৳{total * bdt_per_usd:,.0f}) · {len(items)} renewals"
        )
        lines.append(
            " · ".join(
                f"{html.escape(domain)} {datetime.date(2000, month, 1):%b}"
                for month, domain, _ in sorted(items)
            )
        )
    lines.append(
        f"\n💰 Total {now.year}–{last_year}: <b>${grand_total:,.2f}</b> "
        f"(≈ ৳{grand_total * bdt_per_usd:,.0f})"
    )
    return "\n".join(lines)


def build_report(
    records,
    now=None,
    alert_days=DEFAULT_ALERT_DAYS,
    warn_days=DEFAULT_WARN_DAYS,
    bdt_per_usd=DEFAULT_BDT_PER_USD,
):
    """Builds the consolidated Telegram HTML report."""
    now = now or get_dhaka_time()
    counts = {
        key: 0
        for key in (
            "error",
            "expired",
            "critical",
            "warning",
            "healthy",
            "unknown",
        )
    }
    entries = []

    for record in records:
        urgency = get_urgency(record, now, alert_days, warn_days)
        counts[urgency] += 1
        entries.append((record, urgency))

    urgency_rank = {
        "error": 0,
        "expired": 1,
        "critical": 2,
        "warning": 3,
        "healthy": 4,
        "unknown": 5,
    }
    max_date = datetime.datetime.max.replace(tzinfo=datetime.timezone.utc)
    entries.sort(
        key=lambda item: (
            urgency_rank[item[1]],
            item[0]["expires"] or max_date,
            item[0]["domain"],
        )
    )

    header = [
        "📋 <b>Domain Watch</b>",
        f"🕘 {now.strftime('%d %b %Y, %I:%M %p')} GMT+6",
    ]

    summary_parts = [f"<b>{len(records)}</b> domains"]
    if counts["healthy"]:
        summary_parts.append(f"✅ {counts['healthy']} healthy")
    if counts["warning"]:
        summary_parts.append(f"🟡 {counts['warning']} watch")
    if counts["critical"] or counts["expired"]:
        urgent_count = counts["critical"] + counts["expired"]
        summary_parts.append(f"🚨 {urgent_count} urgent")
    if counts["unknown"]:
        summary_parts.append(f"ℹ️ {counts['unknown']} status-only")
    if counts["error"]:
        summary_parts.append(f"❓ {counts['error']} failed")
    header.append("📊 " + " · ".join(summary_parts))

    prices = [price_usd(record["domain"], bdt_per_usd) for record in records]
    total_usd = sum(p for p in prices if p is not None)
    if total_usd:
        header.append(
            f"💰 Yearly renewals: <b>${total_usd:,.2f}</b> "
            f"(≈ ৳{total_usd * bdt_per_usd:,.0f} at ৳{bdt_per_usd:g}/$)"
        )

    upcoming = [
        (record, record["expires"] - now)
        for record, _ in entries
        if record["expires"] and record["expires"] > now
    ]
    if upcoming:
        next_record, next_delta = min(upcoming, key=lambda item: item[1])
        header.append(
            "⏰ Next renewal: "
            f"<b>{html.escape(next_record['domain'])}</b> in "
            f"{format_duration(next_delta)}"
        )

    section_defs = [
        ("❓ <b>Lookup failed</b>", ("error",)),
        ("🚨 <b>Needs attention</b>", ("expired", "critical")),
        ("🟡 <b>Watch</b>", ("warning",)),
        ("✅ <b>Healthy</b>", ("healthy",)),
        ("ℹ️ <b>Status only</b>", ("unknown",)),
    ]

    parts = ["\n".join(header)]
    for title, urgencies in section_defs:
        blocks = [
            "\n".join(
                format_domain_block(record, now, urgency)
                + [
                    line
                    for line in [format_price(record["domain"], bdt_per_usd)]
                    if line
                ]
            )
            for record, urgency in entries
            if urgency in urgencies
        ]
        if blocks:
            parts.append(f"{title}\n\n" + "\n\n".join(blocks))

    parts.append(build_cost_plan(records, now, bdt_per_usd))

    has_alerts = (
        counts["error"] > 0
        or counts["expired"] > 0
        or counts["critical"] > 0
    )

    return {
        "text": "\n\n".join(parts),
        "counts": counts,
        "has_alerts": has_alerts,
    }


def _hard_split(text, max_length):
    """Splits a single oversized block without losing any text."""
    chunks = []
    while len(text) > max_length:
        split_at = text.rfind("\n", 0, max_length)
        if split_at <= 0:
            split_at = max_length
        chunks.append(text[:split_at].rstrip())
        text = text[split_at:].lstrip("\n")
    if text:
        chunks.append(text)
    return chunks


def split_telegram_message(message, max_length=TELEGRAM_MAX_LENGTH):
    """Splits a report at block boundaries to stay under Telegram's limit."""
    if not message:
        return []
    if len(message) <= max_length:
        return [message]

    chunks = []
    current = ""

    for block in message.split("\n\n"):
        block = block.strip()
        if not block:
            continue

        candidate = f"{current}\n\n{block}" if current else block
        if len(candidate) <= max_length:
            current = candidate
            continue

        if current:
            chunks.append(current)

        if len(block) > max_length:
            chunks.extend(_hard_split(block, max_length))
            current = ""
        else:
            current = block

    if current:
        chunks.append(current)

    return chunks


def send_telegram_message(
    message,
    bot_token,
    chat_id,
    disable_notification=False,
    retries=3,
):
    """Sends an HTML message to Telegram, retrying rate limits/server errors."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML",
        "disable_web_page_preview": True,
        "disable_notification": disable_notification,
    }

    for attempt in range(retries):
        try:
            response = requests.post(url, json=payload, timeout=15)

            if response.status_code == 429:
                retry_after = 5
                try:
                    retry_after = float(
                        response.json()
                        .get("parameters", {})
                        .get("retry_after", 5)
                    )
                except (ValueError, TypeError, AttributeError):
                    pass
                retry_after = max(1.0, min(retry_after, 60.0))
                if attempt < retries - 1:
                    print(
                        f"⏳ Telegram rate limit; retrying in "
                        f"{retry_after:g}s..."
                    )
                    time.sleep(retry_after)
                    continue
                print("⚠️ Telegram rate limit; retries exhausted.")
                return False

            if 400 <= response.status_code < 500:
                print(
                    "⚠️ Telegram rejected the message "
                    f"(HTTP {response.status_code}): "
                    f"{response.text[:300]}"
                )
                return False

            response.raise_for_status()
            print("✅ Telegram message sent.")
            return True

        except requests.exceptions.RequestException as e:
            # Do not print the raw exception: requests can include the bot
            # token in the request URL.
            print(f"⚠️ Telegram send failed: {type(e).__name__}")
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"⏳ Waiting {wait_time}s before Telegram retry...")
                time.sleep(wait_time)

    print("💀 Telegram message could not be sent.")
    return False


def main():
    """Checks all domains and sends one consolidated Telegram report."""
    domains = [
        "sayed.blog",
        "sayed.page",
        "sayed.dev",
        "sayed.app",
        "abusayed.dev",
        "abusayed.de",
        "nayem.page",
        "lrs.bd",
        "tracker.bd",
        "nextshop.com.bd",
        "kriti.app",
    ]

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    dry_run = os.environ.get("WHOIS_DRY_RUN", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    alert_days = max(0, env_int("WHOIS_ALERT_DAYS", DEFAULT_ALERT_DAYS))
    warn_days = max(
        alert_days, env_int("WHOIS_WARN_DAYS", DEFAULT_WARN_DAYS)
    )
    request_delay = max(
        0.0,
        env_float(
            "WHOIS_REQUEST_DELAY_SECONDS",
            DEFAULT_REQUEST_DELAY_SECONDS,
        ),
    )

    if not dry_run and (not bot_token or not chat_id):
        print(
            "⚠️ Telegram bot token or chat ID not found. "
            "Set WHOIS_DRY_RUN=1 to test without Telegram."
        )
        return

    start_time = time.monotonic()
    print(
        f"🚀 Checking {len(domains)} domains at "
        f"{get_dhaka_time().strftime('%d %b %Y, %I:%M %p')} GMT+6"
    )

    records = []
    for index, domain in enumerate(domains, 1):
        print(f"\n[{index}/{len(domains)}] {domain}")

        # A single short delay is enough for the public APIs. The old code
        # slept before and after every request, which doubled the runtime.
        if index > 1 and request_delay > 0:
            time.sleep(request_delay)

        info = whois_lookup(domain)
        record = normalize_domain_info(domain, info)
        records.append(record)

        if record["error"]:
            print(f"   ❌ {record['error']}")
        elif record["expires"]:
            print(
                "   ✅ expires "
                + format_date(
                    record["expires"],
                    include_time=record["expiry_time_known"],
                )
            )
        else:
            print("   ℹ️ no expiry date")

    report = build_report(
        records,
        alert_days=alert_days,
        warn_days=warn_days,
        bdt_per_usd=env_float("BDT_PER_USD", DEFAULT_BDT_PER_USD),
    )
    counts = report["counts"]

    print(
        "\n📊 Summary: "
        + (
            " · ".join(
                f"{key}={value}"
                for key, value in counts.items()
                if value
            )
            or "none"
        )
    )
    print(f"⏱️ Finished in {time.monotonic() - start_time:.1f}s")

    if dry_run:
        print("\n" + "=" * 60)
        print("DRY RUN REPORT (not sent to Telegram)")
        print("=" * 60)
        print(report["text"])
        return

    chunks = split_telegram_message(report["text"])
    print(f"✉️ Sending {len(chunks)} Telegram message(s)...")

    sent = 0
    for index, chunk in enumerate(chunks, 1):
        if index > 1:
            time.sleep(0.5)
        if send_telegram_message(
            chunk,
            bot_token,
            chat_id,
            disable_notification=not report["has_alerts"],
        ):
            sent += 1

    print(f"✅ Sent {sent}/{len(chunks)} message(s).")


if __name__ == "__main__":
    main()
