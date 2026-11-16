"""Publish a Beijing-date issue from verified art collections and music."""

import argparse
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from functools import lru_cache
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
from pathlib import Path
import re
import sys
from urllib.error import HTTPError
from urllib.parse import unquote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen
from urllib.robotparser import RobotFileParser
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parent.parent
CHINA = timezone(timedelta(hours=8))
MUSEUM_CDN = "openaccess-cdn.clevelandart.org"
OCR = "https://ocremix.org"
DAY_LIMIT = 4_000_000
UNKNOWN = "未知"
IMAGE_TYPES = {"image/jpeg", "image/png", "image/gif", "image/webp", "image/avif"}
USER_AGENT = "ARTIFACT/2.0 (https://github.com/CalciteCalcspar6486/artifact)"
WORK_KINDS = {
    "pixel illustration": "pixel", "pixel environment": "pixel",
    "game concept art": "game", "production concept art": "other",
    "digital illustration": "other", "museum artwork": "other", "music track": "music",
}
LICENSES = {
    "CC0": "https://creativecommons.org/publicdomain/zero/1.0/",
    "Public domain": "https://creativecommons.org/publicdomain/mark/1.0/",
    **{f"CC {term.upper()} {version}": f"https://creativecommons.org/licenses/{term}/{version}/"
       for term in ("by", "by-sa") for version in ("2.0", "2.5", "3.0", "4.0")},
}


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
        "User-Agent": USER_AGENT,
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
    return f"{host}{unquote(parts.path).rstrip('/')}"


def candidate(kind, source, url, title, keywords="", **extra):
    stable_id = sha256(canonical(url).encode()).hexdigest()[:20]
    return {
        "id": stable_id, "kind": kind, "source": source, "url": url,
        "title": title or UNKNOWN, "keywords": keywords, **extra,
    }


def source_error(errors, source, context, exc):
    errors.append({"source": source["name"], "context": context, "error": str(exc)})
    warn(f"{source['name']} / {context}: {exc}")


def museum_candidates(source, day, errors):
    topics = source["topics"]
    start = (day.toordinal() * 3) % len(topics)
    for position in range(min(3, len(topics))):
        topic = topics[(start + position) % len(topics)]
        params = {"q": topic["query"], "cc0": 1, "has_image": 1, "limit": 10}
        try:
            rows = json.loads(download(f"{source['endpoint']}?{urlencode(params)}"))["data"]
        except (OSError, ValueError, KeyError) as exc:
            source_error(errors, source, topic["query"], exc)
            continue
        for row in rows:
            url = safe_url(row.get("url"), "clevelandart.org", subdomains=True)
            if not url:
                continue
            images = row.get("images") or {}
            web = images.get("web") or {}
            creators = [person.get("description", "").split(" (", 1)[0]
                        for person in row.get("creators") or []]
            title = row.get("title") or ""
            evidence = " ".join([title, text(row.get("description")), text(row.get("technique"))])
            item = candidate("other", source["publisher"], url, title, evidence,
                             author=", ".join(filter(None, creators)) or UNKNOWN,
                             image=safe_url(web.get("url"), MUSEUM_CDN),
                             width=int(web.get("width") or 0), height=int(web.get("height") or 0),
                             license=row.get("share_license_status"), work_type="museum artwork",
                             theme=topic["theme"], discovery=topic["discovery"])
            subject = " ".join([title, text(row.get("technique"))])
            if row.get("type") not in topic["artwork_types"] or not matches(subject, topic["evidence"]):
                item["provider_rejection"] = "博物馆记录未通过专题类型或主题检查"
            yield item


def manual_candidates(source):
    for work in source["works"]:
        kind = WORK_KINDS.get(work["work_type"], "")
        details = {key: value for key, value in work.items() if key not in ("url", "title", "tags")}
        yield candidate(kind, source["publisher"], work["url"], work["title"], " ".join(work["tags"]), **details)


def collection_candidates(source, day, errors):
    try:
        if not robots_allowed(source["url"]):
            raise ValueError("robots.txt does not allow this collection")
        html = download(source["url"], check_redirect=lambda url: canonical(url) == canonical(source["url"]))
        page = html.decode("utf-8")
    except (OSError, ValueError) as exc:
        source_error(errors, source, "collection", exc)
        return
    host = "https://" + source["page_host"]
    if source["access"] == "oga_collection":
        entries = re.findall(r'class="art-preview-title">\s*<a href="(/content/[^"]+)">(.*?)</a>', page, re.S)
    else:
        filenames = re.findall(r'href="(/wiki/File:[^"]+)"', page)
        entries = [(path, unquote(path.split(":", 1)[1]).rsplit(".", 1)[0].replace("_", " "))
                   for path in filenames if re.fullmatch(source["file_path_pattern"], path)]
    entries = list(dict.fromkeys(entries))
    if not entries:
        source_error(errors, source, "collection", ValueError("no recognized work entries"))
        return
    start = day.toordinal() % len(entries)
    for path, title in (entries[start:] + entries[:start])[:18]:
        yield candidate(WORK_KINDS[source["work_type"]], source["publisher"], host + path, text(title),
                        work_type=source["work_type"], theme=source["theme"], discovery=source["discovery"])


def music_candidates(source, day, errors):
    try:
        rss = ET.fromstring(download(source["endpoint"]))
        for rank, entry in enumerate(rss.findall("./channel/item")):
            url = safe_url(entry.findtext("link"), "ocremix.org").rstrip("/")
            if re.fullmatch(r"https://ocremix\.org/remix/OCR\d+", url):
                yield candidate("music", source["publisher"], url, entry.findtext("title"), rank=rank,
                                published=published(entry.findtext("pubDate")), work_type="music track")
    except (OSError, ValueError, ET.ParseError) as exc:
        source_error(errors, source, "RSS", exc)

    # The RSS feed is short. Rotate through the public catalog for past releases.
    offset = 30 * (1 + day.toordinal() % 125)
    path = f"{OCR}/remixes/?offset={offset}&sort=datedesc"
    try:
        if not robots_allowed(path):
            raise ValueError("robots.txt does not allow this path")
        html = download(path).decode("utf-8", errors="replace")
        tracks = re.findall(r'href="(/remix/OCR\d+)"[^>]*class="main featured"[^>]*>(.*?)</a>', html, re.S)
        for rank, (link, title) in enumerate(tracks):
            yield candidate("music", source["publisher"], OCR + link, text(title), rank=rank + 12,
                            work_type="music track")
    except (OSError, ValueError) as exc:
        source_error(errors, source, "catalog", exc)


def gather(sources, day, errors):
    for source in sources:
        if not source["enabled"]:
            continue
        method = source["access"]
        if method == "reviewed_pages":
            items = manual_candidates(source)
        elif method in {"oga_collection", "commons_collection"}:
            items = collection_candidates(source, day, errors)
        elif method == "cleveland_api":
            items = museum_candidates(source, day, errors)
        elif method == "ocremix_rss":
            items = music_candidates(source, day, errors)
        else:
            raise ValueError(f"unknown source access: {method}")
        for item in items:
            item["collection"] = source
            yield item


@lru_cache(maxsize=10)
def robots(host):
    url = f"https://{host}/robots.txt"
    parser = RobotFileParser(url)
    try:
        body = download(url).decode("utf-8-sig")
        if body.lstrip().startswith("<"):
            raise ValueError("robots.txt is not text")
        parser.parse(body.splitlines())
    except HTTPError as exc:
        if exc.code == 404:
            parser.allow_all = True
        else:
            raise
    return parser


def robots_allowed(url):
    return robots(urlsplit(url).hostname).can_fetch("ARTIFACT", url)


def load_details(item):
    source = item["collection"]
    method = source["access"]
    host = source["page_host"]
    if not safe_url(item["url"], host, subdomains=method == "cleveland_api"):
        raise ValueError("work URL is outside the allowlisted host")
    if method != "cleveland_api" and not robots_allowed(item["url"]):
        raise ValueError("robots.txt does not allow this path")
    html = download(item["url"], check_redirect=lambda url: (
        bool(safe_url(url, host, subdomains=method == "cleveland_api"))
        and canonical(url) == canonical(item["url"])
    )).decode("utf-8", errors="replace")
    if method == "cleveland_api":
        return
    if method == "ocremix_rss":
        meta = Metadata(html).values
        if meta.get("og:type") != "music.song":
            raise ValueError("OC ReMix track unavailable")
        item["image"] = safe_url(meta.get("og:image"), host)
        title = (meta.get("og:title") or "").removesuffix(" OC ReMix")
        item["title"] = title or item["title"]
        item["author"] = extract(r"<h2>\s*By\s+(.*?)</h2>", html).replace(" ,", ",") or UNKNOWN
        item["keywords"] = " ".join(re.findall(r'href="/tag/([^"/?#]+)"', html))
        return

    # Exact images were reviewed individually. Verify that the work page still
    # contains the image, the credited creator and the stated license.
    normalized = unquote(unescape(html))
    image_path = unquote(urlsplit(item.get("image", "")).path)
    if host == "opengameart.org":
        title = Metadata(html).values.get("og:title")
        if not title or text(title) != item["title"]:
            raise ValueError("OpenGameArt work title changed")
        author = extract(r'field-name-author-submitter[^>]*>.*?<a [^>]*href="/users/[^"]+"[^>]*>(.*?)</a>', normalized)
        if not author or (item.get("author") and author.casefold() != item["author"].casefold()):
            raise ValueError("OpenGameArt author could not be confirmed")
        license_section = re.search(r'field-name-field-art-licenses[^>]*>(.*?)(?=field-name-field-art-preview)', normalized, re.S)
        image_section = re.search(r'field-name-field-art-preview[^>]*>(.*?)(?=field-name-)', unescape(html), re.S)
        license_page = license_section[1] if license_section else ""
        image_page = image_section[1] if image_section else ""
        if method == "oga_collection":
            tags = [unquote(tag).replace("+", " ") for tag in
                    re.findall(r'field_art_tags_tid=([^"&]+)', html)]
            if not (matches(" ".join(tags), ["pixel", "pixelart", "pixel art"])
                    and matches(item["title"], ["background", "backgrounds", "scene", "landscape", "environment", "parallax"])
                    and re.search(r'field-name-field-art-type[^>]*>.*?>2D Art</a>', html, re.S)):
                raise ValueError("未确认是独立的 2D 像素场景")
            images = re.findall(r'href="(https://opengameart\.org/sites/default/files/[^"]+)"', image_page)
            item["image"] = next((url for url in images if re.search(r'\.(png|gif|jpg|webp)$', url, re.I)), "")
            item["keywords"] = " ".join(tags)
            item["author"] = author
            valid_image = bool(item["image"])
        else:
            valid_image = image_path in unquote(image_page)
    else:
        author = extract(r'id="fileinfotpl_aut"[^>]*>.*?</td>\s*<td[^>]*>(.*?)</td>', normalized)
        license_page = " ".join(re.findall(r'<span[^>]*class="licensetpl_link"[^>]*>(.*?)</span>', normalized, re.S))
        image = re.search(r'class="fullImageLink"[^>]*>\s*<a href="([^"]+)', unescape(html))
        original = urlsplit(image[1]) if image else None
        if method == "commons_collection":
            category = urlsplit(source["url"]).path
            if f'href="{category}"' not in normalized or not matches(author, source["author_credits"]):
                raise ValueError("未确认作品属于制作档案且署名一致")
            item["author"] = author
            item["image"] = urlunsplit((original.scheme, original.netloc, original.path, "", "")) if original else ""
            valid_image = bool(item["image"])
        else:
            valid_image = bool(original and unquote(original.path) == image_path)
        if not author or (item.get("author") and item["author"].casefold() not in author.casefold()):
            raise ValueError("Commons author could not be confirmed")

    if method in {"oga_collection", "commons_collection"}:
        item["license"] = next((name for name, url in LICENSES.items()
                                if url.removeprefix("https:").rstrip("/") in license_page), "")
    license_url = LICENSES.get(item.get("license"))
    valid_license = license_url and license_url.removeprefix("https:").rstrip("/") in license_page
    if not valid_license or not valid_image:
        raise ValueError("reviewed image or license no longer present on the work page")


def image_available(url):
    if not url:
        return False
    with request(url, {"Range": "bytes=0-4095"}) as response:
        mime = response.headers.get_content_type()
        header = response.read(32)
        return bool(safe_url(response.url, urlsplit(url).hostname)) and mime in IMAGE_TYPES and (
            header.startswith((b"\xff\xd8\xff", b"\x89PNG\r\n\x1a\n", b"GIF87a", b"GIF89a"))
            or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
            or (header[4:8] == b"ftyp" and b"avif" in header[8:])
        )


def matching_text(value):
    return re.sub(r"[-_‐‑–]+", " ", value.casefold())


def matches(value, keywords):
    haystack = matching_text(value)
    return [key for key in keywords
            if re.search(r"(?<!\w)" + re.escape(matching_text(key)) + r"(?!\w)", haystack)]


def matched_terms(item, config):
    value = f"{item['title']} {item['keywords']}"
    return {group: terms for group, words in config["keyword_groups"].items()
            if (terms := matches(value, words))}


def precheck(item, config, details_checked=False):
    source = item.get("collection", {})
    if not source.get("enabled") or not source.get("verified"):
        return "来源不在已验证白名单"
    if item.get("provider_rejection"):
        return item["provider_rejection"]
    if WORK_KINDS.get(item.get("work_type")) != item["kind"] or not item["kind"]:
        return "未确认是独立艺术作品或音乐单曲"
    if item["title"] == UNKNOWN:
        return "缺少真实作品名"
    excluded = matches(f"{item['title']} {item['keywords']}", config["exclude_keywords"])
    if excluded:
        return "命中排除词：" + ", ".join(excluded)
    if item["kind"] != "music":
        if item.get("theme") not in config["visual_mix"] or item.get("discovery") not in config["discovery_mix"]:
            return "缺少策展分类"
        dynamic = source.get("access") in {"oga_collection", "commons_collection"}
        if item.get("license") not in LICENSES and (details_checked or not dynamic):
            return "无可验证的开放预览授权"
    return ""


def order_key(item, config, day):
    source = item.get("collection", {})
    hits = matched_terms(item, config)
    direct_group = "music" if item["kind"] == "music" else item.get("theme")
    relevant = min(3, len(hits.get(direct_group, []))) + (1 if "technique" in hits else 0)
    if item["kind"] == "music":
        recent = bool(item.get("published") and 0 <= (day - item["published"]).days <= 60)
        return (-relevant, -int(recent), item.get("rank", 99))
    repeatable_order = sha256(f"{day}:{item['id']}".encode()).hexdigest()
    return (-source.get("priority", 0), -relevant, repeatable_order)


def report_item(item, config, status, reason):
    source = item.get("collection", {})
    return {
        "title": item["title"], "author": item.get("author", UNKNOWN), "source": item["source"],
        "collection": source.get("name"), "source_type": source.get("type"), "url": item["url"],
        "image": item.get("image"), "license": item.get("license"), "kind": item["kind"],
        "work_type": item.get("work_type"), "theme": item.get("theme"), "discovery": item.get("discovery"),
        "allowlisted": bool(source.get("verified") and source.get("enabled")),
        "work_type_verified": item.get("type_verified", False),
        "matched_keywords": matched_terms(item, config), "status": status, "reason": reason,
    }


def select(items, config, day, seen, music=False, decisions=None):
    target = config["music_target" if music else "visual_target"]
    themes, discoveries, collections = Counter(), Counter(), Counter()
    authors = Counter()
    results = []
    used = set(seen)
    pool = list(items)
    rankings = {id(item): order_key(item, config, day) for item in pool}
    validated_music = []
    attempts = 0

    def record(item, status, reason):
        if decisions is not None:
            decisions.append(report_item(item, config, status, reason))

    def next_key(item):
        rank = rankings[id(item)]
        if music:
            return rank
        theme = item.get("theme")
        discovery = item.get("discovery")
        return (themes[theme] - config["visual_mix"].get(theme, 0) * (len(results) + 1),
                discoveries[discovery] - config["discovery_mix"].get(discovery, 0) * (len(results) + 1), *rank)

    while pool:
        item = min(pool, key=next_key)
        pool.remove(item)
        source = item.get("collection", {})
        key = canonical(item["url"])
        image_key = canonical(item["image"]) if item.get("image") else None
        reason = precheck(item, config)
        if not reason and (item["id"] in used or key in used or image_key in used):
            reason = "已在往期或本期出现（作品页或预览重复）"
        if reason:
            record(item, "rejected", reason)
            continue
        if len(results) >= target or (music and len(validated_music) >= target + 3):
            record(item, "deferred", "本期数量已足，留待后续")
            continue
        if attempts >= (14 if music else 28):
            record(item, "deferred", "本次在线核验预算已用完，留待后续")
            continue
        if collections[source["name"]] >= source.get("max_per_issue", target):
            record(item, "deferred", "本期该专题已达上限，留待后续")
            continue
        attempts += 1
        try:
            load_details(item)
            author = item.get("author", UNKNOWN).strip()
            if author.casefold() in {"", UNKNOWN, "unknown", "anonymous", "unidentified artist"}:
                raise ValueError("缺少可确认的作者")
            if not item.get("image") or not safe_url(item["image"], source["image_host"]):
                raise ValueError("预览不在已验证的域名")
            if not image_available(item["image"]):
                raise ValueError("预览图不可用")
            image_key = canonical(item["image"])
            if not music and image_key in used:
                raise ValueError("已在往期或本期出现（预览重复）")
            if reason := precheck(item, config, details_checked=True):
                raise ValueError(reason)
        except (OSError, ValueError) as exc:
            record(item, "rejected", str(exc))
            warn(f"{item['url']}: {exc}")
            continue
        item["type_verified"] = True
        if music:
            validated_music.append(item)
            used.update((item["id"], key))
            continue
        author_key = author.split(" / ", 1)[0].casefold()
        if authors[author_key] >= config["max_per_author"]:
            record(item, "deferred", "本期该作者已达上限，留待后续")
            continue
        item["license_url"] = LICENSES[item["license"]]
        themes[item["theme"]] += 1
        discoveries[item["discovery"]] += 1
        collections[source["name"]] += 1
        authors[author_key] += 1
        used.update((item["id"], key, image_key))
        results.append(item)
        record(item, "selected", "已确认策展范围、独立作品、作者、开放许可和预览")

    for item in sorted(validated_music, key=lambda entry: order_key(entry, config, day)):
        author = item["author"].casefold()
        if len(results) < target and authors[author] < config["max_per_author"]:
            results.append(item)
            authors[author] += 1
            record(item, "selected", "已确认原站曲目、作者和公开分享封面")
        else:
            record(item, "deferred", "本期曲目或同作者已达上限，留待后续")
    return results


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
                if item.get("kind") != "music" and item.get("image"):
                    seen.add(canonical(item["image"]))
        issues[path.stem] = data
    return issues, seen


def print_issue(issue):
    for item in issue["items"]:
        print(f"{item['kind']:>5}  {item['title']} | {item['author']} | {item['url']}")


def run(config, directory, day, diagnostic=False, sources=None):
    stamp = day.isoformat()
    archive = directory / "archive"
    issues, seen = history(directory)
    if not diagnostic and stamp in issues and not issues[stamp].get("demo"):
        write_json(directory / "index.json", {"dates": list(issues)})
        print(f"{stamp} already collected. Existing issue preserved.")
        return
    if not diagnostic and issues and next(iter(issues)) > stamp:
        raise ValueError("date is older than the latest archived issue")

    if sources is None:
        sources = read_json(ROOT / "scripts" / "curated_sources.json")["sources"]
    errors, decisions = [], [] if diagnostic else None
    candidates = list(gather(sources, day, errors))
    art = select((item for item in candidates if item["kind"] != "music"), config, day, seen, decisions=decisions)
    music = select((item for item in candidates if item["kind"] == "music"), config, day, seen,
                   music=True, decisions=decisions)
    enough_art = len(art) >= config["min_visual_to_publish"]
    if diagnostic:
        status = Counter(item["status"] for item in decisions)
        report = {
            "date": stamp, "dry_run": True, "would_publish_with_available_visuals": enough_art,
            "candidate_count": len(candidates), "selected_visual": len(art), "selected_music": len(music),
            "rejected": status["rejected"], "deferred": status["deferred"],
            "sources": {},
            "rejection_reasons": dict(Counter(item["reason"] for item in decisions if item["status"] == "rejected")),
            "source_errors": errors, "candidates": decisions,
        }
        for source in sources:
            if source["enabled"]:
                counts = Counter(item["status"] for item in decisions if item["collection"] == source["name"])
                report["sources"][source["name"]] = {"candidate_count": counts.total(), **counts}
        return report
    if not enough_art:
        warn("No new verified visual issue today; previous data preserved.")
        return
    if len(art) < config["visual_target"] or len(music) < config["music_target"]:
        warn(f"Verified {len(art)} visual works and {len(music)} tracks; publishing available works.")
    cover = next((item for item in art if (item.get("width") or 0) >= 1.25 * (item.get("height") or 1)), None)
    cover = cover or next(iter(art), None)
    public = {"id", "kind", "source", "url", "title", "author", "image", "full", "width", "height", "license", "license_url"}
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
    parser.add_argument("--diagnostic", action="store_true", help="print decision JSON without changing archived issues")
    parser.add_argument("--report", type=Path, help="save diagnostic JSON to this file (requires --diagnostic)")
    args = parser.parse_args()
    if args.report and not args.diagnostic:
        parser.error("--report requires --diagnostic")
    try:
        report = run(read_json(ROOT / "scripts" / "preferences.json"), args.data_dir, args.date, args.diagnostic)
        if args.diagnostic:
            if args.report:
                if args.report.resolve().is_relative_to(args.data_dir.resolve()):
                    parser.error("--report must be outside the archive directory")
                write_json(args.report, report)
            else:
                print(json.dumps(report, ensure_ascii=False, indent=2))
    except (OSError, ValueError, KeyError) as exc:
        warn(exc)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
