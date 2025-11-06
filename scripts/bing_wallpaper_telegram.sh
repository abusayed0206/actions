#!/bin/bash

# Bing Wallpaper to Telegram Script
# Fetches Bing daily wallpaper and posts to Telegram

set -e

echo "🔍 Fetching Bing wallpaper info..."

# Fetch image data from API
API_URL="https://bing.biturl.top/?resolution=UHD&format=json&index=0&mkt=random"
RESPONSE=$(curl -s -H "User-Agent: Mozilla/5.0" "$API_URL")

# Parse JSON response
IMAGE_URL=$(echo "$RESPONSE" | grep -o '"url":"[^"]*"' | cut -d'"' -f4)
COPYRIGHT=$(echo "$RESPONSE" | grep -o '"copyright":"[^"]*"' | cut -d'"' -f4)
COPYRIGHT_LINK=$(echo "$RESPONSE" | grep -o '"copyright_link":"[^"]*"' | cut -d'"' -f4)

echo "📥 Image URL: $IMAGE_URL"
echo "📷 Copyright: $COPYRIGHT"

# Download the image
echo "⬇️ Downloading image..."
curl -s -H "User-Agent: Mozilla/5.0" -o /tmp/bing_wallpaper.jpg "$IMAGE_URL"
echo "✅ Downloaded $(wc -c < /tmp/bing_wallpaper.jpg) bytes"

# Create caption
CAPTION="🖼️ <b>Bing Wallpaper of the Day</b>%0A%0A"
CAPTION="${CAPTION}📷 ${COPYRIGHT}%0A%0A"
CAPTION="${CAPTION}🔗 <a href='${IMAGE_URL}'>Image Link</a>%0A"
CAPTION="${CAPTION}ℹ️ <a href='${COPYRIGHT_LINK}'>More Info</a>%0A%0A"
CAPTION="${CAPTION}#BingWallpaper #DailyWallpaper #Photography #NaturePhotography #Wallpaper"

# Send to Telegram
echo "📤 Sending to Telegram..."
TG_URL="https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendPhoto"

curl -s -X POST "$TG_URL" \
  -F "chat_id=${TG_CHAT_ID}" \
  -F "photo=@/tmp/bing_wallpaper.jpg" \
  -F "caption=${CAPTION}" \
  -F "parse_mode=HTML" > /dev/null

echo "✅ Successfully posted to Telegram!"
echo "🎉 Done!"

# Cleanup
rm -f /tmp/bing_wallpaper.jpg
