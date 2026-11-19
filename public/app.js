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
  limit = 45;
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
  if (url) {
    const img = node("img");
    img.alt = "";
    img.loading = "lazy";
    img.onerror = () => {
      // A society logo that fails to load falls back to the SU's own logo.
      if (img.dataset.fallback || url.includes("assets/logos/")) img.remove();
      else {
        img.dataset.fallback = "1";
        img.src = "assets/logos/uonsu.png";
      }
    };
    img.src = url;
    box.append(img);
  }
  return box;
}
function activity(e, org) {
  if (e.tags?.includes("Workshop")) return "Workshop";
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
function card(e, o) {
  const item = node("article"),
    body = node("div");
  const title = node("h3");
  title.append(link(e.title, e.url));
  const category = activity(e, o);
  const timing = e.date < dayKey(new Date()) ? "Ongoing" : (e.endTime ? e.time + "–" + e.endTime : e.time) || "Time TBC";
  const when = node("div", "time");
  when.append(node("span", "clock", timing));
  if (category !== "Other") when.append(node("span", "kind", category));
  body.append(
    when,
    title,
    node("p", "meta", [o.name, e.venue].filter(Boolean).join(" · ")),
  );
  item.className = "event-card";
  item.append(body, logo(o));
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
  get("title").textContent = directory
    ? "Groups"
    : {
          Societies: "Society events",
          Sports: "Sport",
          Careers: "Careers events",
          University: "University events",
        }[kind] || "Campus events";
  // Sheet filters (the tabs and date chips are always visible, so not counted)
  const pills = [];
  if (!directory && get("activity").value)
    pills.push([get("activity").value, () => (get("activity").value = "")]);
  if (get("org").value) pills.push([groups.get(get("org").value).name, () => (get("org").value = "")]);
  if (topic) pills.push([topic, () => (get("topic").value = "")]);
  if (!directory && get("when").value === "date" && get("date").value)
    pills.push([
      asDate(get("date").value).toLocaleDateString("en-GB", {
        weekday: "short",
        day: "numeric",
        month: "short",
        timeZone: "Europe/London",
      }),
      () => {
        get("when").value = "";
        get("date").value = "";
      },
    ]);
  get("filtertoggle").textContent = pills.length
    ? "Filters · " + pills.length
    : "Filters";
  get("filtertoggle").classList.toggle("has-active", pills.length > 0);
  const activeRow = get("active");
  activeRow.replaceChildren(
    ...pills.map(([label, clear]) => {
      const pill = node("button", "pill", label);
      pill.type = "button";
      pill.setAttribute("aria-label", "Remove filter: " + label);
      pill.onclick = () => {
        clear();
        limit = 45;
        render();
      };
      return pill;
    }),
  );
  activeRow.hidden = !pills.length;
  for (const chip of document.querySelectorAll("[data-when]"))
    chip.setAttribute("aria-pressed", chip.dataset.when === get("when").value);
  for (const tab of document.querySelectorAll("[data-kind]"))
    tab.setAttribute("aria-pressed", tab.dataset.kind === kind);
  for (const chip of document.querySelectorAll("[data-activity]"))
    chip.setAttribute(
      "aria-pressed",
      chip.dataset.activity === get("activity").value,
    );
  for (const b of document.querySelectorAll("[data-view]"))
    b.setAttribute("aria-pressed", b.dataset.view === view);
  const list = get("list");
  list.replaceChildren();
  const matches = directory
    ? [...groups.values()]
        .filter(
          (o) => o.active !== false &&
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
          (!kind || kind === o.group || e.cohosts?.some(id => groups.get(id)?.group === kind)) &&
          (!topic || o.category === topic || tags.includes(topic) || e.cohosts?.some(id => groups.get(id)?.category === topic)) &&
          (!get("org").value || o.id === get("org").value || e.cohosts?.includes(get("org").value)) &&
          (!get("activity").value ||
            get("activity").value === activity(e, o)) &&
          [e.title, e.venue, o.name, o.category, ...(e.cohosts || []).map(id => groups.get(id)?.name), ...tags]
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
            weekday: label === "Today" || label === "Tomorrow" ? "short" : undefined,
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
  get("apply").textContent = matches.length
    ? "Show " + get("count").textContent
    : "No matches";
  if (!matches.length)
    list.append(
      node(
        "p",
        "meta",
        "No matches. Try another date or clear your filters.",
      ),
    );
  get("more").hidden = matches.length <= limit;
}
function groupOptions() {
  const kind = get("kind").value;
  const selected = ["topic", "org"].map(id => [id, get(id).value]);
  const available = [...groups.values()].filter(
    (o) => o.active !== false && (!kind || o.group === kind),
  );
  const ids = new Set(available.map((o) => o.id));
  const tags =
    view === "organisers"
      ? []
      : events.filter((e) => ids.has(e.organiser) || e.cohosts?.some(id => ids.has(id))).flatMap((e) => e.tags || []);
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
  for (const [id, value] of selected) {
    if ([...get(id).options].some(option => option.value === value)) get(id).value = value;
  }
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
  if (view === "events") get("kind").value = "Societies";
  groupOptions();
  limit = 45;
}
function clearSheet() {
  get("org").value = "";
  get("activity").value = "";
  get("topic").value = "";
  get("date").value = "";
  if (get("when").value === "date") get("when").value = "";
  limit = 45;
}
function setSheet(open) {
  get("filterpanel").hidden = !open;
  get("scrim").hidden = !open;
  get("filtertoggle").setAttribute("aria-expanded", open);
  document.body.classList.toggle("sheet-open", open);
  if (open) get("sheetclose").focus();
  else get("filtertoggle").focus();
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
      if (id === "date") get("when").value = get("date").value ? "date" : "";
      limit = 45;
      render();
    });
  const pick = (selector, id, key) => {
    for (const button of document.querySelectorAll(selector))
      button.onclick = () => {
        const value = button.dataset[key];
        get(id).value = id === "when" && get(id).value === value ? "" : value;
        if (id === "when") get("date").value = "";
        get(id).dispatchEvent(new Event("input"));
      };
  };
  pick("[data-when]", "when", "when");
  pick("[data-kind]", "kind", "kind");
  pick("[data-activity]", "activity", "activity");
  get("filtertoggle").onclick = () => setSheet(get("filterpanel").hidden);
  get("sheetclose").onclick = () => setSheet(false);
  get("apply").onclick = () => setSheet(false);
  get("scrim").onclick = () => setSheet(false);
  document.addEventListener("keydown", (event) => {
    if (event.key === "Escape" && !get("filterpanel").hidden) setSheet(false);
  });
  get("reset").onclick = () => {
    clearSheet();
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
