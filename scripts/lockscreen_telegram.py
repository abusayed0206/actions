#!/usr/bin/env python3
"""
Fetch Windows LockScreen image and post it to Telegram
"""
import os
import sys
import random
import requests
from datetime import datetime

# Available locales for LockScreen
LOCALES = [
    ('US', 'en-US'), ('JP', 'ja-JP'), ('AU', 'en-AU'), ('GB', 'en-GB'), 
    ('DE', 'de-DE'), ('NZ', 'en-NZ'), ('CA', 'en-CA'), ('IN', 'en-IN'), 
    ('FR', 'fr-FR'), ('IT', 'it-IT'), ('ES', 'es-ES'), ('BR', 'pt-BR')
]

def fetch_lockscreen_image():
    """Fetch LockScreen image from Microsoft API"""
    # Select random locale
    country, locale = random.choice(LOCALES)
    print(f"🌍 Using country: {country}, locale: {locale}")
    
    # Use Windows 11 Spotlight API v4 with bcnt=1 to get only one image
    # This API works more reliably than v3
    api_url = f"https://fd.api.iris.microsoft.com/v4/api/selection?placement=88000820&bcnt=1&country={country}&locale={locale}&fmt=json"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        # Parse the response
        if 'batchrsp' in data and 'items' in data['batchrsp']:
            items = data['batchrsp']['items']
            
            if len(items) > 0 and 'item' in items[0]:
                # The 'item' field contains a JSON string, parse it
                import json
                item_json = json.loads(items[0]['item'])
                
                if 'ad' in item_json:
                    ad_data = item_json['ad']
                    
                    # Get image URL - use the asset URL directly (already at max quality)
                    image_url = ''
                    if 'landscapeImage' in ad_data and 'asset' in ad_data['landscapeImage']:
                        image_url = ad_data['landscapeImage']['asset']
                    elif 'portraitImage' in ad_data and 'asset' in ad_data['portraitImage']:
                        image_url = ad_data['portraitImage']['asset']
                    
                    if image_url:
                        title = ad_data.get('title', 'N/A')
                        copyright_text = ad_data.get('copyright', 'N/A')
                        
                        print(f"✅ Found LockScreen image")
                        return {
                            'url': image_url,
                            'title': title,
                            'copyright': copyright_text,
                            'country': country,
                            'locale': locale
                        }
                
                print("❌ Error: No image URL found in API response")
                sys.exit(1)
            else:
                print("❌ Error: No items found in API response")
                sys.exit(1)
        else:
            print("❌ Error: Invalid API response structure")
            sys.exit(1)
            
    except Exception as e:
        print(f"❌ Error fetching LockScreen API: {e}")
        sys.exit(1)

def download_image(image_url):
    """Download the image from URL with validation"""
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'image/webp,image/apng,image/*,*/*;q=0.8',
        'Referer': 'https://www.microsoft.com/'
    }
    
    try:
        response = requests.get(image_url, headers=headers, timeout=60, stream=True)
        response.raise_for_status()
        
        content = response.content
        
        # Check size - images should be at least 50KB
        # Note: Microsoft CDN may return Content-Type: text/plain but actual image data
        if len(content) < 50000:
            print(f"❌ Error: Image too small ({len(content)} bytes), likely placeholder")
            sys.exit(1)
        
        # Verify it's actually image data by checking magic bytes
        # JPEG starts with FF D8 FF
        # PNG starts with 89 50 4E 47
        if content[:3] == b'\xff\xd8\xff' or content[:4] == b'\x89PNG':
            print(f"✅ Downloaded valid image: {len(content)} bytes")
            return content
        else:
            print(f"❌ Error: Response is not valid image data (first bytes: {content[:10].hex()})")
            sys.exit(1)
        
    except Exception as e:
        print(f"❌ Error downloading image: {e}")
        sys.exit(1)

def send_to_telegram(bot_token, chat_id, image_data, caption):
    """Send image to Telegram"""
    url = f"https://api.telegram.org/bot{bot_token}/sendPhoto"
    
    files = {
        'photo': ('lockscreen.jpg', image_data, 'image/jpeg')
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
    title = data.get('title', 'N/A')
    copyright_text = data.get('copyright', 'N/A')
    image_url = data.get('url', 'N/A')
    country = data.get('country', 'N/A')
    locale = data.get('locale', 'N/A')
    
    # Create caption with HTML formatting
    caption = f"🔒 <b>Windows LockScreen</b>\n\n"
    caption += f"📝 {title}\n"
    caption += f"📷 {copyright_text}\n"
    caption += f"🌍 {country} ({locale})\n"
    caption += f"🔗 <a href='{image_url}'>Image Link</a>\n"
    caption += f"\n#WindowsLockScreen #LockScreen #Wallpaper #Microsoft"
    
    return caption

def main():
    """Main function"""
    # Get environment variables
    bot_token = os.environ.get('TELEGRAM_BOT_TOKEN')
    chat_id = os.environ.get('TG_CHAT_ID')
    
    if not bot_token or not chat_id:
        print("❌ Error: TELEGRAM_BOT_TOKEN and TG_CHAT_ID must be set")
        sys.exit(1)
    
    print("🔍 Fetching Windows LockScreen image...")
    lockscreen_data = fetch_lockscreen_image()
    
    print(f"📥 Found image: {lockscreen_data.get('title')}")
    
    print("⬇️ Downloading image...")
    image_data = download_image(lockscreen_data['url'])
    print(f"✅ Downloaded {len(image_data)} bytes")
    
    print("📝 Creating caption...")
    caption = create_caption(lockscreen_data)
    
    print("📤 Sending to Telegram...")
    send_to_telegram(bot_token, chat_id, image_data, caption)
    
    print("🎉 Done!")

if __name__ == "__main__":
    main()
