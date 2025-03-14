import whois
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
    """Fetches WHOIS information for a given domain."""
    try:
        domain_info = whois.whois(domain)
        return domain_info
    except whois.exceptions.WhoisError:
        return None
    except Exception as e:
        print(f"An unexpected error occurred for {domain}: {e}")
        return None

def format_expiration_message(domain_info, domain):
    """Formats the expiration information for a domain in Dhaka time (GMT+6)."""
    if not domain_info or not hasattr(domain_info, 'expiration_date'):
        return f"⚠️ {domain}: Could not retrieve expiration information."

    expiration_date = domain_info.expiration_date
    if isinstance(expiration_date, list):
        expiration_date = expiration_date[0]

    if not isinstance(expiration_date, datetime.datetime):
        return f"⚠️ {domain}: Invalid expiration date format."

    utc_tz = pytz.utc
    dhaka_tz = pytz.timezone('Asia/Dhaka')
    now_dhaka = get_dhaka_time()

    # Convert expiration_date from UTC to Dhaka time
    if expiration_date.tzinfo is None or expiration_date.tzinfo.utcoffset(expiration_date) is None:
        expiration_date = utc_tz.localize(expiration_date).astimezone(dhaka_tz)
    else:
        expiration_date = expiration_date.astimezone(dhaka_tz)

    remaining_time = expiration_date - now_dhaka
    remaining_days = remaining_time.days
    remaining_hours = remaining_time.seconds // 3600  # Convert seconds to hours

    registrar = domain_info.registrar
    if isinstance(registrar, list):
        registrar = registrar[0]
    registrar_name = registrar if isinstance(registrar, str) else "Unknown"

    # Expiration message with formatting
    formatted_expiration_date = expiration_date.strftime('%d %B, %Y')
    formatted_expiration_time = expiration_date.strftime('%I:%M %p')  # 12-hour format with AM/PM

    status_emoji = "✅ সব ঠিক আছে" if remaining_days > 0 else "🔥🚨 EXPIRED!"

    # Add EPP status
    epp_status = domain_info.status if hasattr(domain_info, 'status') else "Unknown"
    if isinstance(epp_status, list):
        epp_status = "\n".join([f"- {status}" for status in epp_status]) #format the status.
    else:
        epp_status = f"- {epp_status}"

    message = (
        f"🌐 **{domain}**\n"
        f"🏢 **Registrar:** {registrar_name}\n"
        f"⏳ **Expiration Date:** {formatted_expiration_date}\n"
        f"🕒 **Time:** {formatted_expiration_time} GMT+6\n"
        f"📆 **Remaining:** {remaining_days} days, {remaining_hours} hours\n"
        f"🔒 **Domain Status:**\n{epp_status}\n"
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
        "abusayed.dev",
        "niralok.com",
        "pothik.app",
        "nextvisionengineering.com",
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