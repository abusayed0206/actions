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
    """Fetches WHOIS information from the RDAP API with retry logic."""
    for attempt in range(retries):
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
                "Accept": "application/json"
            }
            response = requests.get(
                f"https://rdap.sayed.app/api/lookup/{domain}",
                timeout=30,
                headers=headers
            )
            print(f"🔎 {domain}: HTTP {response.status_code}")
            response.raise_for_status()
            data = response.json()
            print(f"✅ {domain}: Got response with keys: {list(data.keys())}")
            return data
        except requests.RequestException as e:
            print(f"⚠️ Attempt {attempt + 1}/{retries} failed for {domain}: {e}")
            if attempt < retries - 1:
                wait_time = (attempt + 1) * 3  # 3s, 6s, 9s
                print(f"⏳ Waiting {wait_time}s before retry...")
                time.sleep(wait_time)
            else:
                print(f"❌ All {retries} attempts failed for {domain}")
                return None

def parse_expiration_date(raw_date_str):
    """
    Parse expiration date from RDAP response.
    Handles format: "Tue, 12 Jan 2027 14:17:50 GMT"
    """
    if not raw_date_str:
        return None
    
    try:
        # Remove " GMT" at the end since %Z doesn't parse it reliably
        clean_date = raw_date_str.replace(" GMT", "").strip()
        
        # Parse the date: "Tue, 12 Jan 2027 14:17:50"
        expiration_date = datetime.datetime.strptime(clean_date, "%a, %d %b %Y %H:%M:%S")
        
        # Localize to UTC (RDAP returns UTC times)
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
    
    # Check if expiresOn field exists
    if 'expiresOn' not in domain_info:
        print(f"⚠️ {domain}: Missing 'expiresOn' field. Response keys: {list(domain_info.keys())}")
        return f"⚠️ {domain}: Could not retrieve expiration information."
    
    # Parse the expiration date
    raw_expires = domain_info.get("expiresOn")
    print(f"📅 {domain}: Raw expiresOn = {raw_expires}")
    
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
    
    # Get registrar name
    registrar_name = domain_info.get("registrar", "Unknown")
    
    # Format dates for display
    formatted_expiration_date = expiration_date_dhaka.strftime('%d %B, %Y')
    formatted_expiration_time = expiration_date_dhaka.strftime('%I:%M %p')  # 12-hour format with AM/PM
    
    # Status emoji based on remaining time
    if remaining_time.total_seconds() > 0:
        status_emoji = "✅ Everything fine"
    else:
        status_emoji = "🔥🚨 EXPIRED!"
    
    # Extract EPP status URLs
    epp_status_urls = []
    for status in domain_info.get("statuses", []):
        if isinstance(status, dict) and "url" in status:
            epp_status_urls.append(status["url"])
    
    epp_status_text = "\n".join([f"• {url}" for url in epp_status_urls]) if epp_status_urls else "• No EPP URLs found"
    
    # Format the message (using HTML for better compatibility)
    message = (
        f"🌐 <b>{domain}</b>\n"
        f"🏢 <b>Registrar:</b> {registrar_name}\n"
        f"⏳ <b>Expiration Date:</b> {formatted_expiration_date}\n"
        f"🕒 <b>Time:</b> {formatted_expiration_time} GMT+6\n"
        f"📆 <b>Remaining:</b> {remaining_days} days, {remaining_hours} hours\n"
        f"🔒 <b>EPP Status:</b>\n{epp_status_text}\n"
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
        "nayem.page"
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
        
        # Add delay before API call to avoid rate limiting
        if i > 1:
            time.sleep(5)
        
        # Fetch WHOIS data
        domain_info = whois_lookup(domain)
        
        # Format message
        message = format_expiration_message(domain_info, domain)
        
        # Send to Telegram
        print(f"✉️ Sending to Telegram...")
        send_telegram_message(message, bot_token, chat_id)
        
        # Small delay between Telegram messages
        time.sleep(1)

    print(f"\n✅ All domains processed!")

if __name__ == "__main__":
    main()
    
