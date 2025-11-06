#!/usr/bin/env python3
"""
Fetch Bing wallpaper and post it to Telegram
"""
import os
import sys
import requests
from datetime import datetime

def fetch_bing_image():
    """Fetch image info from Bing API"""
    api_url = "https://bing.biturl.top/?resolution=UHD&format=json&index=0&mkt=random"
    
    # Add headers to avoid 403 Forbidden
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept': 'application/json, text/plain, */*',
        'Accept-Language': 'en-US,en;q=0.9',
        'Referer': 'https://bing.biturl.top/'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        return data
    except Exception as e:
        print(f"Error fetching Bing API: {e}")
        sys.exit(1)

def download_image(image_url):
    """Download the image from URL"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
    }
    
    try:
        response = requests.get(image_url, headers=headers, timeout=60)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"Error downloading image: {e}")
        sys.exit(1)

def send_to_telegram(bot_token, chat_id, image_data, caption):
    """Send image to Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    files = {
        'photo': ('bing_wallpaper.jpg', image_data, 'image/jpeg')
    }
    
    data = {
        'chat_id': chat_id,
        'caption': caption,
        'parse_mode': 'HTML'
    }
    
    try:
        response = requests.post(url, files=files, data=data, timeout=60)
        response.raise_for_status()
        result = response.json()
        
        if result.get('ok'):
            print("✅ Image successfully posted to Telegram!")
            return True
        else:
            print(f"❌ Telegram API error: {result}")
            return False
    except Exception as e:
        print(f"❌ Error sending to Telegram: {e}")
        sys.exit(1)

def create_caption(data):
    """Create formatted caption for Telegram"""
    copyright_text = data.get('copyright', 'N/A')
    image_url = data.get('url', 'N/A')
    copyright_link = data.get('copyright_link', '')
    
    # Create caption with HTML formatting
    caption = f"🖼️ <b>Bing Wallpaper of the Day</b>\n\n"
    caption += f"📷 {copyright_text}\n\n"
    caption += f"🔗 <a href='{image_url}'>Image Link</a>\n"
    
    if copyright_link:
        caption += f"ℹ️ <a href='{copyright_link}'>More Info</a>\n"
    
    caption += f"\n#BingWallpaper #DailyWallpaper #Photography #NaturePhotography #Wallpaper"
    
    return caption

def main():
    """Main function"""
    # Get environment variables
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    
    if not bot_token or not chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN and TG_CHAT_ID must be set")
        sys.exit(1)
    
    print("🔍 Fetching Bing wallpaper info...")
    bing_data = fetch_bing_image()
    
    print(f"📥 Found image: {bing_data.get('url')}")
    print(f"📅 Date: {bing_data.get('start_date')} - {bing_data.get('end_date')}")
    
    print("⬇️ Downloading image...")
    image_data = download_image(bing_data['url'])
    print(f"✅ Downloaded {len(image_data)} bytes")
    
    print("📝 Creating caption...")
    caption = create_caption(bing_data)
    
    print("📤 Sending to Telegram...")
    send_to_telegram(bot_token, chat_id, image_data, caption)
    
    print("🎉 Done!")

if __name__ == "__main__":
    main()
