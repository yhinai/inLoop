/* Calendar changes happen only when the event form is submitted. */
const $=s=>document.querySelector(s);
const localTime=(seconds,tz)=>{
 const parts=new Intl.DateTimeFormat('en-CA',{timeZone:tz,year:'numeric',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit',hourCycle:'h23'}).formatToParts(new Date(seconds*1000));
 const values=Object.fromEntries(parts.map(p=>[p.type,p.value]));
 return `${values.year}-${values.month}-${values.day}T${values.hour}:${values.minute}`;
};
const shiftDate=(day,amount)=>{const d=new Date(day+'T12:00:00Z');d.setUTCDate(d.getUTCDate()+amount);return d.toISOString().slice(0,10);};
function suggestedTime(text,reference,tz){
 const base=localTime(reference,tz).slice(0,10);let day=null;
 const explicit=text.match(/\b(\d{4}-\d{2}-\d{2})\b/);
 if(explicit)day=explicit[1];
 else if(/\btomorrow\b/i.test(text))day=shiftDate(base,1);
 else if(/\btoday\b/i.test(text))day=base;
 else{
  const names=['sunday','monday','tuesday','wednesday','thursday','friday','saturday'];
  const match=text.toLowerCase().match(/\b(sunday|monday|tuesday|wednesday|thursday|friday|saturday)\b/);
  if(match){const current=new Date(base+'T12:00:00Z').getUTCDay();let delta=(names.indexOf(match[1])-current+7)%7;if(!delta&&/\bnext\b/i.test(text))delta=7;day=shiftDate(base,delta);}
 }
 const time=text.match(/\b(\d{1,2})(?::(\d{2}))?\s*(am|pm)\b/i);
 if(!day||!time)return null;
 const hour=Number(time[1]),minute=Number(time[2]||0);if(hour<1||hour>12||minute>59)return null;
 const h=hour%12+(time[3].toLowerCase()==='pm'?12:0);
 return `${day}T${String(h).padStart(2,'0')}:${String(minute).padStart(2,'0')}`;
}
function plusMinutes(value,minutes){const d=new Date(value+'Z');d.setUTCMinutes(d.getUTCMinutes()+minutes);return d.toISOString().slice(0,16);}
export function createEventEditor(api,notify,getCalendar,update,openSettings,{preview=false}={}){
 const dialog=$('#event-dialog'),form=$('#event-form');let editing=null,busy=false;
 const message=text=>{$('#event-message').textContent=text;$('#event-message').hidden=!text;};
 function close(){if(!busy)dialog.close();}
 function setBusy(value){busy=value;for(const field of form.elements)field.disabled=value;$('#event-calendar').disabled=value||!!editing;}
 function open(event=null,task=null,sourceEvent=null){
  const calendar=getCalendar();
  if(preview){notify('Calendar changes are available in the live app.');return;}
  if(!calendar.authorized||(calendar.write_authorization_required??!calendar.writable)){openSettings();return;}
  const calendars=(calendar.calendars||[]).filter(c=>c.writable);
  if(!calendars.length){notify('No editable calendar is available for this account.');return;}
  if(event&&!calendars.some(c=>c.id===event.calendar_id)){notify('This calendar is read-only.');return;}
  editing=event;busy=false;form.reset();message('');
  const select=$('#event-calendar');select.replaceChildren();
  for(const c of calendars){const option=document.createElement('option');option.value=c.id;option.textContent=c.name;select.append(option);}
  select.value=event?.calendar_id||calendars.find(c=>c.primary)?.id||calendars[0].id;
  const tz=event?.timezone||calendars.find(c=>c.id===select.value)?.timezone||calendar.timezone||'America/Los_Angeles';
  $('#event-timezone').value=tz;$('#event-title').value=event?.title||task?.title||'';
  $('#event-description').value=event?.description||(task?'From inLoop transcript:\n'+task.title:'');
  $('#event-all-day').checked=!!event?.all_day;const allDay=!!event?.all_day;
  $('#event-start').type=allDay?'date':'datetime-local';$('#event-end').type=allDay?'date':'datetime-local';$('#event-end-label').textContent=allDay?'Through':'Ends';
  let start=event?localTime(event.start,tz):task?suggestedTime(task.title,sourceEvent?.said_at||Date.now()/1000,tz):(calendar.date&&calendar.date!==localTime(Date.now()/1000,tz).slice(0,10)?calendar.date+'T09:00':localTime(Math.ceil(Date.now()/1800000)*1800,tz));
  let end=event?localTime(event.end,tz):start?plusMinutes(start,30):'';
  if(allDay){start=event.start_iso?.slice(0,10)||start.slice(0,10);end=shiftDate(event.end_iso?.slice(0,10)||end.slice(0,10),-1);}
  $('#event-start').value=start||'';$('#event-end').value=end||'';
  $('#event-dialog-title').textContent=event?'Edit event':'New event';$('#event-save').textContent=event?'Save changes':'Add event';$('#event-delete').hidden=!event;
  $('#event-source').hidden=!task;$('#event-source').textContent=task?'From your task · check the date and time before saving.':'';
  setBusy(false);dialog.showModal();$('#event-title').focus();
 }
 $('#event-close').onclick=close;$('#event-cancel').onclick=close;
 dialog.addEventListener('cancel',e=>{if(busy)e.preventDefault();});
 $('#event-all-day').onchange=()=>{
  const allDay=$('#event-all-day').checked;
  for(const id of ['event-start','event-end']){const input=$('#'+id),value=input.value;input.type=allDay?'date':'datetime-local';input.value=allDay?value.slice(0,10):value?value.slice(0,10)+'T09:00':'';}
  $('#event-end-label').textContent=allDay?'Through':'Ends';
  if(!allDay&&$('#event-start').value===$('#event-end').value)$('#event-end').value=plusMinutes($('#event-start').value,30);
 };
 $('#event-calendar').onchange=()=>{const c=(getCalendar().calendars||[]).find(c=>c.id===$('#event-calendar').value);if(c?.timezone)$('#event-timezone').value=c.timezone;};
 form.onsubmit=async e=>{
  e.preventDefault();if(busy||!form.reportValidity())return;
  const allDay=$('#event-all-day').checked,start=$('#event-start').value,end=$('#event-end').value;
  if((allDay&&end<start)||(!allDay&&end<=start)){message('The end must be after the start.');return;}
  const calendar_id=$('#event-calendar').value,event={title:$('#event-title').value.trim(),start,end:allDay?shiftDate(end,1):end,all_day:allDay,timezone:$('#event-timezone').value.trim(),description:$('#event-description').value};
  if(!event.title){message('Enter an event title.');return;}
  setBusy(true);message('Saving…');
  try{const result=await api('calendar/events'+(editing?'/'+encodeURIComponent(editing.id):''),editing?'PATCH':'POST',{calendar_id,event});update(result.calendar);setBusy(false);dialog.close();notify(editing?'Calendar event updated.':'Added to Google Calendar.');}
  catch(error){setBusy(false);message(error.message);}
 };
 $('#event-delete').onclick=async()=>{
  if(busy||!editing)return;
  if(!confirm(`Delete “${editing.title}” from Google Calendar?`))return;
  setBusy(true);message('Deleting…');
  try{const result=await api('calendar/events/'+encodeURIComponent(editing.id),'DELETE',{calendar_id:editing.calendar_id});update(result.calendar);setBusy(false);dialog.close();notify('Calendar event deleted.');}
  catch(error){setBusy(false);message(error.message);}
 };
 return {open,addTask:(task,event)=>open(null,task,event)};
}
