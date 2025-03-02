import whois
import datetime
import requests
import os
import pytz

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
    now_dhaka = get_dhaka_time()  # Ensuring now_dhaka is timezone-aware

    # Convert expiration_date from UTC to Dhaka time
    if expiration_date.tzinfo is None or expiration_date.tzinfo.utcoffset(expiration_date) is None:
        expiration_date = utc_tz.localize(expiration_date).astimezone(dhaka_tz)
    else:
        expiration_date = expiration_date.astimezone(dhaka_tz)

    # Ensure both dates are timezone-aware before subtraction
    remaining_days = (expiration_date - now_dhaka).days

    registrar = domain_info.registrar
    if isinstance(registrar, list):
        registrar = registrar[0]
    registrar_name = registrar if isinstance(registrar, str) else "Unknown"

    # Formatting the message
    message = f"🌐 {domain}\n"
    message += f"Registrar: {registrar_name}\n"
    message += f"Expiration: {expiration_date.strftime('%Y-%m-%d %H:%M:%S %Z%z')}\n"

    if remaining_days < 0:
        message += f"🚨 EXPIRED! ({abs(remaining_days)} days ago)\n"
    else:
        message += f"Remaining: {remaining_days} days\n"

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
        print("Telegram message sent successfully.")
    except requests.exceptions.RequestException as e:
        print(f"Failed to send Telegram message: {e}")

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
        print("Telegram bot token or chat ID not found in environment variables.")
        return

    all_messages = ""
    for domain in domains:
        domain_info = whois_lookup(domain)
        message = format_expiration_message(domain_info, domain)
        all_messages += message + "\n\n"

    send_telegram_message(all_messages, bot_token, chat_id)

if __name__ == "__main__":
    main()
