#!/usr/bin/env python3
"""
Pixelfed Image Scraper
Fetches all images from a Pixelfed account and saves them to JSON.
Designed to run daily via GitHub Actions.

Supports:
- Mastodon-compatible API (with access token) - Best method
- Atom feed parsing (fallback without token)
- Profile page scraping for account ID

Environment variable (recommended):
    PIXELFED_ACCESS_TOKEN - Your Pixelfed access token for API authentication
                           Get it from: https://pixelfed.social/settings/applications
"""

import json
import os
import re
import time
import requests
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin
from html import unescape


def strip_html(text: str) -> str:
    """Remove HTML tags and decode entities from text."""
    if not text:
        return text
    # Remove HTML tags
    clean = re.sub(r'<[^>]+>', ' ', text)
    # Decode HTML entities
    clean = unescape(clean)
    # Clean up whitespace
    clean = re.sub(r'\s+', ' ', clean).strip()
    return clean


# Configuration
PIXELFED_INSTANCE = "https://pixelfed.social"
USERNAME = "abusayed"
# Output to parent directory (project root) for GitHub Actions
SCRIPT_DIR = Path(__file__).parent
OUTPUT_FILE = str(SCRIPT_DIR.parent / "pixelfed_images.json")
RATE_LIMIT_DELAY = 1.5
MAX_RETRIES = 3
RETRY_DELAY = 5

# Get access token from environment variable
ACCESS_TOKEN = os.environ.get("PIXELFED_ACCESS_TOKEN", "")


def get_headers(accept: str = "application/json") -> dict:
    """Get HTTP headers for requests."""
    headers = {
        "Accept": accept,
        "User-Agent": "PixelfedImageScraper/2.0 (+https://github.com)"
    }
    if ACCESS_TOKEN:
        headers["Authorization"] = f"Bearer {ACCESS_TOKEN}"
    return headers


def make_api_request(url: str, params: dict = None):
    """Make an API request with error handling."""
    headers = get_headers()
    
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.get(url, params=params, headers=headers, timeout=30)
            
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", RETRY_DELAY))
                print(f"    Rate limited. Waiting {retry_after}s...")
                time.sleep(retry_after)
                continue
            
            if response.status_code in [401, 403, 404]:
                return None
            
            if response.status_code >= 500:
                if attempt < MAX_RETRIES - 1:
                    time.sleep(RETRY_DELAY)
                    continue
                return None
            
            response.raise_for_status()
            
            if not response.text.strip():
                return None
            
            return response.json()
            
        except (requests.exceptions.JSONDecodeError, requests.exceptions.RequestException) as e:
            if attempt < MAX_RETRIES - 1:
                time.sleep(RETRY_DELAY)
            else:
                print(f"    Request failed: {e}")
                return None
    
    return None


def get_account_id_from_avatar_url(instance: str, username: str):
    """Extract account ID from profile page (avatar URL contains the ID)."""
    try:
        url = f"{instance}/{username}"
        response = requests.get(url, headers=get_headers("text/html"), timeout=30)
        
        if response.status_code != 200:
            return None
        
        html = response.text
        
        # Pixelfed stores avatars at: /cache/avatars/{ACCOUNT_ID}/...
        # or /storage/avatars/{ACCOUNT_ID}/...
        patterns = [
            r'/(?:cache|storage)/avatars/(\d+)/',
            r'/avatars/(\d+)/',
            r'data-account-id=["\'](\d+)["\']',
            r'"account_id":\s*"?(\d+)"?',
            r'"id":\s*"?(\d{15,})"?',  # Pixelfed IDs are usually 18+ digits
        ]
        
        for pattern in patterns:
            match = re.search(pattern, html)
            if match:
                return match.group(1)
        
    except Exception as e:
        print(f"    Profile scraping error: {e}")
    
    return None


def get_account_id(instance: str, username: str):
    """Get account ID using multiple methods."""
    print(f"  Looking up account ID for @{username}...")
    
    # Method 1: API lookup (requires token on most instances)
    if ACCESS_TOKEN:
        print("    Trying API lookup...")
        result = make_api_request(f"{instance}/api/v1/accounts/lookup", {"acct": username})
        if result and "id" in result:
            print(f"    ✓ Found via API lookup")
            return result["id"]
        
        # Try search
        print("    Trying API search...")
        result = make_api_request(f"{instance}/api/v1/accounts/search", {"q": username, "limit": 5})
        if result and isinstance(result, list):
            for acc in result:
                if acc.get("username", "").lower() == username.lower():
                    print(f"    ✓ Found via API search")
                    return acc["id"]
    
    # Method 2: Scrape profile page
    print("    Trying profile page scraping...")
    account_id = get_account_id_from_avatar_url(instance, username)
    if account_id:
        print(f"    ✓ Found via profile scraping: {account_id}")
        return account_id
    
    print("    ✗ Could not find account ID")
    return None


def get_posts_via_api(instance: str, account_id: str) -> list:
    """Fetch posts using Mastodon-compatible API."""
    all_posts = []
    url = f"{instance}/api/v1/accounts/{account_id}/statuses"
    params = {
        "limit": 40,
        "only_media": "true",
        "exclude_replies": "true",
        "exclude_reblogs": "true"
    }
    
    max_id = None
    page = 1
    
    print("  Fetching posts via API...")
    
    while True:
        if max_id:
            params["max_id"] = max_id
        
        posts = make_api_request(url, params)
        
        if not posts:
            break
        
        all_posts.extend(posts)
        print(f"    Page {page}: {len(posts)} posts (total: {len(all_posts)})")
        
        if len(posts) < 40:
            break
        
        max_id = posts[-1]["id"]
        page += 1
        time.sleep(RATE_LIMIT_DELAY)
    
    return all_posts


def get_posts_via_atom_feed(instance: str, username: str) -> list:
    """Fetch posts from Atom feed (works without authentication)."""
    print("  Fetching posts via Atom feed...")
    all_posts = []
    
    try:
        atom_url = f"{instance}/users/{username}.atom"
        response = requests.get(atom_url, headers=get_headers("application/atom+xml"), timeout=30)
        
        if response.status_code != 200:
            print(f"    Atom feed returned {response.status_code}")
            return []
        
        # Parse Atom XML
        root = ET.fromstring(response.content)
        
        # Handle namespaces - Pixelfed uses both atom and media namespaces
        ns = {
            'atom': 'http://www.w3.org/2005/Atom',
            'media': 'http://search.yahoo.com/mrss/'
        }
        
        # Find all entries
        entries = root.findall('.//atom:entry', ns)
        if not entries:
            # Try without namespace
            entries = root.findall('.//entry')
        
        print(f"    Found {len(entries)} entries in feed")
        
        for entry in entries:
            post = {
                "id": None,
                "url": None,
                "content": None,
                "created_at": None,
                "media_attachments": [],
                "favourites_count": 0,
                "reblogs_count": 0,
                "replies_count": 0,
                "tags": [],
                "visibility": "public"
            }
            
            # Get ID
            id_elem = entry.find('atom:id', ns)
            if id_elem is None:
                id_elem = entry.find('id')
            if id_elem is not None and id_elem.text:
                post["id"] = id_elem.text
                post["url"] = id_elem.text  # The ID is also the URL
                # Extract numeric ID if possible
                id_match = re.search(r'/p/[^/]+/(\d+)', id_elem.text)
                if id_match:
                    post["id"] = id_match.group(1)
            
            # Get alternate URL link
            for link in entry.findall('atom:link', ns) + entry.findall('link'):
                rel = link.get('rel', 'alternate')
                href = link.get('href')
                if rel == 'alternate' and href:
                    post["url"] = href
            
            # Get published/updated date
            updated = entry.find('atom:updated', ns)
            if updated is None:
                updated = entry.find('updated')
            if updated is not None and updated.text:
                post["created_at"] = updated.text
            
            # Get content
            content = entry.find('atom:content', ns)
            if content is None:
                content = entry.find('content')
            if content is not None and content.text:
                post["content"] = content.text
            
            # Get title as fallback for content
            if not post["content"]:
                title = entry.find('atom:title', ns)
                if title is None:
                    title = entry.find('title')
                if title is not None and title.text:
                    post["content"] = title.text
            
            # Get media from media:content elements (Pixelfed's format)
            media_contents = entry.findall('media:content', ns)
            for media in media_contents:
                media_url = media.get('url')
                media_type = media.get('type', 'image/jpeg')
                medium = media.get('medium', 'image')
                
                if media_url and (medium == 'image' or media_type.startswith('image/')):
                    post["media_attachments"].append({
                        "id": None,
                        "type": "image",
                        "url": media_url,
                        "preview_url": media_url,
                        "description": None,
                        "blurhash": None,
                        "meta": {"type": media_type}
                    })
            
            # Also check for enclosure links (fallback)
            for link in entry.findall('atom:link[@rel="enclosure"]', ns) + entry.findall('link[@rel="enclosure"]'):
                href = link.get('href')
                link_type = link.get('type', '')
                if href and link_type.startswith('image/'):
                    # Check if not already added
                    if not any(m['url'] == href for m in post["media_attachments"]):
                        post["media_attachments"].append({
                            "id": None,
                            "type": "image",
                            "url": href,
                            "preview_url": href,
                            "description": None,
                            "blurhash": None,
                            "meta": {}
                        })
            
            # Extract hashtags from content
            if post["content"]:
                hashtags = re.findall(r'#(\w+)', post["content"])
                post["tags"] = hashtags
            
            # Only add posts with media
            if post["media_attachments"]:
                all_posts.append(post)
        
        print(f"    Extracted {len(all_posts)} posts with media")
        
    except ET.ParseError as e:
        print(f"    XML parsing error: {e}")
    except Exception as e:
        print(f"    Atom feed error: {e}")
    
    return all_posts


def scrape_posts_from_web(instance: str, username: str) -> list:
    """Scrape posts directly from the web profile (last resort)."""
    print("  Scraping posts from web profile...")
    all_posts = []
    
    try:
        url = f"{instance}/{username}"
        response = requests.get(url, headers=get_headers("text/html"), timeout=30)
        
        if response.status_code != 200:
            return []
        
        html = response.text
        
        # Find image URLs in the page
        # Pixelfed typically has images at /storage/m/_v2/{account_id}/...
        image_pattern = r'(https?://[^"\']+/storage/m/[^"\']+\.(?:jpg|jpeg|png|gif|webp))'
        images = re.findall(image_pattern, html, re.IGNORECASE)
        
        # Find post URLs
        post_pattern = rf'{re.escape(instance)}/p/(\d+)'
        post_ids = re.findall(post_pattern, html)
        
        print(f"    Found {len(images)} images and {len(post_ids)} post IDs")
        
        # Create basic post entries from found images
        seen_images = set()
        for img_url in images:
            if img_url in seen_images:
                continue
            seen_images.add(img_url)
            
            post = {
                "id": None,
                "url": None,
                "content": None,
                "created_at": None,
                "media_attachments": [{
                    "id": None,
                    "type": "image",
                    "url": img_url,
                    "preview_url": img_url,
                    "description": None,
                    "blurhash": None,
                    "meta": {}
                }],
                "favourites_count": 0,
                "reblogs_count": 0,
                "replies_count": 0,
                "tags": [],
                "visibility": "public"
            }
            all_posts.append(post)
        
    except Exception as e:
        print(f"    Web scraping error: {e}")
    
    return all_posts


def extract_images_from_posts(posts: list) -> list:
    """Extract image data from posts."""
    images = []
    
    for post in posts:
        attachments = post.get("media_attachments", [])
        
        for media in attachments:
            media_type = media.get("type", "image")
            if media_type not in ["image", "gifv"]:
                continue
            
            # Clean up the content text
            content = post.get("content", "")
            content_clean = strip_html(content) if content else None
            
            # Extract tag names (API returns dicts, Atom feed returns strings)
            raw_tags = post.get("tags", [])
            if raw_tags and isinstance(raw_tags[0], dict):
                tag_names = [t.get("name", "") for t in raw_tags if t.get("name")]
            else:
                tag_names = [t for t in raw_tags if isinstance(t, str)]
            
            image = {
                "id": media.get("id"),
                "post_id": post.get("id"),
                "url": media.get("url"),
                "preview_url": media.get("preview_url"),
                "remote_url": media.get("remote_url"),
                "description": media.get("description"),
                "blurhash": media.get("blurhash"),
                "meta": media.get("meta", {}),
                "post_url": post.get("url"),
                "post_content": content_clean,
                "post_content_html": content if content != content_clean else None,
                "created_at": post.get("created_at"),
                "visibility": post.get("visibility"),
                "favourites_count": post.get("favourites_count", 0),
                "reblogs_count": post.get("reblogs_count", 0),
                "replies_count": post.get("replies_count", 0),
                "tags": list(set(tag_names)),  # Remove duplicates
            }
            images.append(image)
    
    return images


def save_json(data: dict, filepath: str):
    """Save data to JSON file."""
    Path(filepath).parent.mkdir(parents=True, exist_ok=True)
    
    with open(filepath, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    
    print(f"  Saved to {filepath}")


def main():
    """Main entry point."""
    print("=" * 60)
    print("  Pixelfed Image Scraper v2.0")
    print("=" * 60)
    print(f"Instance:  {PIXELFED_INSTANCE}")
    print(f"Username:  {USERNAME}")
    print(f"Auth:      {'Token provided' if ACCESS_TOKEN else 'No token'}")
    print("=" * 60)
    
    start_time = datetime.now()
    posts = []
    method_used = "none"
    account_id = None
    
    # Step 1: Try to get account ID
    account_id = get_account_id(PIXELFED_INSTANCE, USERNAME)
    
    time.sleep(RATE_LIMIT_DELAY)
    
    # Step 2: Fetch posts using best available method
    print("\nFetching posts...")
    
    # Method 1: API (best, requires token and account_id)
    if account_id and ACCESS_TOKEN:
        posts = get_posts_via_api(PIXELFED_INSTANCE, account_id)
        if posts:
            method_used = "api"
    
    # Method 2: API without token (may work for public posts)
    if not posts and account_id:
        posts = get_posts_via_api(PIXELFED_INSTANCE, account_id)
        if posts:
            method_used = "api_public"
    
    # Method 3: Atom feed (no auth needed)
    if not posts:
        posts = get_posts_via_atom_feed(PIXELFED_INSTANCE, USERNAME)
        if posts:
            method_used = "atom_feed"
    
    # Method 4: Web scraping (last resort)
    if not posts:
        posts = scrape_posts_from_web(PIXELFED_INSTANCE, USERNAME)
        if posts:
            method_used = "web_scraping"
    
    print(f"\nResults:")
    print(f"  Posts found: {len(posts)}")
    print(f"  Method used: {method_used}")
    
    # Step 3: Extract images
    print("\nExtracting images...")
    images = extract_images_from_posts(posts)
    print(f"  Images found: {len(images)}")
    
    # Step 4: Save to JSON
    print("\nSaving data...")
    output = {
        "metadata": {
            "instance": PIXELFED_INSTANCE,
            "username": USERNAME,
            "account_id": account_id,
            "profile_url": f"{PIXELFED_INSTANCE}/{USERNAME}",
            "total_posts": len(posts),
            "total_images": len(images),
            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            "method": method_used,
            "version": "2.0.0"
        },
        "images": images
    }
    
    save_json(output, OUTPUT_FILE)
    
    # Done
    duration = (datetime.now() - start_time).total_seconds()
    print("\n" + "=" * 60)
    print("Scraping complete!")
    print(f"   Duration: {duration:.1f}s")
    print(f"   Images:   {len(images)}")
    print(f"   Output:   {OUTPUT_FILE}")
    print("=" * 60)


if __name__ == "__main__":
    main()
