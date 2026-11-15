import {createAgenda} from '/assets/calendar.js';
import {GoogleLocationMap,locationCity} from '/assets/google-map.js';
const $=s=>document.querySelector(s);
const el=(tag,cls,text)=>{const n=document.createElement(tag);if(cls)n.className=cls;if(text!==undefined)n.textContent=text;return n;};
const paths={device:'M4 4h16v12H4zM8 20h8M12 16v4',phone:'M7 2h10v20H7zM11 19h2',band:'M7 7h10v10H7zM9 2v5m6-5v5M9 17v5m6-5v5M2 9h5m-5 6h5m10-6h5m-5 6h5',heart:'M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.7l-1.1-1.1a5.5 5.5 0 0 0-7.8 7.8L12 21l8.8-8.6a5.5 5.5 0 0 0 0-7.8Z',steps:'M7 2c-4 0-4 8-1 8s5-8 1-8ZM5 13c-3 0-4 6-1 7s5-6 1-7ZM18 7c-4 0-4 8-1 8s5-8 1-8ZM16 18c-3 0-3 4-1 4s4-4 1-4Z',flame:'M12 2c3 5-2 7 1 9 2-1 3-3 3-5 8 8 5 16-3 16S2 14 7 8c0 3 1 4 2 4 2-2 0-6 3-10Z',moon:'M20 15A9 9 0 0 1 9 4a9 9 0 1 0 11 11Z',issue:'M12 8v5m0 4h.01M22 12a10 10 0 1 1-20 0 10 10 0 0 1 20 0Z',pr:'M6 6v12m0-12a2 2 0 1 0 0-4 2 2 0 0 0 0 4Zm0 16a2 2 0 1 0 0-4 2 2 0 0 0 0 4ZM18 18V9c0-4-7-2-7-6m4 1-4-1 1 4m6 15a2 2 0 1 0 0-4 2 2 0 0 0 0 4Z'};
function icon(name){const s=document.createElementNS('http://www.w3.org/2000/svg','svg');for(const [k,v]of Object.entries({viewBox:'0 0 24 24',width:24,height:24,fill:'none',stroke:'currentColor','stroke-width':1.3,'stroke-linecap':'round','stroke-linejoin':'round','aria-hidden':'true'}))s.setAttribute(k,v);const p=document.createElementNS(s.namespaceURI,'path');p.setAttribute('d',paths[name]||paths.device);s.append(p);return s;}
const time=v=>new Date(typeof v==='number'?v*1000:v).toLocaleTimeString([],{hour12:false,hour:'2-digit',minute:'2-digit',second:'2-digit'});
function ago(v){if(!v)return 'not synced';const s=(Date.now()-new Date(typeof v==='number'?v*1000:v))/1000;if(!Number.isFinite(s))return 'not synced';if(s<60)return 'just now';if(s<3600)return `${Math.floor(s/60)} min ago`;if(s<86400)return `${Math.floor(s/3600)} h ago`;return `${Math.floor(s/86400)} d ago`;}
let state={},view=null,showSessions=false,selected=null,filter='all',socket,map,marker,circle,mapIdentity='',follow=true,lastFeedKey='',lastDevicesKey='',lastHealthKey='',lastTasksKey='',lastGithubKey='';
const demo=location.pathname==='/preview';
async function api(path,method='GET',data){const r=await fetch('/api/'+path,{method,headers:{'Content-Type':'application/json','X-inLoop-CSRF':state.csrf||''},body:data?JSON.stringify(data):undefined});if(!r.ok){const failure=await r.json().catch(()=>({}));throw Error(failure.error||'Could not save. Please try again.');}return r.json();}
function notice(text){$('#notice').textContent=text;$('#notice').hidden=!text;}
const agenda=createAgenda(api,notice,{preview:demo});
const calendarResult=new URL(location.href).searchParams.get('calendar');
if(calendarResult){
 if(calendarResult==='cancelled')notice('Calendar sign-in was cancelled. You can reconnect from Today.');
 const clean=new URL(location.href);clean.searchParams.delete('calendar');history.replaceState(null,'',clean.pathname+clean.search+clean.hash);
}

function connection(){
 const h=state.health||{},age=h.last_packet_age_sec;
 const capture=!!h.direct_ws_connected&&typeof age==='number'&&age<3;
 const captions=capture&&state.status?.bridge==='connected'&&h.provider_connection_state==='connected';
 $('#connection-dot').classList.toggle('on',capture);$('#listening-dot').classList.toggle('on',captions);
 $('#connection').textContent=capture?'Vexo 43 connected · Bluetooth':h.direct_ws_connected?'Vexo 43 · waiting for audio':'Vexo 43 · reconnecting';
 $('#listening').textContent=view&&view!==state.current_session?'Saved session':captions?'Listening':capture?'Reconnecting captions':'Waiting for audio';
}
function renderDevices(){
 const key=JSON.stringify([state.devices,state.phone,state.network,state.health?.direct_ws_connected,Math.floor(Date.now()/60000)]);
 if(key===lastDevicesKey)return;lastDevicesKey=key;
 const list=$('#device-list');const live=!!state.health?.direct_ws_connected;
 const network=state.network||{},phone=state.phone||{};
 const rows=[{name:'Vexo 43',description:live?'Bluetooth · audio and motion':'Not connected',active:live,icon:'band'},
 {name:'This Mac',description:network.local_ip||'Local receiver',active:true,icon:'device',detail:[network.local_ip&&'LAN '+network.local_ip,network.tailscale_ip&&'Tailscale '+network.tailscale_ip].filter(Boolean).join(' · ')}];
 if(phone.name||phone.connected)rows.push({name:/SM[-_]S952/i.test(phone.name||'')?'Galaxy S25':phone.name||'Phone',description:phone.connected?(phone.ip||'USB connected')+' · ADB':'USB disconnected',active:phone.connected,icon:'phone',detail:phone.connected?'Direct GPS and Health Connect over USB':'Reconnect your phone by USB'});
 const devices=state.devices?.devices||[];
 for(const d of devices){if(/mac/i.test(d.name))continue;if((phone.name||phone.connected)&&/phone|galaxy/i.test(d.name))continue;
 const name=/Dell Tower/i.test(d.model||'')?'Dell Tower':/VirtualMac/i.test(d.model||'')?'VM MacBook Pro':d.name;
 rows.push({name,description:d.connected?'Seen '+ago(d.lastSeen):'Last seen '+ago(d.lastSeen),active:d.connected,icon:d.type?.toLowerCase().includes('android')?'phone':'device',detail:[d.model,d.warpIpv4&&'WARP '+d.warpIpv4].filter(Boolean).join(' · ')});}
 $('#agenda-phone-status').textContent=phone.connected?'Phone · USB':'Phone · disconnected';
 for(const[target,items]of [[list,rows]]){
  target.replaceChildren();
  for(const d of items){const row=el('div','device'+(d.active?'':' inactive'));row.title=d.detail||d.description;row.append(icon(d.icon));const body=el('div');const title=el('div','device-name');if(d.active)title.append(el('i','dot on'));title.append(document.createTextNode(d.name));body.append(title,el('p','caption',d.description));row.append(body);target.append(row);}
 }

}
function renderHealth(){
 const h=state.telemetry?.health||{},direct=state.telemetry?.source==='adb';
 const key=JSON.stringify([h,state.phone,state.status?.telemetry,Math.floor(Date.now()/60000)]);if(key===lastHealthKey)return;lastHealthKey=key;
 $('#health-source').textContent=direct?(state.phone?.connected?'Phone · USB':'Phone · last USB sync'):'Phone · last cloud sync';
 const minute=60000,now=Date.now();const asTime=v=>new Date(typeof v==='number'?v*1000:v).getTime();
 const freshBpm=h.bpm!=null&&h.recordedAt&&now-asTime(h.recordedAt)<5*minute;
 const pulse=freshBpm?h.bpm:h.restingBpm;
 const sleep=h.sleepMinutes;
 const rows=[['heart',freshBpm?'Heart rate':'Resting heart rate',pulse??'—',pulse!=null?'bpm':'',freshBpm?h.recordedAt:h.restingRecordedAt],
 ['steps','Steps today',h.steps==null?'—':Number(h.steps).toLocaleString(),'',h.activityRecordedAt],
 ['flame','Calories today',h.caloriesBurned==null?'—':Math.round(h.caloriesBurned).toLocaleString(),'kcal',h.activityRecordedAt],
 ['moon','Last sleep',sleep==null?'—':`${Math.floor(sleep/60)} h ${Math.round(sleep%60)} m`,'',h.sleepRecordedAt]];
 const box=$('#health');box.replaceChildren();
 for(const[name,label,value,unit,recorded]of rows){const row=el('div','metric');row.append(icon(name));const body=el('div');body.append(el('p','metric-label',label));const val=el('p','metric-value',String(value));if(unit)val.append(el('small','',` ${unit}`));body.append(val);
 const note=recorded?ago(recorded):value==='—'?'No reading':'Time unavailable';const caption=el('p','reading-age',note);if(recorded)caption.title=new Date(recorded).toLocaleString();body.append(caption);row.append(body);box.append(row);}
}
function initMap(){if(!map)map=new GoogleLocationMap($('#map'));}
function renderMap(){
  initMap();
  const event=selected?(state.events||[]).find(e=>e.id===selected):null;
  const f=event?event.location:state.telemetry?.location;
  const recorded=f?.recordedAt==null?NaN:new Date(typeof f.recordedAt==='number'?f.recordedAt*1000:f.recordedAt).getTime();
  const age=(Date.now()-recorded)/1000;
  const valid=f&&Number.isFinite(f.latitude)&&Math.abs(f.latitude)<=90&&Number.isFinite(f.longitude)&&Math.abs(f.longitude)<=180&&Number.isFinite(f.accuracy)&&f.accuracy>=0&&Number.isFinite(recorded)&&age>=-5;
  $('#location-time').textContent=valid?(event?time(event.said_at):ago(f.recordedAt)):'';
  $('#location-time').title=valid?'GPS fix: '+new Date(recorded).toLocaleString()+(event?' · selected speech moment':''):'';
  $('#latest-location').hidden=!event;
  const open=$('#open-location');
  if(valid){open.href='https://www.google.com/maps/search/?'+new URLSearchParams({api:'1',query:`${f.latitude},${f.longitude}`});open.removeAttribute('aria-disabled');}
  else{open.removeAttribute('href');open.setAttribute('aria-disabled','true');$('#location-city').hidden=true;}
  const key=JSON.stringify([selected,f,Math.floor(Date.now()/60000)]);if(key===mapIdentity)return;mapIdentity=key;
  if(!valid){map.clear(event?'No matching GPS fix for this moment':'Waiting for phone GPS');$('#location-caption').textContent=event?'No matching GPS fix for this moment':'Waiting for a valid phone GPS fix';return;}
  map.update(f);
  const cityNode=$('#location-city'),lookup=JSON.stringify([f.latitude,f.longitude,selected]);
  if(cityNode.dataset.lookup!==lookup){
    const previousArea=cityNode.dataset.area,area=`${f.latitude.toFixed(2)},${f.longitude.toFixed(2)}`;
    cityNode.dataset.lookup=lookup;cityNode.dataset.area=area;
    if(previousArea!==area){cityNode.textContent='';cityNode.hidden=true;}
    locationCity(f).then(city=>{if(cityNode.dataset.lookup!==lookup)return;cityNode.textContent=city;cityNode.hidden=!city;});
  }
  const source=f.source==='adb'?'Phone GPS · USB':'Phone GPS';
  const quality=f.accuracy>50?' · approximate':'';
  const match=event&&f.match==='last_known'?' · last known fix':'';
  const freshness=event?' · '+Math.round(f.age_at_speech_sec)+' s before speech':age>120?' · last known fix':'';
  $('#location-caption').textContent=source+match+' · ±'+Math.round(f.accuracy)+' m'+quality+freshness;
  $('#location-caption').title='GPS recorded '+new Date(recorded).toLocaleString();
}
function selectEvent(id){selected=id;lastFeedKey='';renderFeed();renderMap();const node=document.getElementById('event-'+id);if(node){node.scrollIntoView({block:'nearest',behavior:'smooth'});follow=false;}}
let feedFinals,feedDraft,finalFeedKey='',feedRows=new Map(),feedReady=false,feedView=null,unseenSpeech=false;
const reduceMotion=()=>matchMedia('(prefers-reduced-motion: reduce)').matches;
function makeUtterance(e,t,index){
 const row=el('article','utterance');
 if(index===(e.event?.speaker_turns?.length||1)-1)row.id='event-'+e.id;
 row.tabIndex=0;row.setAttribute('aria-label','Select transcript moment');
 let label=Number.isInteger(t.speaker_id)?`Speaker ${t.speaker_id+1}`:'';
 if(t.voice_identity?.status==='match')label='You';
 const offset=(Number(t.sample_offset)-Number(e.event?.sample_offset))/16000;
 const stamp=e.said_at+(Number.isFinite(offset)?Math.max(0,offset):0);
 row.append(el('div','speaker',(label?label+' · ':'')+time(stamp)),el('p','speech',t.text||e.text));
 row.onclick=()=>selectEvent(e.id);
 row.onkeydown=k=>{if(k.key==='Enter'||k.key===' '){k.preventDefault();selectEvent(e.id);}};
 return row;
}
function renderFeed(){
 const feed=$('#feed'),events=state.events||[];
 if(!feedFinals){
  feed.replaceChildren();feedFinals=el('div','final-transcript');feedDraft=el('article','utterance partial');
  feedDraft.append(el('div','speaker','Speaking…'),el('p','speech'));
  feed.append(feedDraft,feedFinals);
 }
 const session=view||state.current_session,changedSession=feedView!==session;
 const shouldFollow=changedSession||(follow&&feed.scrollTop<60);
 const oldTop=feed.scrollTop,edge=feed.getBoundingClientRect().top;
 const anchor=[...feed.querySelectorAll('.utterance')].find(n=>!n.hidden&&n.getBoundingClientRect().bottom>edge);
 const anchorTop=anchor?.getBoundingClientRect().top;
 const draftText=state.partial?.text||'',draftChanged=feedDraft.querySelector('.speech').textContent!==draftText;
 const key=JSON.stringify([session,events.map(e=>[e.id,!!e.location]),selected]);let added=0;
 if(key!==finalFeedKey){
  finalFeedKey=key;const wanted=new Set();let previous=null;
  feedFinals.querySelector('.empty')?.remove();
  // Reverse copies, leaving saved event and speaker order intact in storage.
  const ordered=events.map((e,i)=>({e,i})).sort((a,b)=>b.e.said_at-a.e.said_at||b.i-a.i);
  for(const{e}of ordered){
   const turns=e.event?.speaker_turns?.length?e.event.speaker_turns:[{text:e.text}];
   for(let index=turns.length-1;index>=0;index--){
    const identity=e.id+':'+index;wanted.add(identity);let row=feedRows.get(identity);
    if(!row){
     row=makeUtterance(e,turns[index],index);feedRows.set(identity,row);added++;
     if(feedReady&&!changedSession&&Date.now()/1000-e.said_at<30&&!reduceMotion())row.animate([{opacity:0,transform:'translateY(-3px)'},{opacity:1,transform:'translateY(0)'}],{duration:160,easing:'cubic-bezier(.2,.7,.2,1)'});
    }
    row.classList.toggle('selected',selected===e.id);
    let pin=row.querySelector('.location-mark');
    if(e.location&&!pin){pin=el('span','location-mark','⌖');pin.setAttribute('aria-label','GPS available');row.querySelector('.speaker').append(pin);}
    else if(!e.location&&pin)pin.remove();
    const next=previous?previous.nextElementSibling:feedFinals.firstElementChild;
    if(next!==row)feedFinals.insertBefore(row,next);previous=row;
   }
  }
  for(const[id,row]of feedRows){if(!wanted.has(id)){row.remove();feedRows.delete(id);}}
  if(!events.length&&!draftText)feedFinals.append(el('p','empty','Your conversation will appear here.'));
 }
 feedDraft.hidden=!draftText;
 if(draftText){feedFinals.querySelector('.empty')?.remove();feedDraft.querySelector('.speech').textContent=draftText;}
 else feedDraft.querySelector('.speech').textContent='';
 if(shouldFollow){
  feed.scrollTop=0;follow=true;unseenSpeech=false;
 }else{
  // Preserve the visible passage as newer content is inserted above it.
  if(anchor?.isConnected&&!anchor.hidden)feed.scrollTop+=anchor.getBoundingClientRect().top-anchorTop;
  else feed.scrollTop=oldTop;
  if(added||(draftChanged&&draftText))unseenSpeech=true;
 }
 $('#new-words').hidden=!unseenSpeech;feedReady=true;feedView=session;
}
async function taskChange(task,changes){try{if(demo){Object.assign(task,changes);state.tasks=state.tasks.filter(t=>!t.deleted);renderTasks(true);}else await api('tasks/'+task.id,'PATCH',changes);}catch(e){notice(e.message);renderTasks(true);}}
function renderTasks(force=false){const tasks=state.tasks||[];const key=JSON.stringify([tasks,state.status?.tasks]);if(!force&&key===lastTasksKey)return;lastTasksKey=key;$('#task-count').textContent=tasks.filter(t=>t.status!=='done').length+' open';const box=$('#tasks');box.replaceChildren();if(!tasks.length)box.append(el('p','empty','Tasks from your conversation will appear here. You can also add one.'));for(const t of tasks){const row=el('div','task'+(t.status==='done'?' done':''));const check=el('input');check.type='checkbox';check.checked=t.status==='done';check.setAttribute('aria-label','Complete '+t.title);check.onchange=()=>taskChange(t,{status:check.checked?'done':'open'});const body=el('div');body.append(el('p','task-title',t.title));if(t.kind==='calendar'||t.kind==='action_item')body.append(el('p','task-kind',t.kind==='calendar'?'Calendar suggestion':'Action item'));if(t.calendar_action?.message){const status=el('p','task-kind calendar-action',t.calendar_action.message);status.title=t.calendar_action.status;body.append(status);}if(t.source_id){const source=(state.events||[]).find(e=>e.id===t.source_id);const b=el('button','source',source?time(source.said_at):'View source');b.title=t.quote||'View source';b.onclick=()=>selectEvent(t.source_id);body.append(b);}const actions=el('div','task-actions');const edit=el('button','','Edit');edit.onclick=()=>{const title=prompt('Task',t.title);if(title?.trim())taskChange(t,{title});};const del=el('button','','Delete');del.onclick=()=>taskChange(t,{deleted:true});const schedule=el('button','','Add to calendar');schedule.onclick=async()=>{try{const source=(state.events||[]).find(e=>e.id===t.source_id)||(t.source_id&&!demo?await api('events/'+encodeURIComponent(t.source_id)):null);agenda.addTask(t,source);}catch(e){notice(e.message);}};actions.append(edit,del,schedule);body.append(actions);row.append(check,body);box.append(row);}$('#task-status').textContent=state.status?.tasks==='extracting'?'Finding actions…':state.status?.tasks==='unavailable'?'Suggestions unavailable · manual tasks work':'Suggestions from finalized speech';}
function renderGithub(){const github=state.github||{},key=JSON.stringify([github,filter]);if(key===lastGithubKey)return;lastGithubKey=key;const box=$('#github');box.replaceChildren();const account=github.login||github.user||'';if(account){$('#github-scope').textContent=account+(github.status==='unavailable'?' · cached':'');$('#github-scope').title=(github.checked_at?'Updated '+ago(github.checked_at):'GitHub')+(github.status==='unavailable'?' · refresh unavailable':'');$('#github-link').href='https://github.com/issues?q='+encodeURIComponent('is:open involves:'+account);}
 const items=(github.items||[]).filter(i=>filter==='all'||(filter==='prs'?i.pull_request:!i.pull_request));if(!items.length)box.append(el('p','empty',github.status==='connected'?'No open work in this view.':github.status==='unavailable'?'GitHub is unavailable.':'Loading project issues and PRs…'));for(const i of items){const link=el('a','github-item');const url=new URL(i.html_url||'https://github.com');if(url.protocol!=='https:'||url.hostname!=='github.com')continue;link.href=url.href;link.target='_blank';link.rel='noopener noreferrer';link.append(icon(i.pull_request?'pr':'issue'));const body=el('div');body.append(el('p','',i.title),el('p','caption',`${i.repo?.split('/').pop()||'marshal'} · ${i.pull_request?'PR':'Issue'} #${i.number}`));link.append(body);box.append(link);}}
function renderSessions(){const box=$('#sessions');box.replaceChildren();for(const s of state.sessions||[]){const b=el('button','session-row');const body=el('div');body.append(el('strong','',s.title),el('p','',new Date(s.started_at*1000).toLocaleDateString()+' · '+s.segments+' segments'));b.append(body,el('span','muted',s.id===state.current_session?'Live':'↗'));b.onclick=async()=>{if(demo){showSessions=false;render();return;}try{view=s.id;const next=await api('state?session='+encodeURIComponent(view));state=next;showSessions=false;selected=null;lastFeedKey='';render();}catch(e){notice(e.message);}};box.append(b);}}
function render(){agenda.update(state.calendar);connection();$('#session-list').hidden=!showSessions;$('#dashboard').hidden=showSessions;$('#live-tab').classList.toggle('active',!showSessions);$('#sessions-tab').classList.toggle('active',showSessions);$('#session-title').textContent=view&&view!==state.current_session?(state.sessions||[]).find(s=>s.id===view)?.title||'Saved session':'';$('#session-title').hidden=!$('#session-title').textContent;renderDevices();renderHealth();renderTasks();renderGithub();renderFeed();renderMap();if(showSessions)renderSessions();}
async function reload(){const result=await api('state'+(view?'?session='+encodeURIComponent(view):''));state=result;render();}
function connect(){socket=new WebSocket((location.protocol==='https:'?'wss://':'ws://')+location.host+'/api/live');socket.onmessage=async m=>{try{const msg=JSON.parse(m.data);if(msg.type==='state'){if(view&&view!==msg.data.current_session){state={...state,calendar:msg.data.calendar,phone:msg.data.phone,network:msg.data.network,health:msg.data.health,devices:msg.data.devices,telemetry:msg.data.telemetry,github:msg.data.github,sessions:msg.data.sessions,status:msg.data.status,current_session:msg.data.current_session};}else state=msg.data;render();}else if(msg.type==='telemetry'){Object.assign(state,{health:msg.health,telemetry:msg.telemetry,devices:msg.devices,phone:msg.phone,network:msg.network,status:msg.status});connection();renderDevices();renderHealth();renderMap();}else if(msg.type==='calendar'){state.calendar=msg.data;agenda.update(msg.data);}else if(msg.type==='github'){state.github=msg.data;renderGithub();}else if(msg.type==='transcript'&&(!view||view===msg.session_id)){state.events=(state.events||[]).filter(e=>e.id!==msg.data.id).concat(msg.data).slice(-200);state.partial=null;renderFeed();}else if(msg.type==='partial'&&(!view||view===msg.session_id)){state.partial=msg.data;renderFeed();}else if(msg.type==='task_status'){state.status.tasks=msg.status;renderTasks();}else if(msg.type==='gap'){notice('Audio interrupted briefly. Captions resume as audio returns.');}}catch{notice('Reconnecting to the workspace…');}};socket.onclose=()=>{state.status={...state.status,bridge:'reconnecting'};connection();setTimeout(connect,1500);};}
$('#all-devices').onclick=()=>$('#devices-dialog').showModal();
$('#close-devices').onclick=()=>$('#devices-dialog').close();
$('#devices-dialog').onclick=e=>{if(e.target===$('#devices-dialog')){const r=e.target.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)e.target.close();}};
$('#add-task').onsubmit=async e=>{e.preventDefault();const input=$('#task-title'),title=input.value.trim();if(!title)return;try{if(demo){state.tasks.unshift({id:crypto.randomUUID(),title,status:'open'});renderTasks(true);}else await api('tasks','POST',{title,session_id:view||state.current_session});input.value='';notice('');}catch(error){notice(error.message);}};
$('#github-filters').onclick=e=>{const b=e.target.closest('[data-filter]');if(!b)return;filter=b.dataset.filter;for(const n of $('#github-filters').children)n.classList.toggle('active',n===b);renderGithub();};
$('#sessions-tab').onclick=()=>{showSessions=true;render();};$('#live-tab').onclick=async()=>{view=null;showSessions=false;selected=null;follow=true;lastFeedKey='';if(demo)render();else await reload().catch(e=>notice(e.message));};
$('#new-session').onclick=async()=>{const title=prompt('Session name','Hackathon session');if(!title?.trim())return;try{if(demo){notice('Preview only. New sessions are available in the live app.');return;}await api('sessions','POST',{title});view=null;showSessions=false;selected=null;await reload();}catch(e){notice(e.message);}};
$('#latest-location').onclick=()=>{selected=null;lastFeedKey='';renderFeed();renderMap();};$('#expand').onclick=()=>{const expanded=document.body.classList.toggle('expanded');$('#expand').setAttribute('aria-expanded',String(expanded));$('#expand').setAttribute('aria-label',expanded?'Collapse transcript':'Expand transcript');};document.addEventListener('keydown',e=>{if(e.key==='Escape'){document.body.classList.remove('expanded');$('#expand').setAttribute('aria-expanded','false');}});
$('#feed').onscroll=()=>{const f=$('#feed');follow=f.scrollTop<60;if(follow){unseenSpeech=false;$('#new-words').hidden=true;}};$('#new-words').onclick=()=>{follow=true;unseenSpeech=false;$('#feed').scrollTo({top:0,behavior:reduceMotion()?'instant':'smooth'});$('#new-words').hidden=true;};
try{document.body.classList.toggle('dark',localStorage.getItem('inloop-theme')==='dark');}catch{}$('#theme').onclick=()=>{const dark=document.body.classList.toggle('dark');try{localStorage.setItem('inloop-theme',dark?'dark':'light');}catch{}};
function clock(){$('#clock').textContent=new Date().toLocaleTimeString([],{hour:'numeric',minute:'2-digit',second:'2-digit'});}clock();setInterval(clock,1000);setInterval(()=>{renderDevices();renderHealth();renderMap();},60000);
if(demo){const d=await import('/assets/demo.js');state=d.default;notice('Design preview · sample data');$('#privacy').textContent='Preview only · no capture or AI requests';render();}else{await reload().catch(()=>notice('Connecting to the local workspace…'));connect();}
