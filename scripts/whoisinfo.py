import datetime
import requests
import os
import pytz
import time

def get_dhaka_time():
    """Returns the current time in Dhaka timezone (GMT+6)."""
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    return datetime.datetime.now(dhaka_tz)

def whois_lookup(domain, retries=3):
    """Fetches WHOIS information from the appropriate API with retry logic and detailed logging."""
    # Check if domain is .bd domain
    if domain.endswith('.bd'):
        api_url = f"https://api.sayed.app/whoisbd/lookup?domain={domain}"
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

def format_expiration_message(domain_info, domain):
    """Formats the expiration information for a domain in Dhaka time (GMT+6)."""
    
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
        "nayem.page",
        "lrs.bd",
        "tracker.bd",
        "nextshop.com.bd"
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
    
