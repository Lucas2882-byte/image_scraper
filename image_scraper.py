#!/usr/bin/env python3
"""
Image Scraper from a single URL

Usage examples:
  python image_scraper.py --url "https://example.com" --out "./images" --max 500 --delay 0.4
  python image_scraper.py --url "https://example.com/post" --same-domain --min-width 512 --min-height 512
  python image_scraper.py --url "https://example.com" --no-robots

Requires:
  pip install requests beautifulsoup4 pillow

Notes:
- By default, obeys robots.txt. Use --no-robots to skip (not recommended).
- Extracts images from <img src>, srcset, data-src, and meta og:image / twitter:image.
- Resolves relative URLs, deduplicates, and rate-limits requests.
"""

import argparse
import hashlib
import os
import re
import time
import mimetypes
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

try:
    from urllib import robotparser
except Exception:
    robotparser = None

try:
    from PIL import Image
    from io import BytesIO
    PIL_AVAILABLE = True
except Exception:
    PIL_AVAILABLE = False


DEFAULT_HEADERS = {
    "User-Agent": "Mozilla/5.0 (compatible; ImageScraper/1.0; +https://example.com/bot)"
}


def parse_args():
    p = argparse.ArgumentParser(description="Scrape and download images from a single URL.")
    p.add_argument("--url", required=True, help="Page URL to scrape images from")
    p.add_argument("--out", default="images", help="Output directory (default: images)")
    p.add_argument("--max", type=int, default=500, help="Max number of images to download (default: 500)")
    p.add_argument("--delay", type=float, default=0.3, help="Delay (seconds) between downloads (default: 0.3)")
    p.add_argument("--timeout", type=int, default=20, help="HTTP timeout seconds (default: 20)")
    p.add_argument("--same-domain", action="store_true", help="Only keep images hosted on the same domain as the page")
    p.add_argument("--min-width", type=int, default=0, help="Skip images smaller than this width (requires Pillow)")
    p.add_argument("--min-height", type=int, default=0, help="Skip images smaller than this height (requires Pillow)")
    p.add_argument("--no-robots", action="store_true", help="Do not check robots.txt (not recommended)")
    return p.parse_args()


def robots_allows(url: str, user_agent: str) -> bool:
    if robotparser is None:
        return True
    try:
        parsed = urlparse(url)
        robots_url = f"{parsed.scheme}://{parsed.netloc}/robots.txt"
        rp = robotparser.RobotFileParser()
        rp.set_url(robots_url)
        rp.read()
        return rp.can_fetch(user_agent, url)
    except Exception:
        # If robots.txt cannot be fetched or parsed, be permissive
        return True


def fetch_html(url: str, timeout: int) -> str:
    r = requests.get(url, headers=DEFAULT_HEADERS, timeout=timeout)
    r.raise_for_status()
    return r.text


def extract_image_urls(html: str, base_url: str) -> list[str]:
    soup = BeautifulSoup(html, "html.parser")
    urls = set()

    # <img src> and common lazy-loading attributes
    for img in soup.find_all("img"):
        candidates = []
        for attr in ("src", "data-src", "data-original", "data-lazy", "data-srcset", "data-original-src"):
            val = img.get(attr)
            if val:
                candidates.append(val)

        # srcset parsing
        srcset = img.get("srcset") or img.get("data-srcset")
        if srcset:
            for part in srcset.split(","):
                url_part = part.strip().split(" ")[0].strip()
                if url_part:
                    candidates.append(url_part)

        for c in candidates:
            full = urljoin(base_url, c)
            urls.add(full)

    # Open Graph / Twitter cards
    for prop in ("og:image", "twitter:image", "twitter:image:src"):
        tag = soup.find("meta", attrs={"property": prop}) or soup.find("meta", attrs={"name": prop})
        if tag and tag.get("content"):
            urls.add(urljoin(base_url, tag["content"].strip()))

    # Basic CSS background-image: url(...) inline styles
    # (This is heuristic and won't catch external CSS files.)
    style_urls = set(re.findall(r'url\\(([^)]+)\\)', html, flags=re.IGNORECASE))
    for su in style_urls:
        su = su.strip('\'"')
        if su and not su.lower().startswith("data:"):
            urls.add(urljoin(base_url, su))

    # Filter obvious non-image extensions
    allowed_exts = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".tiff", ".tif", ".avif"}
    filtered = []
    for u in urls:
        path = urlparse(u).path
        ext = os.path.splitext(path)[1].lower()
        if ext and ext in allowed_exts:
            filtered.append(u)
        else:
            # Keep if content-type can later confirm image
            filtered.append(u)

    return list(dict.fromkeys(filtered))  # preserve order, dedupe


def content_type_is_image(resp: requests.Response) -> bool:
    ctype = resp.headers.get("Content-Type", "").lower()
    return ctype.startswith("image/")


def infer_extension(resp: requests.Response, url: str) -> str:
    # Prefer URL extension
    ext = os.path.splitext(urlparse(url).path)[1].lower()
    if ext:
        return ext

    # Fall back to MIME type
    ctype = resp.headers.get("Content-Type", "").lower()
    if ctype:
        ext = mimetypes.guess_extension(ctype.split(";")[0].strip())
        if ext:
            return ext

    # Default
    return ".jpg"


def same_domain(base_url: str, target_url: str) -> bool:
    b = urlparse(base_url).netloc
    t = urlparse(target_url).netloc
    return b == t or t.endswith("." + b)


def ensure_dir(path: str):
    os.makedirs(path, exist_ok=True)


def hash_to_name(url: str, idx: int, ext: str) -> str:
    h = hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]
    return f"{idx:04d}_{h}{ext}"


def download_images(img_urls, base_url, out_dir, max_images, delay, timeout, only_same_domain, min_w, min_h):
    ensure_dir(out_dir)
    count = 0
    session = requests.Session()
    session.headers.update(DEFAULT_HEADERS)

    for i, img_url in enumerate(img_urls, start=1):
        if count >= max_images:
            break

        if only_same_domain and not same_domain(base_url, img_url):
            continue

        try:
            resp = session.get(img_url, stream=True, timeout=timeout)
            if resp.status_code >= 400:
                continue

            if not content_type_is_image(resp):
                # Some CDNs need a second try without stream to get headers right
                # Or the URL might be missing an extension but still serve an image.
                # We'll try to read a small piece and check with Pillow if available.
                if not PIL_AVAILABLE:
                    continue

            # Optional Pillow size check (requires loading content in memory)
            content = resp.content
            ext = infer_extension(resp, img_url)

            if PIL_AVAILABLE and (min_w or min_h):
                try:
                    im = Image.open(BytesIO(content))
                    w, h = im.size
                    if (min_w and w < min_w) or (min_h and h < min_h):
                        time.sleep(delay)
                        continue
                except Exception:
                    # If cannot open with Pillow, skip size filter
                    pass

            filename = hash_to_name(img_url, count + 1, ext)
            filepath = os.path.join(out_dir, filename)
            with open(filepath, "wb") as f:
                f.write(content)

            count += 1
            print(f"[{count}] Saved {img_url} -> {filepath}")
            time.sleep(delay)

        except KeyboardInterrupt:
            print("Interrupted by user.")
            break
        except Exception as e:
            # Skip on error
            print(f"Skip {img_url} ({e})")
            time.sleep(delay)
            continue

    return count


def main():
    args = parse_args()

    if not args.no_robots:
        if not robots_allows(args.url, DEFAULT_HEADERS["User-Agent"]):
            print("robots.txt disallows scraping this URL for the given user-agent. Use --no-robots to ignore (not recommended).")
            return

    try:
        html = fetch_html(args.url, timeout=args.timeout)
    except Exception as e:
        print(f"Failed to fetch page: {e}")
        return

    img_urls = extract_image_urls(html, base_url=args.url)
    print(f"Found {len(img_urls)} candidate image URLs. Starting downloads...")

    saved = download_images(
        img_urls,
        base_url=args.url,
        out_dir=args.out,
        max_images=args.max,
        delay=args.delay,
        timeout=args.timeout,
        only_same_domain=args.same_domain,
        min_w=args.min_width,
        min_h=args.min_height,
    )

    print(f"Done. Saved {saved} image(s) to '{args.out}'.")


if __name__ == "__main__":
    main()
