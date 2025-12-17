#!/usr/bin/env python3
"""
Pixelfed Image Links Extractor
Extracts image URLs with dimensions from pixelfed_images.json
Outputs a simplified JSON array for easy consumption.
"""

import json
from pathlib import Path

# Paths
SCRIPT_DIR = Path(__file__).parent
INPUT_FILE = SCRIPT_DIR.parent / "pixelfed_images.json"
OUTPUT_FILE = SCRIPT_DIR.parent / "pixelfed.json"


def main():
    print("=" * 50)
    print("  Pixelfed Image Links Extractor")
    print("=" * 50)
    
    # Read input file
    if not INPUT_FILE.exists():
        print(f"Error: {INPUT_FILE} not found!")
        print("Run pixelfed_scraper.py first.")
        return
    
    print(f"Reading: {INPUT_FILE}")
    with open(INPUT_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    
    images = data.get("images", [])
    print(f"Total entries: {len(images)}")
    
    # Extract image links with dimensions
    image_links = []
    
    for img in images:
        url = img.get("url")
        if not url:
            continue
        
        # Skip videos (check URL extension and meta type)
        url_lower = url.lower()
        if any(ext in url_lower for ext in [".mp4", ".webm", ".mov", ".avi"]):
            continue
        
        # Get dimensions from meta
        meta = img.get("meta") or {}
        original = meta.get("original") or {}
        
        width = original.get("width")
        height = original.get("height")
        
        # If no dimensions in meta, skip or set to null
        entry = {
            "url": url,
            "width": width,
            "height": height
        }
        
        image_links.append(entry)
    
    print(f"Images extracted: {len(image_links)}")
    
    # Save output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(image_links, f, indent=2)
    
    print(f"Saved to: {OUTPUT_FILE}")
    print("=" * 50)


if __name__ == "__main__":
    main()
