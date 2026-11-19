"""Refresh public organiser listings and event occurrences atomically."""

import html
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse
from zoneinfo import ZoneInfo

import requests
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "public/data.json"
SOURCES = json.loads((ROOT / "sources/registry.json").read_text())
UK = ZoneInfo("Europe/London")
UNKNOWN = "Price unlisted"
UNI_ICON = "https://campuslife-browzer-platform.s3.eu-west-2.amazonaws.com/images/829bdf01134da741031e7bd4a2dcc546"


def get(url, **kwargs):
    response = requests.get(url, timeout=(8, 25), **kwargs)
    response.raise_for_status()
    return response


def page(url, **kwargs):
    return BeautifulSoup(get(url, **kwargs).content, "html.parser")


def clean(text):
    return " ".join(html.unescape(str(text or "")).split())


def text(node):
    return clean(node.get_text(" ", strip=True)) if node else ""


def org(id, name, url, group, category, logo="", instagram=""):
    return {
        "id": id,
        "name": name,
        "url": url,
        "group": group,
        "category": category,
        "logo": logo or "",
        "instagram": instagram,
    }


def event(title, date, time, venue, price, organiser, url, tags, **extra):
    return dict(
        title=clean(title),
        date=date,
        time=time,
        venue=clean(venue),
        price=clean(price) or UNKNOWN,
        organiser=organiser,
        url=url,
        tags=sorted(set(filter(None, tags))),
        **extra,
    )


def split_date(value):
    stamp = datetime.fromisoformat(value)
    if stamp.tzinfo:
        stamp = stamp.astimezone(UK)
    return stamp.date().isoformat(), stamp.strftime("%H:%M")


def profile_info(o):
    soup = page(o["url"])
    for a in soup.select("a[href]"):
        match = re.fullmatch(
            r"https?://(?:www\.)?instagram\.com/([a-z0-9._]+)/?(?:\?[^#]*)?",
            a["href"],
            re.IGNORECASE,
        )
        if match and match[1].lower() not in {
            "uonsu",
            "p",
            "stories",
            "explore",
            "reel",
            "reels",
        }:
            return "https://www.instagram.com/" + match[1] + "/"
    return ""


def union(previous, now):
    site = re.search(r"var siteId\s*=\s*'([^']+)'", get(SOURCES["union"]).text)
    if not site:
        raise ValueError("SU public site ID unavailable")
    base = "https://pluto.sums.digital/api/"
    headers = {"X-Site-Id": site[1]}

    def api(path, params):
        return get(base + path, params=params, headers=headers).json()

    def paginate(path, **params):
        for number in range(1, 101):
            result = api(path, dict(params, page=number, perPage=100))
            yield from result["data"]
            if not result["next_page_url"]:
                return
        raise ValueError(f"Unexpected {path} pagination")

    categories = {
        c["id"]: c
        for kind in (0, 1)
        for c in api("groups/categories", {"isParent": kind})
    }
    union_org = org(
        "su",
        "UoN Students’ Union",
        SOURCES["union"],
        "University",
        "Students’ Union",
        "https://assets-cdn.sums.digital/NT/web_dev/favs/apple-touch-icon.png",
        "https://www.instagram.com/uonsu/",
    )
    orgs = {union_org["id"]: union_org}
    for g in paginate("groups", sortBy="name"):
        cat = categories.get(g["activity_category_id"], {})
        parent = categories.get(cat.get("parent_id"), cat)
        branch = "Sports" if "sport" in cat.get("name", "").lower() else "Societies"
        o = org(
            f"su-{g['id']}",
            clean(g["name"]),
            urljoin(SOURCES["groups"], "/activities/view/" + g["url_name"]),
            branch,
            clean(cat.get("name") or parent.get("name") or "Student groups"),
            g.get("thumbnail_url"),
        )
        orgs[o["id"]] = o
    if len(orgs) <= 1:
        raise ValueError("Empty SU directory")
    events = []
    for e in paginate("events", sortBy="start_date", onlyFuture=1):
        if e.get("unlisted"):
            continue
        group = e.get("group")
        oid = f"su-{group['id']}" if group else "su"
        if oid not in orgs:
            orgs[oid] = org(
                oid,
                group["name"],
                SOURCES["groups"],
                "Societies",
                "Student groups",
                group.get("thumbnail_url"),
            )
        price = e.get("from_price")
        if price is not None:
            amount = float(price)
            money = f"{amount:.2f}" if amount % 1 else str(int(amount))
            price = "Free" if amount == 0 else f"From £{money}"
        link = f"https://su.nottingham.ac.uk/events/id/{e['event_id']}-{e['url_name']}"
        tags = [orgs[oid]["category"]] + [
            clean(c.get("name")) for c in e.get("categories", [])
        ]
        if re.search(
            r"robot|techsoc|compsoc|comput|coding|cyber|hack|artificial intelligence|engineer",
            orgs[oid]["name"],
            re.IGNORECASE,
        ):
            tags.append("Technology")
        events.append(
            event(
                e["title"],
                *split_date(e["start_date"]),
                (e.get("venue") or {}).get("name"),
                price,
                oid,
                link,
                tags,
                endDate=split_date(e["end_date"])[0] if e.get("end_date") else "",
            )
        )
    # Cache each public profile for a month. Never request Instagram itself.
    stale = []
    for oid, o in orgs.items():
        if oid == "su":
            continue
        old = previous.get(oid, {})
        o["instagram"] = old.get("instagram", "")
        checked = old.get("profileChecked", "")
        if checked and checked >= (now.date() - timedelta(days=30)).isoformat():
            o["profileChecked"] = checked
        else:
            stale.append(o)

    def enrich(o):
        try:
            o["instagram"] = profile_info(o)
            o["profileChecked"] = now.date().isoformat()
        except requests.RequestException:
            pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(enrich, stale))
    return list(orgs.values()), events


def living(previous, now):
    base = SOURCES["living"]
    o = org(
        "resx",
        "Student Living · ResX",
        base,
        "University",
        "Student living",
        UNI_ICON,
        "https://www.instagram.com/uonresx/",
    )

    def details(card):
        a = card.select_one(":scope figure a[href]")
        d = text(card.select_one("figcaption p"))
        dt = datetime.strptime(
            re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", d), "%d %b %Y | %I:%M%p"
        )
        soup = page(a["href"])

        def field(label):
            tag = soup.find("p", string=lambda s: s and s.strip() == label)
            return text(tag.find_next_sibling("p")) if tag else ""

        finish = card.select("figcaption p")
        end = ""
        if len(finish) > 1:
            end = (
                datetime.strptime(
                    re.sub(r"(\d)(st|nd|rd|th)\b", r"\1", text(finish[-1])),
                    "%d %b %Y | %I:%M%p",
                )
                .date()
                .isoformat()
            )
        price = field("Price")
        return event(
            text(a),
            dt.date().isoformat(),
            dt.strftime("%H:%M"),
            field("Location"),
            "Free" if price.lower() == "free" else price,
            o["id"],
            a["href"],
            ["Student living"],
            endDate=end,
        )

    records = []
    first = page(base)
    total = re.search(r"Showing [\d,]+ to [\d,]+ of ([\d,]+) results", text(first))
    if not total:
        raise ValueError("Student Living pagination unavailable")
    count = int(total[1].replace(",", ""))
    def event_cards(document):
        return [card for card in document.select("article") if card.select_one(":scope figure a[href*='/event/']")]

    first_cards = event_cards(first)
    step = len(first_cards)
    for start in range(0, count, step):
        cards = (
            first_cards
            if not start
            else event_cards(page(base, params={"page": start // step + 1}))
        )
        with ThreadPoolExecutor(max_workers=3) as pool:
            records.extend(pool.map(details, cards))
    return [o], records


def lakeside(previous, now):
    feed = get(SOURCES["arts"]).json()
    o = org(
        "lakeside",
        "Lakeside Arts",
        "https://www.lakesidearts.org.uk/whats-on/",
        "University",
        "Arts",
        "https://www.lakesidearts.org.uk/wp-content/themes/cog-press-theme/static/favicons/apple-touch-icon.png",
        "https://www.instagram.com/lakesidearts/",
    )

    def listed_price(c):
        if c.get("is_free"):
            return "Free"
        offer = next(
            (clean(t["name"]) for t in c.get("offer_terms", []) if "£" in t["name"]), ""
        )
        if offer:
            return offer
        if urlparse(c["url"]).hostname != "www.lakesidearts.org.uk":
            return UNKNOWN
        try:
            amount = text(page(c["url"]).select_one("main .event-info-row-1 .price p"))
        except requests.RequestException:
            return UNKNOWN
        return amount if len(amount) < 90 else UNKNOWN

    cards = [
        c
        for c in feed["cards"]
        if not c.get("is_cancelled")
        and any(
            i["date"][:10] >= now.date().isoformat() for i in c.get("instances") or []
        )
    ]
    with ThreadPoolExecutor(max_workers=3) as pool:
        prices = dict(zip((c["url"] for c in cards), pool.map(listed_price, cards)))
    results = []
    for c in cards:
        if c.get("is_cancelled"):
            continue
        tags = [clean(term["name"]) for term in c.get("type_terms", [])]
        price = prices[c["url"]]
        for i in c.get("instances") or []:
            if i.get("availability") == "cancelled":
                continue
            day, at = split_date(i["date"])
            # Exhibition feeds carry a placeholder evening time. Link to opening hours.
            if c["post_type"] == "exhibition":
                at = ""
            results.append(
                event(
                    c["name"], day, at, c.get("venue"), price, o["id"], c["url"], tags
                )
            )
    return [o], results


def careers(previous, now):
    base = SOURCES["careers"]
    o = org(
        "careers",
        "Careers and Employability Service",
        base,
        "Careers",
        "Careers",
        UNI_ICON,
    )
    index = page(base)
    links = {
        urljoin(base, a["href"])
        for a in index.select("a[href^='/careers/students/events/']")
    } - {base}
    if not links:
        raise ValueError("No public careers categories found")
    result = []
    for url in sorted(links):
        s = page(url)
        for item in s.select("ul.sys_rss li:has(.ch-startdate)"):
            a = item.select_one("a[href]")
            value = text(item.select_one(".ch-startdate")).partition(":")[2].strip()
            day, _, at = value.partition(", ")
            stamp = datetime.strptime(day, "%d %b %Y")
            time = datetime.strptime(at, "%I:%M %p").strftime("%H:%M") if at else ""
            venue = text(item.select_one(".ch-venue")).removeprefix("Venue:").strip()
            result.append(
                event(
                    text(a),
                    stamp.date().isoformat(),
                    time,
                    venue,
                    UNKNOWN,
                    o["id"],
                    urljoin(url, a["href"]),
                    ["Careers"],
                )
            )
    return [o], result


def academic_dates(value):
    start, sep, end = value.partition(" - ")
    if sep:
        start_parts = start.split("/")
        start = "/".join(start_parts + end.split("/")[len(start_parts) :])

    def parse(day):
        return datetime.strptime(day, "%d/%m/%Y").date().isoformat()

    return parse(start), parse(end) if sep else ""


def university(previous, now, source="university"):
    base = SOURCES[source]
    name = {
        "university": "University of Nottingham",
        "computerscience": "School of Computer Science",
        "psychology": "School of Psychology",
    }[source]
    o = org(
        source,
        name,
        base,
        "University",
        "Academic",
        UNI_ICON,
        "https://www.instagram.com/uniofnottingham/" if source == "university" else "",
    )
    result = []
    url = base
    seen = set()
    while url:
        if url in seen:
            raise ValueError("University calendar pagination cycle")
        seen.add(url)
        s = page(url)
        for item in s.select(".sys_subitem"):
            a = item.select_one(":scope .sys_events-subheading a")
            if a is None:
                continue
            detail = urljoin(base, a["href"])
            date, end = academic_dates(
                text(item.select_one("dd.sys_events-time, dd.sys_events-date"))
            )
            at = ""
            if urlparse(detail).hostname == "www.nottingham.ac.uk":
                try:
                    published = page(detail).select_one(
                        ".sys_events-details dd.sys_events-date"
                    )
                    clock = re.search(
                        r"\((\d{1,2}:\d{2})(?:\s*[-–]|\))", text(published)
                    )
                    if clock:
                        at = datetime.strptime(clock[1], "%H:%M").strftime("%H:%M")
                except requests.RequestException:
                    pass
            tags = ["Academic"]
            for slug, label in {
                "economics": "Economics",
                "psychology": "Psychology",
                "computerscience": "Computer Science",
                "history": "History",
                "music": "Music",
                "english": "English",
                "classics-and-archaeology": "Classics and Archaeology",
                "commercial-law-centre": "Law",
            }.items():
                if slug in urlparse(detail).path.split("/"):
                    tags.append(label)
            result.append(
                event(
                    text(a),
                    date,
                    at,
                    text(item.select_one("dd.sys_events-location")),
                    UNKNOWN,
                    o["id"],
                    detail,
                    tags,
                    endDate=end,
                )
            )
        next_link = next(
            (
                a
                for a in s.select("a[href*='GoToPage']")
                if text(a) == "Next"
                and (source != "psychology" or "EventsListing" in a["href"])
            ),
            None,
        )
        url = urljoin(base, next_link["href"]) if next_link else ""
    return [o], result


def main():
    now = datetime.now(UK)
    old = json.loads(OUTPUT.read_text()) if OUTPUT.exists() else {}
    previous = {o["id"]: o for o in old.get("organisers", [])}
    all_orgs = {}
    all_events = {}
    statuses = {}
    failed = []
    for source, load in {
        "union": union,
        "living": living,
        "arts": lakeside,
        "careers": careers,
        "university": university,
        "computerscience": lambda p, n: university(p, n, "computerscience"),
        "psychology": lambda p, n: university(p, n, "psychology"),
    }.items():
        try:
            orgs, events = load(previous, now)
            statuses[source] = {
                "checked": now.isoformat(timespec="seconds"),
                "ok": True,
            }
        except (
            requests.RequestException,
            ValueError,
            KeyError,
            TypeError,
            AttributeError,
        ) as exc:
            print(f"{source}: {type(exc).__name__}: {exc}", flush=True)
            failed.append(source)
            orgs = [o for o in previous.values() if o.get("source") == source]
            events = [e for e in old.get("events", []) if e.get("source") == source]
            statuses[source] = {
                "checked": now.isoformat(timespec="seconds"),
                "ok": False,
                "lastSuccess": old.get("sources", {})
                .get(source, {})
                .get("lastSuccess", ""),
            }
        if statuses[source]["ok"]:
            statuses[source]["lastSuccess"] = statuses[source]["checked"]
        for o in orgs:
            all_orgs[o["id"]] = dict(o, source=source)
        for e in events:
            if max(e["date"], e.get("endDate", "")) >= now.date().isoformat():
                all_events[(e["url"], e["date"], e["time"])] = dict(e, source=source)
        print(
            f"{source}: {len(orgs)} organisers, {len(events)} source occurrences",
            flush=True,
        )
    if len(failed) == len(statuses):
        raise RuntimeError("Every source failed; keeping the previous snapshot")
    if not all_events:
        raise RuntimeError("Empty catalogue")
    output = {
        "updated": now.isoformat(timespec="seconds"),
        "organisers": list(all_orgs.values()),
        "events": sorted(
            all_events.values(), key=lambda e: (e["date"], e["time"], e["title"])
        ),
        "sources": statuses,
    }
    OUTPUT.parent.mkdir(exist_ok=True)
    with tempfile.NamedTemporaryFile(mode="w", dir=OUTPUT.parent, delete=False) as f:
        json.dump(output, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(f.name, OUTPUT)
    if failed:
        print(
            "::warning::Sources requiring attention: " + ", ".join(failed), flush=True
        )


if __name__ == "__main__":
    main()
