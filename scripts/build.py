"""Build crawlable event pages, their sitemap and a no-JavaScript directory."""
import hashlib
import json
import shutil
import tempfile
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

PROJECT = Path(__file__).resolve().parents[1]
SOURCE = PROJECT / 'public'
ROOT = Path(tempfile.mkdtemp(prefix='notts-build-',dir=PROJECT))
for name in ('CNAME','app.js','assets','index.html','robots.txt','style.css'):
    path = SOURCE / name
    if path.is_dir():
        shutil.copytree(path, ROOT / name)
    else:
        shutil.copy2(path, ROOT / name)
BASE = 'https://whatsonnotts.com/'
data = json.loads((SOURCE / 'data.json').read_text())
groups = {o['id']: o for o in data['organisers']}
today = datetime.now(ZoneInfo("Europe/London")).date()
for notice in json.loads((PROJECT / 'sources/announcements.json').read_text()):
    if notice['date'] >= today.isoformat() and notice['organiser'] in groups:
        data['events'].append(notice)
for avatar in (ROOT / 'assets/groups').glob('*.png'):
    organiser = groups.get(avatar.stem)
    if organiser:
        organiser['logo'] = str(avatar.relative_to(ROOT))

# Real logos only: University-run organisers get the UoN crest, the SU gets its
# own logo, and SU groups that have not uploaded a logo fall back to the SU's.
UON_LOGO = 'assets/logos/uon-crest.svg'
SU_LOGO = 'assets/logos/uonsu.png'
UNIVERSITY_SOURCES = {'careers', 'living', 'university', 'computerscience', 'psychology'}
for organiser in groups.values():
    if organiser['source'] in UNIVERSITY_SOURCES:
        organiser['logo'] = UON_LOGO
    elif organiser['id'] == 'su' or (organiser['source'] == 'union' and not organiser.get('logo')):
        organiser['logo'] = SU_LOGO

def booking_slot(event):
    return (event['organiser'], event['title'].casefold(), event['date'], event['time'])


def saved_key(event):
    return '|'.join(event[k] for k in ('organiser', 'url', 'date', 'time'))


# SU booking links take precedence when both organisers list the same activity.
su_slots = {booking_slot(e): e for e in data['events'] if e['source'] == 'union'}
published = []
collaborators = {'orientalsoc': 'su-555', 'travelsoc': 'su-230'}
for e in data['events']:
    if e['source'] == 'living':
        cohost = next((oid for name, oid in collaborators.items()
                       if name in e['title'].casefold() and oid in groups), None)
        if not cohost:
            continue
        e['aliases'] = [saved_key(e)]
        e['organiser'] = cohost
    if e['source'] == 'arts':
        continue
    preferred = su_slots.get(booking_slot(e))
    if preferred and e['source'] in {'hacksoc', 'newtheatre', 'robotics', 'living', 'announcement', 'collective'}:
        preferred.setdefault('aliases', []).extend([saved_key(e), *e.get('aliases', [])])
        continue
    e.pop('price', None)
    published.append(e)
published.sort(key=lambda e: (e['date'], e['time'], e['title']))
data['events'] = published
# Keep the raw registry complete so a returning group is rediscovered. Use
# dated activity for the public directory, including co-hosts and non-SU feeds.
upcoming = {oid for e in published if (e.get('endDate') or e['date']) >= today.isoformat()
            for oid in [e['organiser'], *e.get('cohosts', [])]}
cutoff = (today - timedelta(days=180)).isoformat()
for o in groups.values():
    o.pop('profileEvents', None)
    o['active'] = (not o['id'].startswith('su-') or o['id'] in upcoming
                   or o.get('lastEvent', '') >= cutoff)

(ROOT / 'data.json').write_text(json.dumps(data,ensure_ascii=False,separators=(',',':')))
items = []
pages = ROOT / 'event'
pages.mkdir(exist_ok=True)
for e in data['events']:
    if urlsplit(e['url']).scheme not in ('https', 'http'):
        continue
    key = '\n'.join(e[k] for k in ('organiser','url','date','time'))
    slug = hashlib.sha256(key.encode()).hexdigest()[:20]
    path = 'event/' + slug + '.html'
    canonical = BASE + path
    title, date, time, venue = (escape(e[k]) for k in ('title','date','time','venue'))
    if e.get('endTime'):
        time += '–' + escape(e['endTime'])
    organiser = escape(groups[e['organiser']]['name'])
    source = escape(e['url'], quote=True)
    action = 'Society website ↗' if e['source'] == 'announcement' else 'Event details &amp; booking ↗'
    tags = ' · '.join(escape(t) for t in e['tags'])
    description = f'{organiser} · {date} {time} · {venue}'
    (ROOT / path).write_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} · What’s On Notts</title><meta name="description" content="{description}"><link rel="canonical" href="{canonical}"><link rel="stylesheet" href="../style.css"><link rel="icon" href="../assets/profile.png"></head><body><main class="detail"><a class="brand" href="../"><img src="../assets/flag.svg" alt="">What’s On Notts</a><p class="time">{date} {time}</p><h1>{title}</h1><p>{organiser}</p><p>{venue}</p><p class="meta">{tags}</p><a class="book" href="{source}">{action}</a></main></body></html>''')
    items.append((path, f'{date} · {title}'))
(ROOT / 'events.html').write_text('<!doctype html><html lang="en-GB"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><title>Event directory · What’s On Notts</title><main class="detail"><a href="./">← Campus events</a><h1>Event directory</h1><ul class="directory-list">'+''.join(f'<li><a href="{p}">{t}</a></li>' for p,t in items)+'</ul></main></html>')
(ROOT / 'sitemap.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{BASE}{p}</loc></url>' for p in ['', 'events.html']+[p for p,_ in items])+'</urlset>')

output = PROJECT / 'dist'
if output.exists():
    shutil.rmtree(output)
ROOT.rename(output)
