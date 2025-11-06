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
    ('US', 'en-US'), ('JP', 'en-US'), ('AU', 'en-US'), ('GB', 'en-US'), 
    ('DE', 'en-US'), ('NZ', 'en-US'), ('CA', 'en-US'), ('IN', 'en-US'), 
    ('FR', 'en-US'), ('IT', 'en-US'), ('ES', 'en-US'), ('BR', 'en-US')
]

def fetch_lockscreen_image():
    """Fetch LockScreen images from Microsoft API (returns up to 4 images)"""
    # Select random locale
    country, locale = random.choice(LOCALES)
    print(f"🌍 Using country: {country}, locale: {locale}")
    
    # Use Windows 11 Spotlight API v4 with bcnt=4 to get maximum images
    api_url = f"https://fd.api.iris.microsoft.com/v4/api/selection?placement=88000820&bcnt=4&country={country}&locale={locale}&fmt=json"
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
        'Accept': 'application/json'
    }
    
    try:
        response = requests.get(api_url, headers=headers, timeout=30)
        response.raise_for_status()
        data = response.json()
        
        images = []
        
        # Parse the response
        if 'batchrsp' in data and 'items' in data['batchrsp']:
            items = data['batchrsp']['items']
            
            for idx, item in enumerate(items[:4]):  # Maximum 4 images
                if 'item' in item:
                    # The 'item' field contains a JSON string, parse it
                    import json
                    item_json = json.loads(item['item'])
                    
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
                            
                            images.append({
                                'url': image_url,
                                'title': title,
                                'copyright': copyright_text,
                                'index': idx + 1,
                                'country': country,
                                'locale': locale
                            })
            
            if images:
                print(f"✅ Found {len(images)} LockScreen images")
                return images
            else:
                print("❌ Error: No images found in API response")
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

def send_to_telegram(bot_token, chat_id, images_data):
    """Send multiple images to Telegram as a media group"""
    import json
    
    url = f"https://api.telegram.org/bot{bot_token}/sendMediaGroup"
    
    # Create a single caption with all image details
    caption = "🔒 <b>Windows LockScreen Images</b>\n\n"
    
    for img_data in images_data:
        image_info = img_data['info']
        caption += f"📸 <b>#{image_info['index']}: {image_info['title']}</b>\n"
        caption += f"📷 {image_info['copyright']}\n\n"
    
    # Add region info
    caption += f"🌍 Region: {images_data[0]['info']['country']} ({images_data[0]['info']['locale']})\n"
    
    # Create links for all images using wsrv.nl proxy
    links = []
    for idx, img_data in enumerate(images_data, 1):
        image_url = img_data['info']['url']
        wsrv_url = f"https://wsrv.nl/?url={image_url}"
        links.append(f"<a href='{wsrv_url}'>Link{idx}</a>")
    
    caption += f"🔗 {' | '.join(links)}\n"
    caption += f"\n#WindowsLockScreen #LockScreen #Wallpaper #Microsoft #Photography"
    
    # Prepare media group (up to 10 images, but we have max 4)
    media = []
    files_dict = {}
    
    for idx, img_data in enumerate(images_data):
        image_content = img_data['content']
        
        file_key = f"photo{idx}"
        files_dict[file_key] = (f'lockscreen_{idx}.jpg', image_content, 'image/jpeg')
        
        media_item = {
            'type': 'photo',
            'media': f'attach://{file_key}'
        }
        
        if idx == 0:  # Add caption to first image only
            media_item['caption'] = caption
            media_item['parse_mode'] = 'HTML'
        
        media.append(media_item)
    
    data = {
        'chat_id': chat_id,
        'media': json.dumps(media)  # Properly JSON-encode the media array
    }
    
    try:
        response = requests.post(url, files=files_dict, data=data, timeout=90)
        response.raise_for_status()
        result = response.json()
        
        if result.get('ok'):
            print(f"✅ Successfully posted {len(images_data)} images to Telegram!")
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
    
    # Use wsrv.nl as proxy for the image URL
    wsrv_url = f"https://wsrv.nl/?url={image_url}"
    
    # Create caption with HTML formatting
    caption = f"🔒 <b>Windows LockScreen</b>\n\n"
    caption += f"📝 {title}\n"
    caption += f"📷 {copyright_text}\n"
    caption += f"🌍 {country} ({locale})\n"
    caption += f"🔗 <a href='{wsrv_url}'>Image Link</a>\n"
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
    
    print("🔍 Fetching Windows LockScreen images...")
    lockscreen_images = fetch_lockscreen_image()
    
    # Download all images
    images_data = []
    for img_info in lockscreen_images:
        print(f"⬇️ Downloading image #{img_info['index']}: {img_info['title'][:50]}...")
        content = download_image(img_info['url'])
        if content:
            print(f"✅ Downloaded {len(content)} bytes")
            images_data.append({
                'content': content,
                'info': img_info
            })
    
    if not images_data:
        print("❌ Error: No images were downloaded successfully")
        sys.exit(1)
    
    print(f"📤 Sending {len(images_data)} images to Telegram...")
    send_to_telegram(bot_token, chat_id, images_data)
    
    print("🎉 Done!")

if __name__ == "__main__":
    main()
