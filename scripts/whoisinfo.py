import datetime
import requests
import os
import pytz
import time

def get_dhaka_time():
    """Returns the current time in Dhaka timezone (GMT+6)."""
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    return datetime.datetime.now(dhaka_tz)

def whois_lookup(domain):
    """Fetches WHOIS information from the RDAP API."""
    try:
        response = requests.get(f"https://rdap.sayed.app/api/lookup/{domain}", timeout=10)
        response.raise_for_status()
        return response.json()
    except requests.RequestException as e:
        print(f"⚠️ Failed to fetch WHOIS info for {domain}: {e}")
        return None

def format_expiration_message(domain_info, domain):
    """Formats the expiration information for a domain in Dhaka time (GMT+6)."""
    if not domain_info or 'expiresOn' not in domain_info:
        return f"⚠️ {domain}: Could not retrieve expiration information."

    try:
        expiration_date = datetime.datetime.strptime(domain_info["expiresOn"], "%a, %d %b %Y %H:%M:%S %Z")
    except ValueError:
        return f"⚠️ {domain}: Invalid expiration date format."

    utc_tz = pytz.utc
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    now_dhaka = get_dhaka_time()

    expiration_date = utc_tz.localize(expiration_date).astimezone(dhaka_tz)
    remaining_time = expiration_date - now_dhaka
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.seconds // 3600  # Convert seconds to hours

    registrar_name = domain_info.get("registrar", "Unknown")

    # Expiration message with formatting
    formatted_expiration_date = expiration_date.strftime('%d %B, %Y')
    formatted_expiration_time = expiration_date.strftime('%I:%M %p')  # 12-hour format with AM/PM

    status_emoji = "✅ Everything fine" if remaining_days > 0 else "🔥🚨 EXPIRED!"

    # Extract EPP status URLs
    epp_status_urls = []
    for status in domain_info.get("statuses", []):
        if isinstance(status, dict) and "url" in status:
            epp_status_urls.append(status["url"])

    epp_status_text = "\n".join([f"- {url}" for url in epp_status_urls]) if epp_status_urls else "- No EPP URLs found"

    message = (
        f"🌐 **{domain}**\n"
        f"🏢 **Registrar:** {registrar_name}\n"
        f"⏳ **Expiration Date:** {formatted_expiration_date}\n"
        f"🕒 **Time:** {formatted_expiration_time} GMT+6\n"
        f"📆 **Remaining:** {remaining_days} days, {remaining_hours} hours\n"
        f"🔒 **EPP Status:**\n{epp_status_text}\n"
        f"{status_emoji}"
    )

    return message


def send_telegram_message(message, bot_token, chat_id):
    """Sends a message to a Telegram bot."""
    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": message,
        "parse_mode": "Markdown"
    }
    try:
        response = requests.post(url, json=payload)
        response.raise_for_status()
        print("✅ Telegram message sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"⚠️ Failed to send Telegram message: {e}")

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

    for domain in domains:
        domain_info = whois_lookup(domain)
        message = format_expiration_message(domain_info, domain)
        send_telegram_message(message, bot_token, chat_id)
        time.sleep(3)  # Delay of 3 seconds between messages

if __name__ == "__main__":
    main()
