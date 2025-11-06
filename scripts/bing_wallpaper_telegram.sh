#!/bin/bash

# Bing Wallpaper to Telegram Script
# Fetches Bing daily wallpaper and posts to Telegram

set -e

echo "🔍 Fetching Bing wallpaper info..."

# Fetch image data from API
API_URL="https://bing.biturl.top/?resolution=UHD&format=json&index=0&mkt=random"
RESPONSE=$(curl -s -L -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  -H "Accept: application/json" \
  "$API_URL")

echo "API Response: $RESPONSE"

# Check if response is valid
if [ -z "$RESPONSE" ]; then
    echo "❌ Error: Empty response from API"
    exit 1
fi

# Parse JSON response using jq
IMAGE_URL=$(echo "$RESPONSE" | jq -r '.url')
COPYRIGHT=$(echo "$RESPONSE" | jq -r '.copyright')
COPYRIGHT_LINK=$(echo "$RESPONSE" | jq -r '.copyright_link')

# Validate parsed data
if [ -z "$IMAGE_URL" ] || [ "$IMAGE_URL" = "null" ]; then
    echo "❌ Error: Failed to parse image URL from response"
    exit 1
fi

echo "📥 Image URL: $IMAGE_URL"
echo "📷 Copyright: $COPYRIGHT"

# Download the image with progress and wait for completion
echo "⬇️ Downloading image..."
curl -L -H "User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36" \
  --progress-bar \
  --max-time 120 \
  --retry 3 \
  --retry-delay 2 \
  -o /tmp/bing_wallpaper.jpg \
  "$IMAGE_URL"

# Verify download
if [ ! -f /tmp/bing_wallpaper.jpg ]; then
    echo "❌ Error: Failed to download image"
    exit 1
fi

FILE_SIZE=$(wc -c < /tmp/bing_wallpaper.jpg)
if [ "$FILE_SIZE" -lt 1000 ]; then
    echo "❌ Error: Downloaded file is too small ($FILE_SIZE bytes)"
    exit 1
fi

echo "✅ Downloaded $FILE_SIZE bytes"

# Create caption
CAPTION="${CAPTION}📷 ${COPYRIGHT}%0A%0A"
CAPTION="${CAPTION}🔗 <a href='${IMAGE_URL}'>Image Link</a>%0A"
CAPTION="${CAPTION}ℹ️ <a href='${COPYRIGHT_LINK}'>More Info</a>%0A%0A"
CAPTION="${CAPTION}#BingWallpaper #DailyWallpaper #Wallpaper"

# Validate environment variables
if [ -z "$TELEGRAM_BOT_TOKEN" ] || [ -z "$TG_CHAT_ID" ]; then
    echo "❌ Error: TELEGRAM_BOT_TOKEN and TG_CHAT_ID must be set"
    exit 1
fi

# Send to Telegram
echo "📤 Sending to Telegram..."
TG_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendPhoto"

RESPONSE=$(curl -s -X POST "$TG_URL" \
  -F "chat_id=${TG_CHAT_ID}" \
  -F "photo=@/tmp/bing_wallpaper.jpg" \
  -F "caption=${CAPTION}" \
  -F "parse_mode=HTML")

# Check if Telegram upload was successful
if echo "$RESPONSE" | jq -e '.ok' > /dev/null 2>&1; then
    echo "✅ Successfully posted to Telegram!"
else
    echo "❌ Telegram API error:"
    echo "$RESPONSE" | jq '.'
    exit 1
fi

echo "🎉 Done!"

# Cleanup
rm -f /tmp/bing_wallpaper.jpg
