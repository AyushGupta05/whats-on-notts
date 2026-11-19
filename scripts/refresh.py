"""Refresh public organiser listings and event occurrences atomically."""

import html
import json
import os
import re
import tempfile
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlencode, unquote, quote
from zoneinfo import ZoneInfo

import requests
import icalendar
import recurring_ical_events
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


def profile_info(o, now):
    soup = page(o["url"])
    instagram = ""
    urls = set()
    for a in soup.select("a[href]"):
        href = a["href"].strip()
        match = re.fullmatch(
            r"https?://(?:www\.)?instagram\.com/([a-z0-9._]+)/?(?:\?[^#]*)?",
            href, re.IGNORECASE,
        )
        if not instagram and match and match[1].lower() not in {
            "uonsu", "p", "stories", "explore", "reel", "reels",
        }:
            instagram = "https://www.instagram.com/" + match[1] + "/"
        parts = urlparse(href)
        if (parts.scheme == "https" and parts.netloc in {"luma.com", "lu.ma"}
                and re.fullmatch(r"/[a-zA-Z0-9_-]+/?", parts.path)):
            urls.add("https://luma.com" + parts.path.rstrip("/"))

    cached = {e["url"]: e for e in o.get("profileEvents", [])}
    found = []
    for url in sorted(urls):
        try:
            listing = BeautifulSoup(get(url, allow_redirects=False).content, "html.parser")
            for script in listing.select('script[type="application/ld+json"]'):
                record = json.loads(script.get_text())
                if not isinstance(record, dict) or record.get("@type") != "Event":
                    continue
                if str(record.get("eventStatus", "")).endswith("EventCancelled"):
                    continue
                day, time = split_date(record["startDate"])
                last, until = split_date(record.get("endDate") or record["startDate"])
                if last >= now.date().isoformat():
                    venue = record.get("location") or {}
                    found.append(event(record["name"], day, time,
                                       venue.get("name") if isinstance(venue, dict) else "",
                                       UNKNOWN, o["id"], url, [o["category"]],
                                       endDate=last, endTime=until if last==day and record.get("endDate") else ""))
        except (requests.RequestException, ValueError, TypeError, KeyError):
            if url in cached:
                found.append(cached[url])
    return instagram, found


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
        is_sport = parent.get("name") == "Sports Clubs" or cat.get("name") in {
            "Sports (SB)",
            "Sports (Med Soc)",
        }
        branch = "Sports" if is_sport else "Societies"
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
    # The upcoming-only endpoint omits societies between events. Read the public
    # archive every three days and retain the latest dated evidence per group.
    history_checked = previous.get("su", {}).get("historyChecked", "")
    for oid, owner in orgs.items():
        for field in ("lastEvent", "lastEventUrl"):
            if field in previous.get(oid, {}):
                owner[field] = previous[oid][field]
    if history_checked <= (now.date() - timedelta(days=3)).isoformat():
        try:
            for entry in paginate("events", sortBy="start_date", onlyFuture=0):
                group = entry.get("group")
                if not group or entry.get("unlisted"):
                    continue
                owner = orgs.get(f"su-{group['id']}")
                day = split_date(entry["start_date"])[0]
                if owner and day <= now.date().isoformat() and day > owner.get("lastEvent", ""):
                    owner["lastEvent"] = day
                    owner["lastEventUrl"] = f"https://su.nottingham.ac.uk/events/id/{entry['event_id']}-{entry['url_name']}"
            history_checked = now.date().isoformat()
        except (requests.RequestException, KeyError, ValueError, TypeError) as exc:
            print(f"::warning::SU event archive unavailable: {exc}", flush=True)
    union_org["historyChecked"] = history_checked
    # Recheck every registered group, even those without upcoming events. Never request Instagram itself.
    stale = []
    for oid, o in orgs.items():
        if oid == "su":
            continue
        old = previous.get(oid, {})
        o["instagram"] = old.get("instagram", "")
        checked = old.get("profileChecked", "")
        o["profileEvents"] = old.get("profileEvents", [])
        if "profileEvents" in old and checked and checked > (now.date() - timedelta(days=3)).isoformat():
            o["profileChecked"] = checked
        else:
            stale.append(o)

    def enrich(o):
        try:
            o["instagram"], o["profileEvents"] = profile_info(o, now)
            o["profileChecked"] = now.date().isoformat()
        except requests.RequestException:
            pass

    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(enrich, stale))
    for owner in orgs.values():
        events.extend(owner.get("profileEvents", []))
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
        return [
            card
            for card in document.select("article")
            if card.select_one(":scope figure a[href*='/event/']")
        ]

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


def hacksoc(previous, now):
    events = []
    for row in get(SOURCES["hacksoc"]).json()["data"]:
        try:
            starts = date.fromisoformat(row["date"])
        except (ValueError, TypeError):
            continue  # The archive contains undated historical entries.
        if starts < now.date():
            continue
        url = urljoin(SOURCES["hacksoc"], urlparse(row["permalink"]).path)
        origin = urlparse(SOURCES["hacksoc"])
        resolved = urlparse(url)
        if (resolved.scheme, resolved.netloc) != (origin.scheme, origin.netloc):
            continue
        time = row.get("time")
        events.append(
            event(
                row["title"],
                starts.isoformat(),
                time.strip() if isinstance(time, str) else "",
                row.get("location"),
                UNKNOWN,
                "su-213",
                url,
                ["Technology", "School of Computer Science"],
            )
        )
    return [], events


def newtheatre(previous, now):
    base = SOURCES["newtheatre"]
    listing = page(base)
    if not listing.find("h1") or "what" not in text(listing.find("h1")).lower():
        raise ValueError("Unrecognised theatre listings")
    links = sorted(
        {
            urljoin(base, a["href"].split("#")[0])
            for a in listing.select('a[href^="/whats-on/"]')
        }
    )
    events = []
    for url in links:
        show = page(url)
        title = text(show.find("h1"))
        performances = show.select("li time[datetime]")
        if not title or not performances:
            raise ValueError(f"No performance details for {url}")
        for t in performances:
            row = t.find_parent("li")
            date, time = split_date(t["datetime"].replace("Z", "+00:00"))
            details = text(t.find_parent("p").find_next_sibling("p")).split(" · ")
            venue = details[1] if len(details) > 1 else ""
            price = re.search(r"(?:from )?£[\d,.]+|\bFree\b", text(row), re.I)
            events.append(
                event(
                    title,
                    date,
                    time,
                    venue,
                    price[0] if price else UNKNOWN,
                    "su-42",
                    url,
                    ["Theatre", "Arts & culture"],
                )
            )
    return [], events


def robotics(previous, now):
    url = SOURCES["robotics"]
    calendar_id = unquote(url.split("/ical/")[1].split("/")[0])
    cal = icalendar.Calendar.from_ical(get(url).content)
    start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    events = []
    for item in recurring_ical_events.of(cal).between(
        start, start + timedelta(days=365)
    ):
        if str(item.get("STATUS", "")).upper() == "CANCELLED":
            continue
        begins = item.decoded("DTSTART")
        if isinstance(begins, datetime):
            date, time = split_date(begins.isoformat())
        else:
            date, time = begins.isoformat(), ""
        end_date = date
        if "DTEND" in item:
            ends = item.decoded("DTEND")
            if isinstance(ends, datetime):
                end_date = split_date((ends - timedelta(microseconds=1)).isoformat())[0]
            else:
                end_date = (ends - timedelta(days=1)).isoformat()
            end_date = max(date, end_date)
        stamp = datetime.fromisoformat(date)
        dates = (
            stamp.strftime("%Y%m%d")
            + "/"
            + (stamp + timedelta(days=1)).strftime("%Y%m%d")
        )
        href = "https://calendar.google.com/calendar/embed?" + urlencode(
            {
                "src": calendar_id,
                "ctz": "Europe/London",
                "mode": "AGENDA",
                "dates": dates,
            }
        )
        # Google’s public agenda opens on the occurrence date. The iCalendar
        # UID identifies simultaneous events even for anonymous visitors.
        href += "#" + quote(str(item["UID"]), safe="")
        title = str(item["SUMMARY"])
        tags = ["Sport"] if "volleyball" in title.lower() else ["Technology"]
        events.append(
            event(
                title,
                date,
                time,
                str(item.get("LOCATION", "")),
                UNKNOWN,
                "su-711",
                href,
                tags,
                endDate=end_date,
            )
        )
    return [], events


def collective(previous, now):
    calendar = icalendar.Calendar.from_ical(get(SOURCES["collective"]).content)
    host = org("collective", "OpenAI Student Collective at University of Nottingham",
               "https://luma.com/openai-collective-university-of-nottingham", "University", "Technology")
    events = []
    for item in calendar.walk("VEVENT"):
        if str(item.get("STATUS", "")).upper() == "CANCELLED":
            continue
        starts = item.decoded("DTSTART")
        ends = item.decoded("DTEND") if "DTEND" in item else starts
        if isinstance(starts, datetime):
            day, time = split_date(starts.isoformat())
        else:
            day, time = starts.isoformat(), ""
        last = max(date.fromisoformat(day), date.fromisoformat(split_date((ends - timedelta(microseconds=1)).isoformat())[0])
                   if isinstance(ends, datetime) else ends - timedelta(days=1))
        if last < now.date():
            continue
        match = re.search(r"https://(?:luma\.com|lu\.ma)/[a-zA-Z0-9_-]+", str(item.get("DESCRIPTION", "")))
        if not match:
            continue
        url = match[0]
        title = str(item["SUMMARY"])
        owner, cohosts, tags = "collective", [], ["Technology"]
        venue = str(item.get("LOCATION", ""))
        if venue.startswith("https://"):
            venue = ""
        if url.endswith("/diuir9bw"):
            owner, cohosts, tags = "su-241", ["su-682", "collective"], ["Careers", "Workshop"]
            if "Sir Clive Granger Building" in venue:
                venue = "A41, Sir Clive Granger Building"
        events.append(event(title, day, time, venue, UNKNOWN, owner, url, tags,
                            endDate=last.isoformat(), cohosts=cohosts,
                            endTime=ends.astimezone(UK).strftime("%H:%M") if "DTEND" in item and isinstance(ends, datetime) and day == last.isoformat() else ""))
    return [host], events


SOCIETY_FALLBACKS = {
    "su-241": ("African-Caribbean Society", "african-caribbean", "International and Cultural"),
    "su-682": ("Advancing Black Careers Society", "abc", "Identity/Infinity"),
    "su-213": ("HackSoc", "hacksoc", "Hobbies and Interest"),
    "su-42": ("New Theatre", "new-theatre", "Student-Run Services"),
    "su-711": (
        "Robotics Society",
        "robotics_society",
        "Professional Skills",
    ),
}


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
        "collective": collective,
        "living": living,
        "hacksoc": hacksoc,
        "newtheatre": newtheatre,
        "robotics": robotics,
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
                all_events[(source, e["url"], e["date"], e["time"])] = dict(
                    e, source=source
                )
        print(
            f"{source}: {len(orgs)} organisers, {len(events)} source occurrences",
            flush=True,
        )
    if len(failed) == len(statuses):
        raise RuntimeError("Every source failed; keeping the previous snapshot")
    if not all_events:
        raise RuntimeError("Empty catalogue")
    # Extra calendars share their SU organiser. Keep links valid on a cold
    # start when a calendar succeeds but the SU directory is unavailable.
    for oid, (name, slug, category) in SOCIETY_FALLBACKS.items():
        if oid not in all_orgs and any(
            e["organiser"] == oid or oid in e.get("cohosts", []) for e in all_events.values()
        ):
            all_orgs[oid] = previous.get(oid) or dict(
                org(
                    oid,
                    name,
                    urljoin(SOURCES["groups"], "/activities/view/" + slug),
                    "Societies",
                    category,
                ),
                source="union",
            )
    # Preserve completed listings after they roll off the upcoming feeds.
    for oid, group in all_orgs.items():
        for field in ("lastActivity", "lastActivityUrl"):
            if field in previous.get(oid, {}):
                group[field] = previous[oid][field]
    for e in old.get("events", []):
        if e["date"] > now.date().isoformat():
            continue
        for oid in [e["organiser"], *e.get("cohosts", [])]:
            group = all_orgs.get(oid)
            if group and e["date"] > group.get("lastActivity", ""):
                group.update(lastActivity=e["date"], lastActivityUrl=e["url"])
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
