"""Build crawlable event pages, their sitemap and a no-JavaScript directory."""
import hashlib
import json
from html import escape
from pathlib import Path
from urllib.parse import urlsplit

ROOT = Path(__file__).resolve().parents[1] / 'public'
BASE = 'https://whatsonnotts.com/'
data = json.loads((ROOT / 'data.json').read_text())
groups = {o['id']: o for o in data['organisers']}
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
    title, date, time, venue, price = (escape(e[k]) for k in ('title','date','time','venue','price'))
    organiser = escape(groups[e['organiser']]['name'])
    source = escape(e['url'], quote=True)
    tags = ' · '.join(escape(t) for t in e['tags'])
    description = f'{organiser} · {date} {time} · {venue} · {price}'
    (ROOT / path).write_text(f'''<!doctype html><html lang="en-GB"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><title>{title} · What’s On Notts</title><meta name="description" content="{description}"><link rel="canonical" href="{canonical}"><link rel="stylesheet" href="../style.css"><link rel="icon" href="../assets/profile.png"></head><body><main class="detail"><a class="brand" href="../"><img src="../assets/flag.svg" alt="">What’s On Notts</a><p class="time">{date} {time}</p><h1>{title}</h1><p>{organiser}</p><p>{venue}</p><p>{price}</p><p class="meta">{tags}</p><a class="book" href="{source}">Event details &amp; booking ↗</a></main></body></html>''')
    items.append((path, f'{date} · {title}'))
(ROOT / 'events.html').write_text('<!doctype html><html lang="en-GB"><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1"><link rel="stylesheet" href="style.css"><title>Event directory · What’s On Notts</title><main class="detail"><a href="./">← Campus events</a><h1>Event directory</h1><ul class="directory-list">'+''.join(f'<li><a href="{p}">{t}</a></li>' for p,t in items)+'</ul></main></html>')
(ROOT / 'sitemap.xml').write_text('<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'+''.join(f'<url><loc>{BASE}{p}</loc></url>' for p in ['', 'events.html']+[p for p,_ in items])+'</urlset>')
