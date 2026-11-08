"""Collect one Beijing-date issue from public feeds and the museum API."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urljoin, urlsplit, urlunsplit
from urllib.request import Request, urlopen
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
CHINA = timezone(timedelta(hours=8))
MUSEUM = "Cleveland Museum of Art"
MUSEUM_CDN = "openaccess-cdn.clevelandart.org"
OCR = "https://ocremix.org"
DAY_LIMIT = 4_000_000
UNKNOWN = "未知"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}


def warn(message):
    print(f"WARNING: {message}", file=sys.stderr, flush=True)


def safe_url(value, host, subdomains=False):
    parsed = urlsplit(value or "")
    name = parsed.hostname or ""
    if (
        parsed.scheme == "https"
        and (name == host or (subdomains and name.endswith("." + host)))
        and parsed.username is None and parsed.password is None
        and parsed.port in (None, 443)
    ):
        return urlunsplit(("https", name, parsed.path or "/", parsed.query, ""))
    return ""


def request(url, headers=None):
    return urlopen(Request(url, headers={
        "User-Agent": "ARTIFACT/1.0 (public art discovery, feed reader)",
        **(headers or {}),
    }), timeout=7)


def download(url, headers=None, check_redirect=None):
    with request(url, headers) as response:
        if check_redirect and not check_redirect(response.url):
            raise ValueError("unexpected page redirect")
        body = response.read(DAY_LIMIT + 1)
        if len(body) > DAY_LIMIT:
            raise ValueError("response exceeds size limit")
        return body


def text(value):
    return " ".join(unescape(re.sub(r"<[^>]*>", " ", value or "")).split())


def extract(pattern, html):
    match = re.search(pattern, html, re.I | re.S)
    return text(match[1]) if match else ""


class Metadata(HTMLParser):
    def __init__(self, html):
        super().__init__()
        self.values = {}
        self.feed(html)

    def handle_starttag(self, tag, attributes):
        attrs = dict(attributes)
        if tag == "meta" and attrs.get("content"):
            self.values[attrs.get("property") or attrs.get("name")] = attrs["content"]


def published(value):
    try:
        return parsedate_to_datetime(value).date()
    except (TypeError, ValueError, AttributeError):
        return None


def canonical(url):
    parts = urlsplit(url)
    host = "clevelandart.org" if parts.hostname == "www.clevelandart.org" else parts.hostname
    return f"{host}{parts.path.rstrip('/')}"


def candidate(kind, source, url, title, keywords="", **extra):
    stable_id = sha256(canonical(url).encode()).hexdigest()[:20]
    return {
        "id": stable_id, "kind": kind, "source": source, "url": url,
        "title": title or UNKNOWN, "keywords": keywords, **extra,
    }


def museum_candidates(config, day, first):
    base = "https://openaccess-api.clevelandart.org/api/artworks"
    queries = config["museum_queries"]
    start = (day.toordinal() * 3) % len(queries)
    for index in range(3):
        query = queries[(start + index) % len(queries)]
        params = {"q": query, "cc0": 1, "has_image": 1, "limit": 18}
        yield from museum_request(f"{base}/?{urlencode(params)}", query)
    if first and config.get("opening_artwork_id"):
        yield from museum_request(f"{base}/{int(config['opening_artwork_id'])}", "landscape", opening=True)


def museum_request(path, query, opening=False):
    try:
        records = json.loads(download(path))["data"]
        if isinstance(records, dict):
            records = [records]
        for rank, row in enumerate(records):
            if row.get("share_license_status") != "CC0" or row.get("type") not in {
                "Painting", "Print", "Drawing", "Photograph"
            }:
                continue
            url = safe_url(row.get("url"), "clevelandart.org", subdomains=True)
            images = row.get("images") or {}
            web = images.get("web") or {}
            image = safe_url(web.get("url"), MUSEUM_CDN)
            if not url or not image:
                continue
            large = images.get("print") or {}
            full = safe_url(large.get("url"), MUSEUM_CDN) if int(large.get("filesize") or 0) <= 5_000_000 else ""
            creators = [entry.get("description", "").split(" (", 1)[0] for entry in row.get("creators", [])]
            yield candidate("other", MUSEUM, url, row.get("title"), query, rank=rank, opening=opening,
                            author=", ".join(filter(None, creators)) or UNKNOWN, license="CC0",
                            image=image, full=full, width=int(web["width"]), height=int(web["height"]))
    except (OSError, ValueError, KeyError) as exc:
        warn(f"{MUSEUM} / {query}: {exc}")


def itch_candidates(config, day, first):
    # Browse feeds expose paging, so old favorites and recent catalog changes both surface.
    page = 1 if first else 1 + day.toordinal() % 7
    for feed in config["itch_feeds"]:
        try:
            path = feed["url"] if page == 1 else f"{feed['url']}?{urlencode({'page': page})}"
            entries = ET.fromstring(download(path)).findall("./channel/item")
            for rank, entry in enumerate(entries):
                url = safe_url(entry.findtext("link"), "itch.io", subdomains=True)
                image = safe_url(entry.findtext("imageurl"), "img.itch.zone")
                if url and image:
                    yield candidate(feed["kind"], "itch.io", url, entry.findtext("plainTitle"),
                                    text(entry.findtext("description")), rank=rank, image=image,
                                    published=published(entry.findtext("pubDate")))
        except (OSError, ValueError, ET.ParseError) as exc:
            warn(f"{feed['url']}: {exc}")


def music_candidates(day):
    try:
        rss = ET.fromstring(download(f"{OCR}/feeds/ten20/"))
        for rank, entry in enumerate(rss.findall("./channel/item")):
            url = safe_url(entry.findtext("link"), "ocremix.org").rstrip("/")
            if re.fullmatch(r"https://ocremix\.org/remix/OCR\d+", url):
                yield candidate("music", "OC ReMix", url, entry.findtext("title"), rank=rank,
                                published=published(entry.findtext("pubDate")))
    except (OSError, ValueError, ET.ParseError) as exc:
        warn(f"OC ReMix RSS: {exc}")

    # The RSS feed is short. Rotate through the public catalog for past releases.
    offset = 30 * (1 + day.toordinal() % 125)
    path = f"{OCR}/remixes/?offset={offset}&sort=datedesc"
    try:
        html = download(path).decode("utf-8", errors="replace")
        tracks = re.findall(r'href="(/remix/OCR\d+)"[^>]*class="main featured"[^>]*>(.*?)</a>', html, re.S)
        for rank, (link, title) in enumerate(tracks):
            yield candidate("music", "OC ReMix", OCR + link, text(title), rank=rank + 12)
    except (OSError, ValueError) as exc:
        warn(f"OC ReMix catalog: {exc}")


def load_details(item):
    host = {"itch.io": "itch.io", MUSEUM: "clevelandart.org", "OC ReMix": "ocremix.org"}[item["source"]]
    html = download(item["url"], check_redirect=lambda url: (
        bool(safe_url(url, host, subdomains=host != "ocremix.org"))
        and canonical(url) == canonical(item["url"])
    )).decode("utf-8", errors="replace")
    if item["source"] == MUSEUM:
        return
    meta = Metadata(html).values
    if item["source"] == "itch.io":
        if meta.get("og:site_name") != "itch.io":
            raise ValueError("itch.io project preview unavailable")
        item["author"] = extract(r"<td>\s*Author[s]?\s*</td>\s*<td>(.*?)</td>", html).replace(" ,", ",") or UNKNOWN
        official = safe_url(meta.get("og:image"), "img.itch.zone")
        if official:
            item["image"] = official
    else:
        if meta.get("og:type") != "music.song":
            raise ValueError("OC ReMix track unavailable")
        item["image"] = safe_url(meta.get("og:image"), host)
        title = (meta.get("og:title") or "").removesuffix(" OC ReMix")
        item["title"] = title or item["title"]
        item["author"] = extract(r"<h2>\s*By\s+(.*?)</h2>", html).replace(" ,", ",") or UNKNOWN
        item["keywords"] = " ".join(re.findall(r'href="/tag/([^"/?#]+)"', html))


def image_available(url):
    if not url:
        return False
    with request(url, {"Range": "bytes=0-4095"}) as response:
        return response.headers.get_content_type() in IMAGE_TYPES and bool(response.read(32))


def keyword_score(value, keywords):
    return sum(weight for key, weight in keywords.items()
               if re.search(r"(?<!\w)" + re.escape(key.casefold()) + r"(?!\w)", value))


def score(item, config, day):
    keywords = config["music_keywords" if item["kind"] == "music" else "visual_keywords"]
    value = f"{item['title']} {item['keywords']}".casefold().replace("_", " ")
    age = (day - item["published"]).days if item.get("published") else 365
    recent = max(0, 3 - max(0, age) / 60)
    return (config["weights"][item["source"]] + keyword_score(value, keywords)
            + recent + max(0, 2 - item["rank"] / 10) + 100 * item.get("opening", False))


def sort_items(items, config, day):
    return sorted(items, key=lambda item: (-score(item, config, day), item["id"]))


def select(items, config, day, seen, music=False):
    target = config["music_target" if music else "visual_target"]
    shortlist = target + 3 if music else target
    counts = Counter()
    authors = Counter()
    results = []
    checked = set()
    attempts = 0
    for item in sort_items(items, config, day):
        if len(results) >= shortlist or attempts >= (12 if music else 25):
            break
        key = canonical(item["url"])
        kind = item["kind"]
        if item["id"] in seen or key in seen or key in checked:
            continue
        if counts[kind] >= config["max_per_kind"].get(kind, shortlist):
            continue
        if any(term.casefold() in f"{item['title']} {item['keywords']}".casefold()
               for term in config["exclude_keywords"]):
            continue
        checked.add(key)
        attempts += 1
        try:
            load_details(item)
            author = item["author"].casefold()
            if author != UNKNOWN and authors[author] >= config["max_per_author"]:
                continue
            if not image_available(item.get("image")):
                raise ValueError("image preview unavailable")
        except (OSError, ValueError) as exc:
            warn(f"{item['url']}: {exc}")
            continue
        counts[kind] += 1
        authors[author] += 1
        results.append(item)
    return sort_items(results, config, day)[:target]


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path, data):
    encoded = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    if path.exists() and path.read_text(encoding="utf-8") == encoded:
        return
    pending = path.with_suffix(".tmp")
    pending.write_text(encoded, encoding="utf-8")
    pending.replace(path)


def history(directory):
    issues = {}
    seen = set()
    for path in sorted((directory / "archive").glob("*.json"), reverse=True):
        data = read_json(path)
        if data["date"] != path.stem or date.fromisoformat(data["date"]).isoformat() != path.stem:
            raise ValueError(f"invalid archive date: {path.name}")
        if not data.get("demo"):
            for item in data["items"]:
                seen.update([item["id"], canonical(item["url"])])
        issues[path.stem] = data
    return issues, seen


def print_issue(issue):
    for item in issue["items"]:
        print(f"{item['kind']:>5}  {item['title']} | {item['author']} | {item['url']}")


def run(config, directory, day):
    stamp = day.isoformat()
    archive = directory / "archive"
    issues, seen = history(directory)
    if stamp in issues and not issues[stamp].get("demo"):
        write_json(directory / "index.json", {"dates": list(issues)})
        print(f"{stamp} already collected. Existing issue preserved.")
        return
    if issues and next(iter(issues)) > stamp:
        raise ValueError("date is older than the latest archived issue")

    visual = [*itch_candidates(config, day, not issues), *museum_candidates(config, day, not issues)]
    art = select(visual, config, day, seen)
    music = select(music_candidates(day), config, day, seen, music=True)
    if not art and not music:
        raise ValueError("no new verified works; previous data preserved")
    if len(art) < config["visual_target"] or len(music) < config["music_target"]:
        warn(f"Verified {len(art)} visual works and {len(music)} tracks; publishing available works.")
    cover = next((item for item in art if item.get("opening")), None)
    if not cover:
        cover = next((item for item in art if (item.get("width") or 0) >= 1.25 * (item.get("height") or 1)), None)
    cover = cover or next(iter(art), None)
    public = {"id", "kind", "source", "url", "title", "author", "image", "full", "width", "height", "license"}
    issue = {
        "date": stamp,
        "cover": cover["id"] if cover else None,
        "items": [{key: value for key, value in item.items() if key in public and value}
                  for item in art + music],
    }
    archive.mkdir(parents=True, exist_ok=True)
    write_json(archive / f"{stamp}.json", issue)
    write_json(directory / "index.json", {"dates": sorted(issues.keys() | {stamp}, reverse=True)})
    print_issue(issue)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--date", type=date.fromisoformat, default=datetime.now(CHINA).date())
    args = parser.parse_args()
    try:
        run(read_json(ROOT / "scripts" / "preferences.json"), args.data_dir, args.date)
    except (OSError, ValueError, KeyError) as exc:
        warn(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
