/* Today agenda: all writes are local connection preferences, never calendar events. */
const $=s=>document.querySelector(s);
const node=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const calendarIcon=()=>{const n=document.createElementNS('http://www.w3.org/2000/svg','svg');for(const[k,v]of Object.entries({viewBox:'0 0 24 24',width:20,height:20,fill:'none',stroke:'currentColor','stroke-width':1.3,'aria-hidden':'true'}))n.setAttribute(k,v);const p=document.createElementNS(n.namespaceURI,'path');p.setAttribute('d','M5 5h14a1 1 0 0 1 1 1v14H4V6a1 1 0 0 1 1-1ZM8 2v6m8-6v6M4 10h16');n.append(p);return n;};
const safeLink=(value,fallback)=>{try{const u=new URL(value);return u.protocol==='https:'&&['calendar.google.com','www.google.com'].includes(u.hostname)?u.href:fallback;}catch{return fallback;}};
export function createAgenda(api,notify,{preview=false}={}){
 let calendar={},signature='',busy=false,awaitingSave=false,offset=0;
 const dialog=$('#calendar-dialog');
 function message(text){$('#calendar-message').textContent=text;$('#calendar-message').hidden=!text;}
 async function signIn(){
  if(preview){message('This preview uses sample events. Connect your calendar in the live app.');return;}
  if(busy)return;busy=true;message('Opening Google sign-in…');
  try{const r=await api('calendar/connect','POST',{});const u=new URL(r.url);if(u.origin!=='https://accounts.google.com')throw Error('Calendar sign-in could not open.');location.assign(u.href);}
  catch(e){message(e.message);busy=false;}
 }
 function openSettings(){
  message('');$('#calendar-setup').hidden=!!calendar.configured;
  $('#calendar-authorize').hidden=!calendar.configured||calendar.authorized&&calendar.status!=='authorization_required';
  $('#calendar-options').hidden=!calendar.authorized;
  $('#calendar-disconnect').hidden=!calendar.authorized;
  $('#calendar-dialog-intro').textContent=calendar.authorized?'Choose the calendars shown in Today. Access is read-only.':'Connect Google Calendar to see today’s events. Access is read-only.';
  const options=$('#calendar-choices');options.replaceChildren();
  for(const c of calendar.calendars||[]){const label=node('label','calendar-choice'),input=node('input');input.type='checkbox';input.value=c.id;input.checked=(calendar.selected||[]).includes(c.id);label.append(input,node('span','',c.name));options.append(label);}
  dialog.showModal();
 }
 function update(value){calendar=value||{};if(awaitingSave&&['connected','unavailable','authorization_required'].includes(calendar.status)){awaitingSave=false;notify('');}render();}
 function render(){
  const tz=calendar.timezone||Intl.DateTimeFormat().resolvedOptions().timeZone;
  const now=Date.now()/1000;
  // Calendar-timezone day keys (YYYY-MM-DD); day arithmetic happens at UTC noon to avoid DST edges.
  const dayKey=ms=>new Intl.DateTimeFormat('en-CA',{year:'numeric',month:'2-digit',day:'2-digit',timeZone:tz}).format(new Date(ms));
  const noon=iso=>new Date(iso+'T12:00:00Z');
  const shift=(iso,n)=>{const d=noon(iso);d.setUTCDate(d.getUTCDate()+n);return d.toISOString().slice(0,10);};
  const between=(a,b)=>Math.round((noon(b)-noon(a))/864e5);
  const today=/^\d{4}-\d{2}-\d{2}$/.test(calendar.date||'')?calendar.date:dayKey(Date.now());
  const first=/^\d{4}-\d{2}-\d{2}$/.test(calendar.range_start||'')?between(today,calendar.range_start):-7;
  const last=/^\d{4}-\d{2}-\d{2}$/.test(calendar.range_end||'')?between(today,calendar.range_end):14;
  offset=Math.min(last,Math.max(first,offset));
  const day=shift(today,offset),isToday=offset===0;
  const date=new Intl.DateTimeFormat(undefined,{weekday:'short',month:'short',day:'numeric',timeZone:'UTC'}).format(noon(day));
  $('#agenda-day').textContent=isToday?'Today':offset===-1?'Yesterday':offset===1?'Tomorrow':new Intl.DateTimeFormat(undefined,{weekday:'long',timeZone:'UTC'}).format(noon(day));
  $('#today-date').textContent=date;
  $('#today-date').title=(isToday?'Today':'Selected day')+' · '+tz;
  $('#agenda-prev').disabled=offset<=first;$('#agenda-next').disabled=offset>=last;$('#agenda-today').hidden=isToday;
  $('#agenda').setAttribute('aria-label',(isToday?'Today':date)+' calendar events');
  const time=v=>new Intl.DateTimeFormat(undefined,{hour:'2-digit',minute:'2-digit',hour12:false,timeZone:tz}).format(new Date(v*1000));
  // An event belongs to every calendar day it overlaps; ends are exclusive, so step back one second.
  const onDay=e=>dayKey(e.start*1000)<=day&&day<=dayKey(Math.max(e.start,e.end-1)*1000);
  const all=(calendar.events||[]).filter(e=>Number.isFinite(e.start)&&Number.isFinite(e.end)&&onDay(e)&&(!isToday||e.end>now));
  all.sort((a,b)=>Number(b.all_day)-Number(a.all_day)||a.start-b.start);
  const key=JSON.stringify([calendar,day,Math.floor(now/30)]);
  if(key===signature)return;signature=key;
  const connected=calendar.authorized||calendar.status==='connected';
  const cached=calendar.status==='unavailable'||calendar.status==='authorization_required';
  $('#calendar-settings').textContent=connected?'Calendars ↗':'Connect ↗';
  $('#open-calendar').href=safeLink('https://calendar.google.com/calendar/u/0/r/day/'+day.replaceAll('-','/'),'https://calendar.google.com/');
  $('#open-calendar').hidden=!connected;
  const list=$('#agenda');list.replaceChildren();
  if(!connected){
   const box=node('div','agenda-empty');box.append(calendarIcon(),node('p','agenda-empty-title','Your day, in one place.'),node('p','caption','Connect Google Calendar to see what’s next.'));
   const button=node('button','calendar-connect-button','Connect Google Calendar');button.onclick=openSettings;box.append(button);list.append(box);
  }else if(!all.length){
   const box=node('div','agenda-empty');box.append(calendarIcon(),node('p','agenda-empty-title',cached?'Calendar needs a refresh':!(calendar.selected||[]).length?'No calendars selected':isToday?'No more events today':'Nothing scheduled'),node('p','caption',cached?'Showing the last available calendar sync.':!(calendar.selected||[]).length?'Choose calendars to show in Today.':isToday?'A little room to focus.':'No events on '+date+'.'));list.append(box);
  }else{
   let nextMarked=false;
   for(const e of all){
    const link=node('a','agenda-event');link.href=safeLink(e.html_url,'https://calendar.google.com/');link.target='_blank';link.rel='noopener noreferrer';link.append(calendarIcon());
    const range=node('div','agenda-time',e.all_day?'All day':time(e.start)+' – '+time(e.end));
    const body=node('div','agenda-event-body');body.append(node('p','agenda-event-title',e.title));
    let note=e.calendar_name||'Google Calendar',current=isToday&&!e.all_day&&e.start<=now;
    if(current){note='Now · ends '+time(e.end);link.classList.add('current');}
    else if(isToday&&!e.all_day&&!nextMarked){const min=Math.max(1,Math.ceil((e.start-now)/60));note=min<60?'Next · '+min+' min':'Next · '+time(e.start);nextMarked=true;link.classList.add('next');}
    body.append(node('p','agenda-event-note',note));link.append(range,body);link.title=e.title+' · '+(e.calendar_name||'Calendar');list.append(link);
   }
  }
  const checked=calendar.checked_at,age=checked?Math.max(0,Math.floor((Date.now()/1000-checked)/60)):null;
  let status=connected?'Google Calendar':'Not connected';
  if(calendar.status==='connecting')status='Connecting…';
  else if(calendar.status==='authorization_required')status='Reconnect to sync';
  else if(calendar.status==='unavailable')status=checked?'Sync unavailable · cached':'Sync unavailable';
  else if(checked)status+=' · '+(age<1?'synced just now':age+' min ago');
  $('#calendar-sync').textContent=status;$('#calendar-sync').title=checked?'Last sync '+new Date(checked*1000).toLocaleString():'';
  $('#calendar-sync').classList.toggle('stale',cached);
 }
 $('#calendar-settings').onclick=openSettings;
 $('#close-calendar').onclick=()=>dialog.close();
 $('#calendar-authorize').onclick=signIn;
 $('#calendar-client-file').onchange=async e=>{
  const file=e.target.files?.[0];if(!file)return;
  if(preview){message('Credentials are not used in preview mode.');e.target.value='';return;}
  if(file.size>32768){message('Choose the small OAuth Desktop app JSON file from Google Cloud.');return;}
  try{message('Saving the local connection settings…');const data=JSON.parse(await file.text());await api('calendar/setup','POST',data);calendar.configured=true;$('#calendar-setup').hidden=true;$('#calendar-authorize').hidden=false;message('Ready. Continue with Google to allow calendar reading.');}
  catch{message('Could not use that file. Choose a Google OAuth Desktop app credentials JSON.');}
  finally{e.target.value='';}
 };
 $('#calendar-save').onclick=async()=>{
  if(preview){dialog.close();return;}
  const selected=[...$('#calendar-choices').querySelectorAll('input:checked')].map(n=>n.value);
  if(selected.length>5){message('Choose up to five calendars.');return;}
  try{awaitingSave=true;notify('Updating Today…');await api('calendar/select','POST',{selected});dialog.close();}catch(e){awaitingSave=false;notify('');message(e.message);}
 };
 $('#calendar-refresh').onclick=async()=>{if(preview)return;try{await api('calendar/refresh','POST',{});message('Refreshing your calendar…');}catch(e){message(e.message);}};
 $('#calendar-disconnect').onclick=async()=>{if(preview){dialog.close();return;}try{await api('calendar/disconnect','POST',{});dialog.close();}catch(e){message(e.message);}};
 function go(step){offset=step===0?0:offset+step;signature='';render();}
 $('#agenda-prev').onclick=()=>go(-1);
 $('#agenda-next').onclick=()=>go(1);
 $('#agenda-today').onclick=()=>go(0);
 document.addEventListener('keydown',e=>{
  if(e.defaultPrevented||e.altKey||e.ctrlKey||e.metaKey||e.shiftKey||(e.key!=='ArrowLeft'&&e.key!=='ArrowRight'))return;
  if(document.querySelector('dialog[open]')||e.target.closest?.('input,textarea,select,[contenteditable="true"]'))return;
  e.preventDefault();go(e.key==='ArrowLeft'?-1:1);
 });
 setInterval(render,30000);
 return {update,openSettings};
}
