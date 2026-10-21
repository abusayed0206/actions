import datetime
import requests
import os
import pytz
import time

def get_dhaka_time():
    """Returns the current time in Dhaka timezone (GMT+6)."""
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    return datetime.datetime.now(dhaka_tz)

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
            print(f"📥 [{domain}] Spaceship status code: {response.status_code}")

            if response.status_code != 200:
                print(f"📥 [{domain}] Spaceship response body: {response.text[:300]}")

            if response.status_code in (401, 403):
                print(f"⚠️ [{domain}] Spaceship authorization failed. Check the API key/secret and domains:read scope.")
                return None
            if response.status_code == 404:
                print(f"⚠️ [{domain}] Domain not found in the Spaceship account.")
                return None

            response.raise_for_status()
            data = response.json()

            events = []
            if data.get("registrationDate"):
                events.append({"eventAction": "registration", "eventDate": data["registrationDate"]})
            if data.get("expirationDate"):
                events.append({"eventAction": "expiration", "eventDate": data["expirationDate"]})

            print(f"✅ [{domain}] Spaceship expirationDate: {data.get('expirationDate', 'NOT FOUND')}")

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
            print(f"❌ [{domain}] Spaceship request error: {type(e).__name__}: {e}")
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 5
                print(f"⏳ [{domain}] Waiting {wait_time}s before Spaceship retry...")
                time.sleep(wait_time)

    print(f"💀 [{domain}] Spaceship lookup failed after {retries} attempts; using DENIC RDAP.")
    return None

def whois_lookup(domain, retries=3):
    """Fetches WHOIS information from the appropriate API with retry logic and detailed logging."""
    domain = domain.lower()

    # .de domains are queried from Spaceship's registrar API when credentials
    # are available, because DENIC itself publishes no expiry date. If that
    # fails, fall back to DENIC RDAP for status/last-changed data.
    if domain.endswith('.bd'):
        api_url = f"https://api.sayed.app/whoisbd/lookup?domain={domain}"
    elif domain.endswith('.de'):
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
                "Accept": "application/json"
            }
            
            # Add bypass token for Cloudflare (to bypass bot protection)
            bypass_token = os.environ.get("CF_BYPASS_TOKEN")
            if bypass_token:
                headers["X-Bypass-Token"] = bypass_token
            
            print(f"🔎 [{domain}] Attempt {attempt + 1}/{retries}")
            print(f"📡 [{domain}] URL: {api_url}")
            print(f"📡 [{domain}] Headers: {headers}")
            
            response = requests.get(api_url, timeout=30, headers=headers)
            
            print(f"📥 [{domain}] Status Code: {response.status_code}")
            print(f"📥 [{domain}] Response Headers: {dict(response.headers)}")
            
            if response.status_code != 200:
                print(f"📥 [{domain}] Response Body: {response.text[:500]}")
            
            response.raise_for_status()
            data = response.json()
            
            print(f"✅ [{domain}] Success! Response keys: {list(data.keys())}")
            if domain.endswith('.bd'):
                print(f"✅ [{domain}] expiry: {data.get('data', {}).get('expiry', 'NOT FOUND')}")
            elif domain.endswith('.de'):
                print(f"✅ [{domain}] status: {data.get('status', 'NOT FOUND')}")
            else:
                print(f"✅ [{domain}] expiresOn: {data.get('expiresOn', 'NOT FOUND')}")
            return data
            
        except requests.exceptions.Timeout as e:
            print(f"⏰ [{domain}] TIMEOUT after 30s: {e}")
        except requests.exceptions.ConnectionError as e:
            print(f"🔌 [{domain}] CONNECTION ERROR: {e}")
        except requests.exceptions.HTTPError as e:
            print(f"🚫 [{domain}] HTTP ERROR: {e}")
            print(f"📥 [{domain}] Response Body: {e.response.text[:500] if e.response else 'No response'}")
        except requests.exceptions.RequestException as e:
            print(f"❌ [{domain}] REQUEST EXCEPTION: {type(e).__name__}: {e}")
        except Exception as e:
            print(f"💥 [{domain}] UNEXPECTED ERROR: {type(e).__name__}: {e}")
        
        if attempt < retries - 1:
            wait_time = (attempt + 1) * 10  # 10s, 20s (increased for rate limiting)
            print(f"⏳ [{domain}] Waiting {wait_time}s before retry...")
            time.sleep(wait_time)
        else:
            print(f"💀 [{domain}] All {retries} attempts failed!")
    
    return None

def parse_expiration_date(raw_date_str):
    """
    Parse expiration date from RDAP response or BD WHOIS response.
    Formats: 
    - "Tue, 12 Jan 2027 14:17:50 GMT" (RDAP)
    - "28/01/2030" (BD WHOIS)
    """
    if not raw_date_str:
        return None
    
    try:
        # Try BD format first (DD/MM/YYYY)
        if '/' in raw_date_str:
            expiration_date = datetime.datetime.strptime(raw_date_str, "%d/%m/%Y")
            # Assume end of day for BD dates (23:59:59 in BD timezone)
            dhaka_tz = pytz.timezone('Asia/Dhaka')
            expiration_date = expiration_date.replace(hour=23, minute=59, second=59)
            expiration_date = dhaka_tz.localize(expiration_date)
            return expiration_date
        else:
            # Try RDAP format
            clean_date = raw_date_str.replace(" GMT", "").strip()
            expiration_date = datetime.datetime.strptime(clean_date, "%a, %d %b %Y %H:%M:%S")
            expiration_date = pytz.utc.localize(expiration_date)
            return expiration_date
    except ValueError as e:
        print(f"❌ Date parsing failed for '{raw_date_str}': {e}")
        return None

def parse_iso_date(raw_date_str):
    """Parse an ISO 8601 timestamp such as '2026-10-16T23:31:44+02:00'."""
    if not raw_date_str:
        return None

    try:
        # Python 3.9/3.10 do not accept a trailing 'Z' in fromisoformat().
        parsed = datetime.datetime.fromisoformat(raw_date_str.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            dhaka_tz = pytz.timezone('Asia/Dhaka')
            if parsed.hour == 0 and parsed.minute == 0 and parsed.second == 0:
                parsed = parsed.replace(hour=23, minute=59, second=59)
            parsed = dhaka_tz.localize(parsed)
        return parsed
    except ValueError as e:
        print(f"❌ ISO date parsing failed for '{raw_date_str}': {e}")
        return None

def get_event_date(events, action):
    """Returns the eventDate for an RDAP event action, if present."""
    return next(
        (event.get('eventDate') for event in events
         if isinstance(event, dict) and event.get('eventAction') == action),
        None
    )

def format_de_message(domain_info, domain):
    """
    Formats a .de domain report from Spaceship (registrar) or DENIC (registry).

    DENIC does not publish expiration dates for .de domains. When Spaceship
    credentials are available, the registrar-side expiration date is included.
    Otherwise the report shows DENIC status and last-changed data only.
    """
    if not domain_info:
        return f"⚠️ {domain}: lookup failed - no data returned"

    dhaka_tz = pytz.timezone('Asia/Dhaka')
    source = domain_info.get('source')

    statuses = domain_info.get('status') or []
    if isinstance(statuses, str):
        statuses = [statuses]
    status_text = ", ".join(status.replace('-', ' ').title() for status in statuses) or "Unknown"

    events = domain_info.get('events') or []
    registration_raw = get_event_date(events, 'registration')
    last_changed_raw = get_event_date(events, 'last changed')
    expiration_raw = domain_info.get('expiresOn') or get_event_date(events, 'expiration')

    registrar = domain_info.get('registrar')
    message_lines = [
        f"🌐 <b>{domain}</b>",
        (f"🏢 <b>Registrar:</b> {registrar}" if registrar
         else "🏢 <b>Registry:</b> DENIC (registrar not published)"),
        f"🔒 <b>Status:</b> {status_text}",
    ]

    if registration_raw:
        registration_date = parse_iso_date(registration_raw)
        if registration_date:
            message_lines.append(
                f"📅 <b>Registered:</b> {registration_date.astimezone(dhaka_tz).strftime('%d %B, %Y')}"
            )

    if last_changed_raw:
        last_changed = parse_iso_date(last_changed_raw)
        if last_changed:
            last_changed_dhaka = last_changed.astimezone(dhaka_tz)
            message_lines.append(
                f"🕒 <b>Last Changed:</b> {last_changed_dhaka.strftime('%d %B, %Y %I:%M %p')} GMT+6"
            )

    if "autoRenew" in domain_info:
        message_lines.append(
            f"🔄 <b>Auto-renew:</b> {'On' if domain_info.get('autoRenew') else 'Off'}"
        )

    expired = False
    if expiration_raw:
        expiration_date = parse_iso_date(expiration_raw)
        if expiration_date:
            expiration_date_dhaka = expiration_date.astimezone(dhaka_tz)
            remaining_time = expiration_date_dhaka - get_dhaka_time()
            expired = remaining_time.total_seconds() <= 0
            message_lines.append(
                f"⏳ <b>Expiration Date:</b> {expiration_date_dhaka.strftime('%d %B, %Y')}"
            )
            message_lines.append(
                f"📆 <b>Remaining:</b> {remaining_time.days} days, {remaining_time.seconds // 3600} hours"
            )
    elif source == 'spaceship':
        message_lines.append("ℹ️ <b>Expiration:</b> Spaceship did not return an expiration date")
    else:
        message_lines.append("ℹ️ <b>Expiration:</b> Not published by DENIC (.de is open-ended)")

    statuses_lower = {status.lower() for status in statuses}
    if expired:
        message_lines.append("🔥🚨 EXPIRED!")
    elif statuses_lower & {"redemption", "redemption period", "redemptionperiod",
                           "pending delete", "pendingdelete"}:
        message_lines.append("🔥🚨 Domain is deleted or in redemption!")
    elif statuses_lower & {"grace1", "grace2"}:
        message_lines.append("🔥🚨 Domain has expired and is in a grace period!")
    elif statuses_lower & {"free", "available"}:
        message_lines.append("⚠️ Domain is available for registration!")
    elif statuses_lower & {"active", "connect", "registered"}:
        message_lines.append("✅ Everything fine")
    elif "creating" in statuses_lower:
        message_lines.append("⏳ Registration is being processed")
    else:
        message_lines.append(f"⚠️ Unusual domain status: {status_text}")

    return "\n".join(message_lines)

def format_expiration_message(domain_info, domain):
    """Formats the expiration information for a domain in Dhaka time (GMT+6)."""

    # .de domains use Spaceship/DENIC data; DENIC has no expiration date.
    if domain.lower().endswith('.de'):
        return format_de_message(domain_info, domain)

    # Check if we got a valid response
    if not domain_info:
        return f"⚠️ {domain}: API lookup failed - no data returned"
    
    # Determine if this is a BD domain response or RDAP response
    is_bd_domain = 'data' in domain_info and 'expiry' in domain_info.get('data', {})
    
    # Extract expiration date based on response type
    if is_bd_domain:
        raw_expires = domain_info.get('data', {}).get('expiry')
        if not raw_expires:
            print(f"⚠️ {domain}: Missing 'expiry' field in data. Response keys: {list(domain_info.keys())}")
            return f"⚠️ {domain}: Could not retrieve expiration information."
    else:
        if 'expiresOn' not in domain_info:
            print(f"⚠️ {domain}: Missing 'expiresOn' field. Response keys: {list(domain_info.keys())}")
            return f"⚠️ {domain}: Could not retrieve expiration information."
        raw_expires = domain_info.get("expiresOn")
    
    print(f"📅 {domain}: Raw expiration = {raw_expires}")
    
    # Parse the expiration date
    expiration_date = parse_expiration_date(raw_expires)
    
    if expiration_date is None:
        return f"⚠️ {domain}: Invalid expiration date format - {raw_expires}"
    
    # Get current time in Dhaka timezone
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    now_dhaka = get_dhaka_time()
    
    # Convert expiration date to Dhaka timezone
    expiration_date_dhaka = expiration_date.astimezone(dhaka_tz)
    
    # Calculate remaining time
    remaining_time = expiration_date_dhaka - now_dhaka
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.seconds // 3600  # Convert seconds to hours
    
    # Get registrar/registrant name based on response type
    if is_bd_domain:
        registrar_name = domain_info.get('data', {}).get('registrant', 'Unknown')
        registrar_label = 'Registrant'
    else:
        registrar_name = domain_info.get("registrar", "Unknown")
        registrar_label = 'Registrar'
    
    # Format dates for display
    formatted_expiration_date = expiration_date_dhaka.strftime('%d %B, %Y')
    formatted_expiration_time = expiration_date_dhaka.strftime('%I:%M %p')  # 12-hour format with AM/PM
    
    # Status emoji based on remaining time
    if remaining_time.total_seconds() > 0:
        status_emoji = "✅ Everything fine"
    else:
        status_emoji = "🔥🚨 EXPIRED!"
    
    # Extract EPP status URLs (only for RDAP responses)
    epp_status_text = ""
    if not is_bd_domain:
        epp_status_urls = []
        for status in domain_info.get("statuses", []):
            if isinstance(status, dict) and "url" in status:
                epp_status_urls.append(status["url"])
        
        epp_status_text = "\n".join([f"• {url}" for url in epp_status_urls]) if epp_status_urls else "• No EPP URLs found"
        epp_status_text = f"🔒 <b>EPP Status:</b>\n{epp_status_text}\n"
    
    # Format the message (using HTML for better compatibility)
    message = (
        f"🌐 <b>{domain}</b>\n"
        f"🏢 <b>{registrar_label}:</b> {registrar_name}\n"
        f"⏳ <b>Expiration Date:</b> {formatted_expiration_date}\n"
        f"🕒 <b>Time:</b> {formatted_expiration_time} GMT+6\n"
        f"📆 <b>Remaining:</b> {remaining_days} days, {remaining_hours} hours\n"
        f"{epp_status_text}"
        f"{status_emoji}"
    )
    
    return message

def send_telegram_message(message, bot_token, chat_id):
    """Sends a message to a Telegram bot."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "HTML"
    }
    try:
        response = requests.post(url, json=payload, timeout=10)
        response.raise_for_status()
        print("✅ Telegram message sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to send Telegram message: {e}")
        # Print response body for debugging
        if hasattr(e, 'response') and e.response is not None:
            print(f"📝 Response body: {e.response.text}")

def main():
    """Main function to check domain expiration and send a Telegram notification."""
    domains = [
        "sayed.blog",
        "sayed.page",
        "sayed.app",
        "abusayed.dev",
        "abusayed.de",
        "nayem.page",
        "lrs.bd",
        "tracker.bd",
        "nextshop.com.bd",
        "kriti.app"
    ]

    bot_token = os.environ.get("TELEGRAM_BOT_TOKEN")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")

    if not bot_token or not chat_id:
        print("⚠️ Telegram bot token or chat ID not found in environment variables.")
        return

    print(f"🚀 Starting domain expiration check at {get_dhaka_time()}\n")

    for i, domain in enumerate(domains, 1):
        print(f"\n{'='*60}")
        print(f"[{i}/{len(domains)}] Processing: {domain}")
        print(f"{'='*60}")
        
        # Add delay before API call to avoid rate limiting (1 RPS = 1 request per second)
        if i > 1:
            time.sleep(2)  # Wait 2 seconds between domains to respect rate limits
        
        # Fetch WHOIS data
        domain_info = whois_lookup(domain)
        
        # Format message
        message = format_expiration_message(domain_info, domain)
        
        # Send to Telegram
        print(f"✉️ Sending to Telegram...")
        send_telegram_message(message, bot_token, chat_id)
        
        # Delay between iterations to respect rate limits (1 RPS)
        if i < len(domains):
            time.sleep(1.5)

    print(f"\n✅ All domains processed!")

if __name__ == "__main__":
    main()
    
