const get = (id) => document.getElementById(id);
const node = (tag, cls, text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text) element.textContent = text;
  return element;
};
const dayKey = (date) =>
  new Intl.DateTimeFormat("sv-SE", { timeZone: "Europe/London" }).format(date);
const asDate = (day) => new Date(day + "T12:00:00Z");
const after = (day, n) => {
  const d = asDate(day);
  d.setUTCDate(d.getUTCDate() + n);
  return dayKey(d);
};
const dateLabel = (day) =>
  asDate(day).toLocaleDateString("en-GB", {
    weekday: "long",
    day: "numeric",
    month: "long",
    year: "numeric",
    timeZone: "Europe/London",
  });
function safeURL(value) {
  try {
    const url = new URL(value);
    if (["http:", "https:"].includes(url.protocol)) return url.href;
  } catch {}
  return "";
}
function link(text, url) {
  const a = node("a", null, text);
  const href = safeURL(url);
  if (href) {
    a.href = href;
    a.target = "_blank";
    a.rel = "noopener noreferrer";
  }
  return a;
}
let groups = new Map(),
  events = [],
  view = "events",
  limit = 45,
  saved = new Set();
let records = [];
let storageWritable = true;
function options(id, label, items) {
  const el = get(id);
  el.replaceChildren(new Option(label, ""));
  for (const [value, text] of items) el.add(new Option(text, value));
}
const sorted = (values) =>
  [...new Set(values.filter(Boolean))].sort((a, b) => a.localeCompare(b));
function logo(org) {
  const box = node("div", "badge");
  box.setAttribute("aria-hidden", "true");
  box.append(
    node(
      "span",
      "",
      org.name
        .split(/\s+/)
        .filter((w) => w && !["of", "and", "the"].includes(w.toLowerCase()))
        .slice(0, 2)
        .map((w) => w[0])
        .join("")
        .toUpperCase(),
    ),
  );
  const url =
    safeURL(org.logo) ||
    (/^\/?(?:assets|logos)\//.test(org.logo || "") ? org.logo : "");
  if (
    url &&
    ![
      "careers",
      "living",
      "university",
      "computerscience",
      "psychology",
    ].includes(org.source)
  ) {
    const img = node("img");
    img.alt = "";
    img.loading = "lazy";
    img.onerror = () => img.remove();
    img.src = url;
    box.append(img);
  }
  return box;
}
function activity(e, org) {
  if (e.tags?.includes("Sport")) return "Sport";
  if (e.source === "newtheatre" || /\b(concert|showcase|recital)\b/i.test(e.title)) return "Performance";
  const title = e.title.toLowerCase();
  if (/workshop|tutorial|practical|masterclass|class\b/.test(title))
    return "Workshop";
  if (
    /social|quiz|party|bowling|karaoke|\bpub\b|crawl|dinner|games night|\bball\b|club night/.test(
      title,
    )
  )
    return "Social";
  if (/talk|panel|lecture|seminar|discussion/.test(title)) return "Talk";
  return org.group === "Sports" ? "Sport" : "Other";
}
function eventKey(e) {
  return [e.organiser, e.url, e.date, e.time].join("|");
}
const slotCounts = new Map();
function bookmarkSlot(e) {
  return JSON.stringify([e.organiser, e.date, e.time, e.title.toLowerCase()]);
}
function bookmarkKeys(e) {
  const keys = [eventKey(e), ...(e.aliases || [])];
  const slot = bookmarkSlot(e);
  if (slotCounts.get(slot) === 1) keys.push(slot);
  return keys;
}
function restoreBookmarks() {
  if (!storageWritable) return;
  let raw;
  try {
    raw = localStorage.getItem("notts-saved") || "[]";
    records = JSON.parse(raw).map(item => Array.isArray(item) ? item : [item]);
  } catch {}
  const today = dayKey(new Date());
  const direct = new Map(), aliases = new Map(), slots = new Map();
  for (const e of events) {
    if ((e.endDate || e.date) < today) continue;
    direct.set(eventKey(e), e);
    direct.set(eventKey(e) + "|" + e.title, e);
    for (const key of e.aliases || []) {
      aliases.set(key,e);
      aliases.set(key + "|" + e.title,e);
    }
    if (slotCounts.get(bookmarkSlot(e)) === 1) slots.set(bookmarkSlot(e),e);
  }
  saved.clear();
  records = records.map(record => {
    const e = record.map(key => direct.get(key)).find(Boolean) ||
              record.map(key => aliases.get(key)).find(Boolean) ||
              record.map(key => slots.get(key)).find(Boolean);
    if (!e) return record;
    saved.add(eventKey(e));
    return [...new Set([...bookmarkKeys(e), ...record.filter(key => !key.startsWith("["))])];
  });
  if (JSON.stringify(records) !== raw) storeBookmarks();
}
function storeBookmarks() {
  try {
    localStorage.setItem("notts-saved", JSON.stringify(records));
  } catch {
    storageWritable = false;
  }
}
function card(e, o) {
  const item = node("article"),
    body = node("div"),
    side = node("div", "side");
  const title = node("h3");
  title.append(link(e.title, e.url));
  const category = activity(e, o);
  const timing = e.date < dayKey(new Date()) ? "Ongoing" : e.time || "Time TBC";
  body.append(
    node(
      "div",
      "time",
      category === "Other" ? timing : timing + "  ·  " + category,
    ),
    title,
    node("p", "meta", [o.name, e.venue].filter(Boolean).join(" · ")),
  );
  const key = eventKey(e);
  const button = node("button", "save", saved.has(key) ? "★" : "☆");
  button.setAttribute(
    "aria-label",
    (saved.has(key) ? "Unsave " : "Save ") + e.title,
  );
  button.setAttribute("aria-pressed", saved.has(key));
  button.onclick = () => {
    restoreBookmarks();
    if (saved.has(key)) {
      saved.delete(key);
      records = records.filter(record => record[0] !== key);
    } else {
      saved.add(key);
      records.push(bookmarkKeys(e));
    }
    storeBookmarks();
    render();
  };
  side.append(button);
  item.append(logo(o), body, side);
  return item;
}
function orgCard(o) {
  const item = node("article"),
    body = node("div"),
    title = node("h3"),
    links = node("div", "org-links");
  title.textContent = o.name;
  if (safeURL(o.url)) links.append(link("Organiser website ↗", o.url));
  if (safeURL(o.instagram)) links.append(link("Instagram ↗", o.instagram));
  body.append(
    title,
    node("p", "meta", [o.group, o.category].filter(Boolean).join(" · ")),
    links,
  );
  item.append(logo(o), body);
  return item;
}
function dateMatch(e, today) {
  const when = get("when").value;
  if (when === "today")
    return e.date <= today && (e.endDate || e.date) >= today;
  if (when === "date" && get("date").value)
    return (
      e.date <= get("date").value && (e.endDate || e.date) >= get("date").value
    );
  if (when === "week") return e.date < after(today, 7);
  if (when === "weekend") {
    const dow = asDate(today).getUTCDay(),
      sat = after(today, dow === 0 ? -1 : 6 - dow);
    return e.date <= after(sat, 1) && (e.endDate || e.date) >= sat;
  }
  return true;
}
function render() {
  const directory = view === "organisers",
    today = dayKey(new Date());
  const q = get("query").value.trim().toLowerCase(),
    kind = get("kind").value,
    topic = get("topic").value;
  for (const el of document.querySelectorAll(".event-only"))
    el.hidden = directory;
  get("date").hidden = get("when").value !== "date";
  get("title").textContent = directory
    ? "Group directory"
    : view === "saved"
      ? "Saved events"
      : kind === "Societies"
        ? "Society diary"
        : "Campus diary";
  get("reset").hidden =
    !q &&
    !topic &&
    !get("org").value &&
    !get("when").value &&
    !get("activity").value &&
    kind === (view === "saved" ? "" : "Societies");
  get("filters").querySelector("summary").textContent =
    topic || get("org").value
      ? "More filters · " + [topic, get("org").value].filter(Boolean).length
      : "More filters";
  get("savedcount").textContent = saved.size || "";
  for (const b of document.querySelectorAll("[data-view]"))
    b.setAttribute("aria-pressed", b.dataset.view === view);
  const list = get("list");
  list.replaceChildren();
  const matches = directory
    ? [...groups.values()]
        .filter(
          (o) =>
            (!kind || o.group === kind) &&
            (!topic || o.category === topic) &&
            (!get("org").value || o.id === get("org").value) &&
            [o.name, o.group, o.category].join(" ").toLowerCase().includes(q),
        )
        .sort((a, b) => a.name.localeCompare(b.name))
    : events.filter((e) => {
        const o = groups.get(e.organiser),
          tags = e.tags || [];
        return (
          o &&
          (e.endDate || e.date) >= today &&
          dateMatch(e, today) &&
          (!kind || kind === o.group) &&
          (!topic || o.category === topic || tags.includes(topic)) &&
          (!get("org").value || o.id === get("org").value) &&
          (!get("activity").value ||
            get("activity").value === activity(e, o)) &&
          (view !== "saved" || saved.has(eventKey(e))) &&
          [e.title, e.venue, o.name, o.category, ...tags]
            .join(" ")
            .toLowerCase()
            .includes(q)
        );
      });
  let prev = "",
    section;
  for (const entry of matches.slice(0, limit)) {
    if (directory) {
      list.append(orgCard(entry));
      continue;
    }
    const displayDate = entry.date < today ? today : entry.date;
    if (prev !== displayDate) {
      prev = displayDate;
      const day = asDate(prev),
        block = node("section", "day-group"),
        heading = node("h2", "day");
      heading.setAttribute("aria-label", dateLabel(prev));
      const label =
        prev === today
          ? "Today"
          : prev === after(today, 1)
            ? "Tomorrow"
            : day.toLocaleDateString("en-GB", {
                weekday: "long",
                timeZone: "Europe/London",
              });
      heading.append(
        node("span", "weekday", label),
        node(
          "span",
          "calendar-date",
          day.toLocaleDateString("en-GB", {
            day: "numeric",
            month: "short",
            timeZone: "Europe/London",
          }),
        ),
      );
      section = node("div", "rows");
      block.append(heading, section);
      list.append(block);
    }
    section.append(card(entry, groups.get(entry.organiser)));
  }
  get("count").textContent =
    matches.length +
    " " +
    (directory ? "organiser" : "event") +
    (matches.length === 1 ? "" : "s");
  if (!matches.length)
    list.append(
      node(
        "p",
        "meta",
        view === "saved"
          ? "No saved events match. Save an event from Events to find it here."
          : "No matches. Try another date or clear your filters.",
      ),
    );
  get("more").hidden = matches.length <= limit;
}
function groupOptions() {
  const kind = get("kind").value;
  const available = [...groups.values()].filter(
    (o) => !kind || o.group === kind,
  );
  const ids = new Set(available.map((o) => o.id));
  const tags =
    view === "organisers"
      ? []
      : events.filter((e) => ids.has(e.organiser)).flatMap((e) => e.tags || []);
  options(
    "topic",
    "All interests",
    sorted([...available.map((o) => o.category), ...tags]).map((t) => [t, t]),
  );
  options(
    "org",
    "All groups",
    available
      .sort((a, b) => a.name.localeCompare(b.name))
      .map((o) => [o.id, o.name]),
  );
}
function reset() {
  for (const id of [
    "query",
    "when",
    "date",
    "kind",
    "topic",
    "org",
    "activity",
  ])
    get(id).value = "";
  get("kind").value = view === "saved" ? "" : "Societies";
  groupOptions();
  limit = 45;
}
async function start() {
  const response = await fetch("data.json", { cache: "no-cache" });
  if (!response.ok) throw Error();
  const data = await response.json();
  groups = new Map(data.organisers.map((o) => [o.id, o]));
  events = data.events
    .slice()
    .sort(
      (a, b) =>
        a.date.localeCompare(b.date) ||
        (a.time || "99").localeCompare(b.time || "99") ||
        a.title.localeCompare(b.title),
    );
  for (const event of events) {
    const slot = bookmarkSlot(event);
    slotCounts.set(slot, (slotCounts.get(slot) || 0) + 1);
  }
  restoreBookmarks();
  const orgs = [...groups.values()];
  options(
    "kind",
    "All types",
    sorted(orgs.map((o) => o.group)).map((k) => [k, k]),
  );
  reset();
  for (const b of document.querySelectorAll("[data-view]"))
    b.onclick = () => {
      view = b.dataset.view;
      reset();
      render();
    };
  for (const id of [
    "query",
    "when",
    "date",
    "kind",
    "topic",
    "org",
    "activity",
  ])
    get(id).addEventListener("input", () => {
      if (id === "kind") groupOptions();
      limit = 45;
      render();
    });
  get("reset").onclick = () => {
    reset();
    render();
  };
  get("more").onclick = () => {
    limit += 45;
    render();
  };
  if (data.updated)
    get("updated").textContent =
      "Directory updated " +
      new Date(data.updated).toLocaleDateString("en-GB", {
        day: "numeric",
        month: "short",
        year: "numeric",
        timeZone: "Europe/London",
      });
  render();
}
start().catch(
  () =>
    (get("list").textContent =
      "The listings could not load. Refresh to try again."),
);
