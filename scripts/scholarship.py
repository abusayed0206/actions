import requests
from bs4 import BeautifulSoup
from datetime import datetime
import os

TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")
data_file = os.path.join(os.path.dirname(__file__), 'sent_notices.txt')

def load_sent_notices():
    if not os.path.exists(data_file):
        return set()
    with open(data_file, 'r', encoding='utf-8') as f:
        return set(line.strip() for line in f)

def save_sent_notice(notice_id):
    with open(data_file, 'a', encoding='utf-8') as f:
        f.write(f"{notice_id}\n")

def send_pdf_to_telegram(pdf_url, caption):
    try:
        pdf_data = requests.get(pdf_url, timeout=30).content
    except Exception as e:
        print(f"[ERROR] Failed to download PDF: {pdf_url} - {e}")
        return False
    files = {'document': ('notice.pdf', pdf_data)}
    data = {'chat_id': TELEGRAM_CHAT_ID, 'caption': caption}
    url = f'https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendDocument'
    response = requests.post(url, data=data, files=files)
    if not response.ok:
        print(f"[ERROR] Telegram send failed: {response.text}")
    return response.ok

def main():

    url = 'https://shed.gov.bd/site/view/scholarship/%E0%A6%B6%E0%A6%BF%E0%A6%95%E0%A7%8D%E0%A6%B7%E0%A6%BE%E0%A6%AC%E0%A7%83%E0%A6%A4%E0%A7%8D%E0%A6%A4%E0%A6%BF-%E0%A6%AC%E0%A6%BF%E0%A6%9C%E0%A7%8D%E0%A6%9E%E0%A6%AA%E0%A7%8D%E0%A6%A4%E0%A6%BF'
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, 'html.parser')
    except Exception as e:
        print(f"[ERROR] Failed to fetch the page: {url} - {e}")
        return

    table = soup.find('table', class_='bordered')
    if not table:
        print('[ERROR] Scholarship table not found on the page.')
        return
    tbody = table.find('tbody')
    from bs4.element import Tag
    if not tbody or not isinstance(tbody, Tag):
        print('[ERROR] Table body (tbody) not found or is not a valid tag.')
        return
    rows = tbody.find_all('tr')
    sent_notices = load_sent_notices()
    today = datetime.today().date()
    found_today = False

    for row in rows:
        tds = row.find_all('td')
        if len(tds) < 4:
            continue
        subject = tds[1].get_text(strip=True)
        pub_date = tds[2].get_text(strip=True)
        doc_link = tds[3].find('a')['href'] if tds[3].find('a') else ''
        if doc_link.startswith('//'):
            doc_link = 'https:' + doc_link
        elif doc_link.startswith('/'):
            doc_link = 'https://shed.gov.bd' + doc_link
        elif doc_link and not doc_link.startswith('http'):
            doc_link = 'https://shed.gov.bd/' + doc_link.lstrip('/')

        # Compare date with today
        try:
            date_obj = datetime.strptime(pub_date, '%Y-%m-%d').date()
            if date_obj == today:
                status = 'Published today'
            elif date_obj > today:
                status = 'Future'
            else:
                status = 'Past'
        except Exception:
            status = 'Invalid date'

        print(f"Subject: {subject}")
        print(f"Date: {pub_date} ({status})")
        print(f"Document: {doc_link}")
        print('-' * 40)

        # Send to Telegram if published today and not already sent
        if status == 'Published today' and doc_link and doc_link not in sent_notices:
            caption = f"{subject}\nDate: {pub_date}"
            if send_pdf_to_telegram(doc_link, caption):
                print(f"[INFO] Sent to Telegram: {subject}")
                save_sent_notice(doc_link)
                found_today = True
            else:
                print(f"[ERROR] Failed to send: {subject}")

    if not found_today:
        print("[INFO] No new notices published today.")

if __name__ == '__main__':
    main()