const get = id => document.getElementById(id);
const node = (tag, cls, text) => {
  const element = document.createElement(tag);
  if (cls) element.className = cls;
  if (text) element.textContent = text;
  return element;
};
const dayKey = date => new Intl.DateTimeFormat('sv-SE',{timeZone:'Europe/London'}).format(date);
const asDate = day => new Date(day+'T12:00:00Z');
const after = (day, n) => { const d=asDate(day); d.setUTCDate(d.getUTCDate()+n); return dayKey(d); };
const dateLabel = day => asDate(day).toLocaleDateString('en-GB',{weekday:'long',day:'numeric',month:'long',year:'numeric',timeZone:'Europe/London'});
function safeURL(value) {
  try { const url=new URL(value); if (['http:','https:'].includes(url.protocol)) return url.href; } catch {}
  return '';
}
function link(text, url) {
  const a=node('a',null,text); const href=safeURL(url);
  if (href) { a.href=href; a.target='_blank'; a.rel='noopener noreferrer'; }
  return a;
}
let groups=new Map(), events=[], view='events', limit=45, saved=new Set();
try {saved=new Set(JSON.parse(localStorage.getItem('notts-saved')||'[]'));} catch {}
function options(id,label,items) {
  const el=get(id); el.replaceChildren(new Option(label,''));
  for(const [value,text] of items) el.add(new Option(text,value));
}
const sorted = values => [...new Set(values.filter(Boolean))].sort((a,b)=>a.localeCompare(b));
function logo(org) {
  const box=node('div','badge');box.setAttribute('aria-hidden','true');
  box.append(node('span','',org.name.split(/\s+/).filter(w=>w && !['of','and','the'].includes(w.toLowerCase())).slice(0,2).map(w=>w[0]).join('').toUpperCase()));
  const url=safeURL(org.logo)||(/^\/?(?:assets|logos)\//.test(org.logo||'')?org.logo:'');
  if(url && url!==groups.get('university')?.logo){const img=node('img');img.alt='';img.loading='lazy';img.onerror=()=>img.remove();img.src=url;box.append(img);}
  return box;
}
function priceType(value) {
  const p=(value||'').trim();
  if (/^(free\b|£0(?:\.00)?$)/i.test(p)) return 'free';
  if (/£\s*\d|paid/i.test(p)) return 'paid';
  return 'unknown';
}
function eventKey(e){return [e.organiser,e.url,e.date,e.time].join('|');}
function card(e,o) {
  const item=node('article'),body=node('div'),side=node('div','side');
  const title=node('h3');title.append(link(e.title,e.url));
  body.append(node('div','time',e.date<dayKey(new Date())?'Ongoing':e.time||'Time on organiser page'),title,node('p','meta',[o.name,e.venue].filter(Boolean).join(' · ')));
  const tags=node('div','tags');
  tags.append(node('span',priceType(e.price)==='free'?'chip free':'chip',e.price||'Price unlisted'));
  body.append(tags); const key=eventKey(e);
  const button=node('button','save',saved.has(key)?'★':'☆');
  button.setAttribute('aria-label',(saved.has(key)?'Unsave ':'Save ')+e.title);button.setAttribute('aria-pressed',saved.has(key));
  button.onclick=()=>{if(saved.has(key))saved.delete(key);else saved.add(key);try{localStorage.setItem('notts-saved',JSON.stringify([...saved]));}catch{}render();};
  side.append(button,logo(o));item.append(body,side);return item;
}
function orgCard(o){
  const item=node('article'),body=node('div'),title=node('h3'),links=node('div','org-links');
  title.textContent=o.name;
  if(safeURL(o.url))links.append(link('Organiser website ↗',o.url));
  if(safeURL(o.instagram))links.append(link('Instagram ↗',o.instagram));
  body.append(title,node('p','meta',[o.group,o.category].filter(Boolean).join(' · ')),links);
  item.append(body,logo(o));return item;
}
function dateMatch(e,today){
  const when=get('when').value;
  if(when==='today')return e.date<=today&&(e.endDate||e.date)>=today;
  if(when==='date'&&get('date').value)return e.date<=get('date').value&&(e.endDate||e.date)>=get('date').value;
  if(when==='week')return e.date<after(today,7);
  if(when==='weekend'){
    const dow=asDate(today).getUTCDay(),sat=after(today,dow===0?-1:6-dow);
    return e.date<=after(sat,1)&&(e.endDate||e.date)>=sat;
  }
  return true;
}
function render(){
  const directory=view==='organisers',today=dayKey(new Date());
  const q=get('query').value.trim().toLowerCase(),kind=get('kind').value,topic=get('topic').value;
  get('filters').hidden=directory;
  get('date').hidden=get('when').value!=='date';
  get('title').replaceChildren(document.createTextNode(({events:'Campus events',organisers:'Organisers',saved:'Saved events'})[view]),node('span','','.'));
  get('sectionTitle').textContent=directory?'Directory':view==='saved'?'Your list':'Upcoming';
  get('savedcount').textContent=saved.size||'';
  for(const b of document.querySelectorAll('[data-view]'))b.setAttribute('aria-pressed',b.dataset.view===view);
  const list=get('list');list.replaceChildren();
  const matches=directory?[...groups.values()].filter(o=>[o.name,o.group,o.category].join(' ').toLowerCase().includes(q)).sort((a,b)=>a.name.localeCompare(b.name)):
    events.filter(e=>{
      const o=groups.get(e.organiser), tags=e.tags||[];
      return o&&(e.endDate||e.date)>=today&&dateMatch(e,today)&&(!kind||kind===o.group)&&(!topic||o.category===topic||tags.includes(topic))&&(!get('org').value||o.id===get('org').value)&&(!get('price').value||priceType(e.price)===get('price').value)&&(view!=='saved'||saved.has(eventKey(e)))&&[e.title,e.venue,o.name,o.category,...tags].join(' ').toLowerCase().includes(q);
    });
  get('apply').textContent='Show '+matches.length+(directory?' organisers':' events');
  for(const b of document.querySelectorAll('[data-when]')){b.hidden=directory;b.setAttribute('aria-pressed',b.dataset.when===get('when').value);}
  get('free').hidden=directory;get('free').setAttribute('aria-pressed',get('price').value==='free');
  const extras=['query','kind','org','topic'].filter(id=>get(id).value).length+Number(['date','week'].includes(get('when').value))+Number(['unknown','paid'].includes(get('price').value));
  get('openFilter').textContent=(directory?'Search':'Filters')+(extras?' · '+extras:'');
  let prev='';
  for(const entry of matches.slice(0,limit)){
    if(directory){list.append(orgCard(entry));continue;}
    const displayDate=entry.date<today?today:entry.date;
    if(prev!==displayDate){prev=displayDate;const relative=prev===today?'Today':prev===after(today,1)?'Tomorrow':'';list.append(node('h2','day',relative?relative+' · '+asDate(prev).toLocaleDateString('en-GB',{weekday:'short',day:'numeric',month:'short',timeZone:'Europe/London'}):dateLabel(prev)));}
    list.append(card(entry,groups.get(entry.organiser)));
  }
  get('count').textContent=matches.length+' '+(directory?'organiser':'event')+(matches.length===1?'':'s');
  if(!matches.length)list.append(node('p','meta',view==='saved'?'No saved events match. Save an event from Explore to find it here.':'No matches. Try another date or clear your filters.'));
  get('more').hidden=matches.length<=limit;
}
function reset(){for(const id of ['query','when','date','kind','topic','org','price'])get(id).value='';limit=45;}
async function start(){
  const response=await fetch('data.json',{cache:'no-cache'});if(!response.ok)throw Error();
  const data=await response.json();
  groups=new Map(data.organisers.map(o=>[o.id,o]));
  events=data.events.slice().sort((a,b)=>a.date.localeCompare(b.date)||(a.time||'99').localeCompare(b.time||'99')||a.title.localeCompare(b.title));
  const today=dayKey(new Date());
  saved=new Set(events.filter(e=>(e.endDate||e.date)>=today && (saved.has(eventKey(e)) || saved.has(eventKey(e)+'|'+e.title))).map(eventKey));
  const orgs=[...groups.values()];
  options('kind','All types',sorted(orgs.map(o=>o.group)).map(k=>[k,k]));
  options('topic','All subjects & interests',sorted([...orgs.map(o=>o.category),...events.flatMap(e=>e.tags||[])]).map(k=>[k,k]));
  options('org','All organisers',orgs.sort((a,b)=>a.name.localeCompare(b.name)).map(o=>[o.id,o.name]));
  for(const b of document.querySelectorAll('[data-view]'))b.onclick=()=>{view=b.dataset.view;reset();render();};
  for(const id of ['query','when','date','kind','topic','org','price'])get(id).addEventListener('input',()=>{limit=45;render();});
  get('reset').onclick=()=>{reset();render();};get('more').onclick=()=>{limit+=45;render();};
  for(const b of document.querySelectorAll('[data-when]'))b.onclick=()=>{get('when').value=b.dataset.when;limit=45;render();};
  get('free').onclick=()=>{get('price').value=get('price').value==='free'?'':'free';limit=45;render();};
  get('openFilter').onclick=()=>get('sheet').showModal();
  get('closeFilter').onclick=get('apply').onclick=()=>get('sheet').close();
  if(data.updated)get('updated').textContent='Directory updated '+new Date(data.updated).toLocaleDateString('en-GB',{day:'numeric',month:'short',year:'numeric',timeZone:'Europe/London'});
  render();
}
start().catch(()=>get('list').textContent='The listings could not load. Refresh to try again.');
