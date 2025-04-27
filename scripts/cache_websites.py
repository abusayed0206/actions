import requests
import json
import time

def save_to_wayback(url):
    save_url = f"https://web.archive.org/save/{url}"
    headers = {
        "User-Agent": "Mozilla/5.0 (WaybackBot/1.0)"
    }
    try:
        response = requests.get(save_url, headers=headers)
        if response.status_code == 200 or response.status_code == 302:
            print(f"Successfully submitted {url} for archiving.")
        else:
            print(f"Failed to archive {url}. Status code: {response.status_code}")
    except Exception as e:
        print(f"Error archiving {url}: {e}")

def main():
    with open("files/websites.json", "r") as f:
        websites = json.load(f)

    for url in websites:
        save_to_wayback(url)
        time.sleep(10)  # Be polite to the Wayback servers

if __name__ == "__main__":
    main()
