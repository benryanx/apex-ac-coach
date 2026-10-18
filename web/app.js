import {CoachRadio, groupNotes} from '/static/coaching.mjs';
import {EngineerAudio, volumeCommand} from '/static/audio.mjs';
import {rosterContext} from '/static/roster.mjs';
import {setupDisplay} from '/static/display.mjs';
import {SessionAwareness} from '/static/session.mjs';
import {InstructionUpdater} from '/static/instructions.mjs';
import {TelemetryNumbers} from '/static/numbers.mjs';
const $ = id => document.getElementById(id);
const token = document.querySelector('meta[name="coach-token"]').content;
setupDisplay(token);
const esc = s => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const time = ms => ms == null ? '—' : `${Math.floor(ms / 60000)}:${((ms % 60000) / 1000).toFixed(3).padStart(6, '0')}`;
const diff = ms => ms == null ? '—' : `${ms >= 0 ? '+' : '−'}${(Math.abs(ms) / 1000).toFixed(3)}`;
const pretty = s => s.replace(/_/g, ' ');
let state = null, mode = 'ac', seen = new Set(), initial = true, lastContext = 0, lastEvent = '';
let peer = null, channel = null, microphone = null, sessionId = null, ready = false, busy = false, muted = false, closing = false;
let transcript = '', lastTranscript = 0, closeResolve = null, finalized = false, feedStatus = 'waiting';
let verbosity = localStorage.getItem('apex-verbosity') || 'normal';
const radio=new CoachRadio(), instructionWaiters=new Map();
const sessionAwareness=new SessionAwareness();
let voiceStyleReady=false;
const motionPreference=matchMedia('(prefers-reduced-motion: reduce)');
const numbers=new TelemetryNumbers({reduced:()=>motionPreference.matches || document.hidden});
const tyreValues=[null,null,null,null];
let numberSession='',numberLap=null,numberStatus='',numberZone=null;
let snapNumbers=true;
const number=(key,value,paint,options={})=>numbers.set(key,value,paint,{snap:snapNumbers,...options});
const instructionUpdater=new InstructionUpdater({
  load:async()=>{
    const response=await fetch('/static/engineer-personality.json',{cache:'no-store'});
    if(!response.ok)throw new Error('The engineer personality could not be loaded.');
    return response.json();
  },
  append:async instruction=>{
    const id=send('session.instructions.append',instruction);
    if(!id)throw new Error('The radio disconnected while applying the personality.');
    await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>{instructionWaiters.delete(id);reject(new Error('The engineer did not confirm the personality. Try reconnecting.'));},6000);
      instructionWaiters.set(id,{resolve:()=>{clearTimeout(timer);resolve();},reject:error=>{clearTimeout(timer);reject(error);}});
    });
  },
  onReady:value=>{voiceStyleReady=value;}
});
const audioOutput=new EngineerAudio($('engineer-audio'),localStorage.getItem('apex-volume-v2')??120);
let voiceInput='',lastInputAt=0,volumeTimer=null;
$('verbosity').value = verbosity;
const savedVoice=localStorage.getItem('apex-voice') || 'cedar';
$('voice').value = [...$('voice').options].some(option=>option.value===savedVoice)?savedVoice:'cedar';

function notice(text = '') { $('notice').textContent = text; $('notice').hidden = !text; }
async function post(path, body = {}) {
  const response = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json','X-Coach-Token':token},body:JSON.stringify(body)});
  const result = await response.json();
  if (!response.ok) throw new Error(typeof result.detail === 'string' ? result.detail : `Request failed (${response.status})`);
  return result;
}
function send(type, content, delegationId = null) {
  if (ready && channel?.readyState === 'open' && !closing) {
    const id=crypto.randomUUID();
    channel.send(JSON.stringify({type, event_id:id, delegation_id:delegationId, content}));
    return id;
  }
}
async function applyVoiceStyle(force=false) {
  if(ready && !closing)await instructionUpdater.apply(force);
}
function context(forQuestion=false) {
  if (!state) return 'Ready when the driver is. No driving session is established; do not assume racing.';
  const t=state.telemetry,a=state.analysis,r=state.race,p=state.profile;
  if(t.status!=='live')return `${sessionAwareness.context()} Driving is on hold. Wait quietly, or briefly say ready when you are if asked. Do not read frozen driving figures or announce a technical fault. Voice volume ${audioOutput.percent}%; ${audioOutput.muted?'muted':'unmuted'}.`;
  const recent=forQuestion ? state.events.find(e=>['overtake','position','position_lost','incident','shift','clean_exit'].includes(e.kind)) : null;
  return [
    forQuestion ? 'Reference for the current driver question; answer only what was asked.' : 'Silent background reference, not a speaking cue. Do not announce race order or nearby drivers from these updates. Race calls need a fresh pass/lost-position commentary cue or a driver question.',
    sessionAwareness.context(),
    `Driver workload: ${t.brake>.08 || Math.abs(t.steer)>.08 ? 'braking or turning; keep replies short and focused in your usual engineer style' : 'low brake and steering inputs; brief banter may fit a reply, not an extra call'}.`,
    `Simulator source ${t.source}; status ${t.status}. Car ${t.car}; track ${t.track}.`,
    `Lap ${t.lap+1}, game sector ${t.sector+1}, ${Math.round(t.progress*100)}% around lap. ${Math.round(t.speed)} km/h, gear ${t.gear}, ${t.rpm} RPM; reported ceiling ${t.rpm_limit_known?t.max_rpm:'unknown'}. Fuel ${t.fuel.toFixed(1)} L.`,
    `Lap time ${time(t.lap_ms)}; reference delta ${diff(a.delta_ms)} s. Balance estimate: ${a.grip}.`,
    r?`Race position ${r.position??'unknown'}/${r.car_count??'unknown'}, flag ${r.flag}; ${r.overtakes} passes detected; ${r.positions_lost??0} positions lost; ${r.incident_count} incidents. Roster: ${r.opponents_available?'connected':r.roster_status||'unavailable'}.`:'Race facts unavailable.',
    forQuestion?`Reported session time remaining ${t.session_time_left>0?t.session_time_left+' seconds':'unknown'}; scheduled laps ${t.session_total_laps>0?t.session_total_laps:'unknown'}. This is not a start countdown.`:'',
    p?`Profile ${p.laps} observed laps; track section ${p.current_section}/20. This lap ${p.current_lap.high_rev_seconds}s near ceiling, ${p.current_lap.missed_shifts} possible missed shifts. ${p.last_lap?.encouragement||''}`:'Driving profile not available.',
    p?.hotspots[0]?`Recurring pattern: section ${p.hotspots[0].section}, high revs on ${p.hotspots[0].high_rev_laps} laps, missed-shift estimates on ${p.hotspots[0].missed_shift_laps} laps.`:'',
    recent?`Last coaching observation at ${recent.time}: ${recent.text.slice(0,170)}`:'',
    `Voice volume ${audioOutput.percent}%; ${audioOutput.muted?'muted':'unmuted'}.`
  ].join(' ');
}
function cornerContext() {
  const c=state?.analysis.corner;
  if(state?.telemetry.status!=='live' || !c)return 'Live turn assessment unavailable.';
  return [
    `Turn model: ${c.learned_turns} estimated regions on the driven reference line, without official corner names.`,
    c.current?`Position: ${c.current.label}, ${c.phase}.`:'Between learned turn regions.',
    c.next_turn?`Next: ${c.next_turn.label}, approximate distance ${c.next_turn.distance??'unknown'} metres.`:'',
    c.last_result?`Last assessed turn: ${c.last_result.label}, lap ${c.last_result.lap}; ${c.last_result.clean?'clean observed exit':c.last_result.outcome}.`:'No exit assessed yet.',
    `This lap: ${c.lap_counts.clean_exits} clean exits confirmed from observations.`
  ].join(' ');
}
function render(s) {
  state = s; mode = s.mode || s.telemetry.source;
  const t = s.telemetry, a = s.analysis, live = t.status === 'live';
  const identity=`${s.session_id}|${mode}|${t.track}|${t.car}`;
  if(identity!==numberSession)numbers.reset();
  snapNumbers=identity!==numberSession || t.status!==numberStatus || !live;
  const lapChanged=numberLap!==t.lap;
  numberSession=identity;numberLap=t.lap;numberStatus=t.status;
  const race=s.race;
  const sessionCue=sessionAwareness.observe(s,Date.now());
  const profile=s.profile;
  $('map-label').textContent=live && a.corner?.current?`${a.corner.current.label.toUpperCase()} · ${a.corner.phase.toUpperCase()}`:a.corner?.learned_turns?`LEARNED MAP · ${a.corner.learned_turns} TURNS`:'LEARNED MAP';
  $('profile-laps').textContent=profile?`${profile.laps} LAPS / ${profile.clean_laps} CLEAN`:'BUILDING';
  $('profile-location').textContent=profile && live?`Track section ${profile.current_section}/20 · ${profile.section_start_percent}–${profile.section_end_percent}% of the lap`:'Waiting for live track positioning';
  $('profile-shifting').textContent=profile?`This lap: ${profile.current_lap.high_rev_seconds.toFixed(1)}s near the RPM ceiling · ${profile.current_lap.late_shifts} high-rev holds · ${profile.current_lap.missed_shifts} possible missed shifts.`:'Rev and shift habits appear as you drive.';
  $('profile-encouragement').textContent=profile?.last_lap?.encouragement || (profile?.consistency_ms!=null?`Your last ${profile.consistency_laps} clean laps vary by ${profile.consistency_ms/1000}s (standard deviation).`:'Complete observed laps to build a profile for this car and layout.');
  $('profile-patterns').innerHTML=(profile?.hotspots||[]).map(h=>`<div class="profile-pattern"><strong>Section ${h.section} · ${(h.section-1)*5}–${h.section*5}% of lap</strong><span>${h.high_rev_laps} laps with high-rev holds · ${h.missed_shift_laps} laps with possible missed shifts · ${h.understeer_seconds.toFixed(1)}s front-slip estimate · ${h.oversteer_seconds.toFixed(1)}s rear-slip estimate</span></div>`).join('');
  $('race-session').textContent=race?.session?.toUpperCase() || 'AWAITING SESSION';
  $('race-position').textContent=race?.position ? `P${race.position}` : '—';
  $('race-field').textContent=`FIELD ${race?.car_count || '—'}`;
  $('race-passes').textContent=race?.overtakes ?? 0;
  $('race-opponents').textContent=race?.opponents_available ? 'Roster connected' : 'Roster unavailable';
  $('race-opponents').title=race?.roster_status||'Roster unavailable';
  renderRoster(race,live);
  $('race-incidents').textContent=race?.incident_count ?? 0;
  $('race-flag').textContent=`FLAG ${race?.flag?.toUpperCase() || '—'}`;
  const lastIncident=race?.recent_incidents?.[0];
  $('race-incident').textContent=!live ? 'Incident detection waits for live driving telemetry.' : lastIncident ? `Lap ${lastIncident.lap}: ${lastIncident.evidence}. ${lastIncident.assessment}.` : 'No new damage or spin detected in observed telemetry.';
  if(feedStatus !== t.status) {
    feedStatus=t.status;
    send('session.thinking.append',sessionAwareness.context());
  }
  $('demo-label').hidden = mode !== 'demo';
  $('connection').className = `status ${live ? 'live' : ''}`;
  $('connection').innerHTML = `<i></i>${mode === 'demo' ? 'DEMO FEED' : ({live:'AC CONNECTED',waiting:'WAITING FOR AC',paused:'AC PAUSED',replay:'AC REPLAY',disconnected:'AC DISCONNECTED'}[t.status] || 'WAITING')}`;
  $('session-state').textContent = mode === 'demo' ? 'DEMO SESSION' : live ? 'LIVE SESSION' : t.status.toUpperCase();
  $('track').textContent = t.status === 'waiting' ? 'Waiting for AC' : pretty(t.track);
  $('car').textContent = t.status === 'waiting' ? 'Launch a driving session to connect your engineer.' : (t.driver?`${t.driver} · `:'')+pretty(t.car_display_name||t.car) + (t.configuration ? ` / ${pretty(t.configuration)}` : '');
  $('lap-label').textContent = `LAP ${t.lap + 1} / S${t.sector + 1}`;
  number('lap-time',t.lap_ms,value=>{
    const formatted=time(Math.round(value)).split('.');
    $('lap-time').innerHTML=`${formatted[0]}<span>.${formatted[1]}</span>`;
  },{snap:snapNumbers || lapChanged});
  number('delta',a.delta_ms,value=>{
    $('delta').textContent=diff(value);
    $('delta').className=`delta ${value==null?'':value<=0?'good':'bad'}`;
  });
  $('best-time').textContent = a.reference_ms ? time(a.reference_ms) : 'Learning first lap';
  $('lap-validity').textContent = !live ? 'Awaiting live running' : a.clean ? 'No incidents observed' : 'Lap excluded from reference';
  number('progress',t.progress*100,value=>{
    $('lap-progress').style.width=`${value}%`;
    $('map-percent').textContent=`${Math.round(value)}% LAP`;
  },{snap:snapNumbers || lapChanged});
  $('sectors').style.gridTemplateColumns = `repeat(${t.sector_count},1fr)`;
  $('sectors').innerHTML = Array.from({length:t.sector_count}, (_,i) => {
    const actual = a.sectors?.[i], ref = a.reference_sectors?.[i];
    return `<div class="sector"><span>${i === t.sector ? '● ' : ''}SECTOR ${i+1}</span><strong class="${actual && ref ? actual <= ref ? 'good' : 'bad' : ''}">${actual ? time(actual) : i === t.sector && live ? 'RUNNING' : '—'}</strong><span>${actual && ref ? diff(actual-ref)+' SEC' : ref ? 'REF '+time(ref) : 'BUILDING REFERENCE'}</span></div>`;
  }).join('');
  number('speed',t.speed,value=>$('speed').innerHTML=`${Math.round(value)}<small>KM/H</small>`);
  number('speed-reference',a.speed_delta,value=>$('speed-reference').textContent=value==null?'REF —':`${value>=0?'+':''}${value.toFixed(1)} VS REF`);
  $('gear').textContent = t.gear === -1 ? 'R' : t.gear === 0 ? 'N' : t.gear;
  number('rpm',t.rpm,value=>$('rpm').innerHTML=`${Math.round(value).toLocaleString()}<small>RPM</small>`);
  number('fuel',t.fuel,value=>$('fuel').innerHTML=`${value.toFixed(1)}<small>L</small>`);
  for (const input of ['throttle','brake']) {
    number(input,Math.max(0,Math.min(1,t[input]))*100,value=>{
      $(input).textContent=`${Math.round(value)}%`;$(input+'-bar').style.width=`${value}%`;
    });
  }
  number('steer',t.steer,value=>{
    $('steer').textContent=value.toFixed(2);
    $('steer-bar').style.left=`${50+Math.max(-1,Math.min(1,value))*48}%`;
  });
  $('balance').textContent = a.grip || 'No live analysis';
  $('balance-dot').style.background = a.grip?.includes('slip') ? 'var(--red)' : 'var(--lime)';
  t.temperatures.forEach((temp,i)=>number(`tyre-${i}`,temp||null,value=>{
    tyreValues[i]=value;
    $('tyres').textContent=tyreValues.map((v,j)=>`${['FL','FR','RL','RR'][j]} ${v==null?'—':Math.round(v)}`).join('  /  ');
  }));
  $('demo-toggle').textContent = mode === 'demo' ? 'Connect to AC ↗' : 'Try demo ↗';
  $('footer-status').textContent = mode === 'demo' ? 'Fictional circuit · simulated data' : 'Shared memory · original Assetto Corsa';
  renderMap(s);
  const zone = a.next_zone;
  $('next-corner').textContent = zone ? zone.label : a.reference_ready ? 'Waiting for a braking zone' : 'Track map pending';
  $('next-note').textContent = zone ? 'Approximate distance from your reference lap.' : 'Braking cues begin after a clean reference lap.';
  number('corner-distance',zone?.distance,value=>$('corner-distance').innerHTML=`${value==null?'—':Math.round(value)}<small>METRES</small>`,{snap:snapNumbers || zone?.p!==numberZone});
  numberZone=zone?.p;
  $('event-count').textContent = `${s.events.length} NOTES`;
  if (s.events[0]?.id !== lastEvent) {
    lastEvent = s.events[0]?.id || '';
    if (s.events.length) $('events').innerHTML = groupNotes(s.events).map(e=>`<div class="event"><i></i><div><span class="event-label">${esc(pretty(e.kind))}${e.observations>1?` · ${e.observations} observations`:''}<time>${esc(e.time)}</time></span><p>${esc(e.text)}</p></div></div>`).join('');
  }
  if (!s.events.length) $('events').innerHTML = '<div class="empty-state">The radio is quiet.<br><span>Coaching notes appear as you drive.</span></div>';
  if (!ready && s.events[0]) $('coach-caption').textContent = `“${s.events[0].text}”`;
  if (s.laps.length) {
    const lap = s.laps[0];
    $('summary').innerHTML = `<div class="summary-content"><div class="summary-time">${time(lap.time_ms)}<span>${lap.best ? 'SESSION BEST' : `LAP ${lap.lap}`}</span></div><p>${esc(lap.summary)}</p></div>`;
    $('lap-history').innerHTML = s.laps.map(l=>`<tr><td>${l.lap}${l.best?' ★':''}</td><td>${time(l.time_ms)}</td><td class="${l.delta_ms == null ? '' : l.delta_ms <= 0 ? 'good':'bad'}">${diff(l.delta_ms)}</td><td>${l.max_speed} km/h</td><td>${l.partial ? 'Partial' : l.clean ? 'Clean observed' : 'Excluded'}</td></tr>`).join('');
  } else {
    $('summary').innerHTML = '<div class="empty-state">No completed laps.</div>';
    $('lap-history').innerHTML = '<tr><td colspan="5" class="muted">Complete a lap to begin your session history.</td></tr>';
  }
  for (const event of [...s.events].reverse()) {
    if (!seen.has(event.id)) {
      seen.add(event.id);
      if (!initial && live && ready && voiceStyleReady) radio.enqueue(event,Date.now(),verbosity==='quiet');
    }
  }
  initial = false;
  if (seen.size > 500) seen = new Set(s.events.map(e=>e.id));
  if(sessionCue && ready && voiceStyleReady)radio.enqueue(sessionCue,Date.now(),verbosity==='quiet');
  const radioTelemetry=sessionAwareness.current?.driving_allowed?t:{...t,status:'waiting'};
  const cue=ready && voiceStyleReady ? radio.next(radioTelemetry,Date.now(),sessionAwareness.current?.phase,race) : null;
  if (ready && (cue || Date.now()-lastContext > 3000)) {
    lastContext=Date.now(); send('session.thinking.append',context());
    send('session.thinking.append',cornerContext());
  }
  if(cue)send('session.commentary.append',cue);
}
function renderRoster(race,live) {
  const available=live && race?.opponents_available;
  const rows=available?(race.roster||[]):[];
  $('roster-status').textContent=available?`${rows.length} DRIVERS`:'ROSTER UNAVAILABLE';
  $('roster-count').textContent=rows.length;
  $('roster-help').hidden=!live || Boolean(available);
  $('roster-help').textContent=race?.roster_status||'Waiting for Apex Bridge in AC.';
  for(const relation of ['ahead','behind']) {
    const other=available?race[relation]:null;
    const boundary=available && race.position>0 && (relation==='ahead'?race.position===1:race.position===race.car_count);
    $('driver-'+relation).textContent=other?`P${other.position} · ${other.name||'Unknown driver'}`:boundary?'—':available?'Unknown':'Waiting for roster';
    $('car-'+relation).textContent=other?(other.car_name||other.car||'Car unavailable'):
      boundary?(relation==='ahead'?'You lead the standings':'Last in the standings'):'Driver and car unavailable';
  }
  $('race-roster').innerHTML=rows.length?rows.map(other=>`<div class="roster-row ${other.id===0?'player':''}"><span class="roster-rank">${other.position?`P${other.position}`:'—'}</span><div class="roster-driver">${esc(other.name||'Unknown driver')}<span class="roster-car">${esc(other.car_name||other.car||'Car unavailable')}</span></div><span class="roster-tag">${other.id===0?'YOU':other.in_pit?'PIT':''}</span></div>`).join(''):`<p class="muted small">${esc(race?.roster_status||'Enable Apex Bridge in AC to see the live field.')}</p>`;
}
function renderMap(s) {
  const points = s.map, t=s.telemetry;
  const useful = points.length > 4 && new Set(points.map(p=>`${Math.round(p.x)},${Math.round(p.z)}`)).size > 3;
  $('map-empty').hidden = useful;
  for (const id of ['map-line','map-shadow','map-driven','car-dot','car-glow','zone-dot','profile-markers']) $(id).style.display = useful ? '' : 'none';
  if (!useful) return;
  const xs=points.map(p=>p.x), zs=points.map(p=>p.z);
  const minX=Math.min(...xs),minZ=Math.min(...zs), w=Math.max(...xs)-minX,h=Math.max(...zs)-minZ;
  const scale=Math.min(500/Math.max(1,w),235/Math.max(1,h));
  const xy=p=>[50+(500-w*scale)/2+(p.x-minX)*scale,24+(235-h*scale)/2+(p.z-minZ)*scale];
  const path=ps=>ps.map((p,i)=>`${i?'L':'M'}${xy(p).map(n=>n.toFixed(1)).join(',')}`).join(' ');
  const line=path(points)+(s.analysis.reference_ready?' Z':'');
  $('map-line').setAttribute('d',line); $('map-shadow').setAttribute('d',line);
  $('map-driven').setAttribute('d',path(points.filter(p=>p.p <= t.progress)));
  for(const id of ['car-dot','car-glow']) { const [x,y]=xy(t); $(id).setAttribute('cx',x); $(id).setAttribute('cy',y); }
  const zone=s.analysis.next_zone;
  $('zone-dot').style.display=zone?'':'none';
  if(zone) { const point=points.reduce((best,p)=>Math.abs(p.p-zone.p)<Math.abs(best.p-zone.p)?p:best); const [x,y]=xy(point); $('zone-dot').setAttribute('cx',x);$('zone-dot').setAttribute('cy',y); }
  $('profile-markers').innerHTML=(s.profile?.hotspots||[]).map(h=>{const point=points.reduce((best,p)=>Math.abs(p.p-h.progress)<Math.abs(best.p-h.progress)?p:best);const [x,y]=xy(point);return `<circle cx="${x}" cy="${y}" r="5"><title>Driving pattern: section ${h.section}</title></circle>`;}).join('');
}

const stream = new EventSource('/api/events');
stream.onmessage = e => { render(JSON.parse(e.data)); if($('notice').dataset.feedError) { notice(); delete $('notice').dataset.feedError; } };
stream.onerror = () => { notice('Telemetry connection interrupted. Reconnecting…'); $('notice').dataset.feedError='1'; $('connection').textContent='APP DISCONNECTED'; $('connection').className='status'; if(state){state.telemetry.status='disconnected';sessionAwareness.observe(state,Date.now());} send('session.thinking.append','Driving is on hold. Do not give current driving calls. Wait quietly; if asked, say ready when you are without announcing a technical fault.'); };

async function refreshConfig() {
  const config = await (await fetch('/api/config')).json();
  $('key-state').textContent = config.key_configured ? 'API key configured. Leave blank to keep it. The app never returns the key to this page.' : 'No API key configured. Your key stays in local process memory.';
  return config;
}
$('settings-open').onclick = () => { refreshConfig().catch(e=>notice(e.message)); $('settings').showModal(); };
$('settings-close').onclick = () => $('settings').close();
$('settings-form').onsubmit = async e => {
  e.preventDefault();
  try {
    if($('api-key').value.trim()) await post('/api/key',{api_key:$('api-key').value.trim()});
    $('api-key').value=''; verbosity=$('verbosity').value;
    localStorage.setItem('apex-verbosity',verbosity); localStorage.setItem('apex-voice',$('voice').value);
    if(ready)await applyVoiceStyle(true);
    $('settings').close(); notice();
  } catch(error) { notice(error.message); }
};
$('demo-toggle').onclick = async () => {
  try {
    if(peer || sessionId) await disconnect();
    await post('/api/mode',{mode:mode==='demo'?'ac':'demo'}); seen.clear(); initial=true; lastEvent=''; notice();
  } catch(e) { notice(e.message); }
};
let pinned=true;
$('pin').onclick=async()=>{
  if(!window.pywebview) {notice('Always-on-top is available in the dedicated desktop window. Launch with Launch Apex.cmd.');return;}
  pinned=!pinned;await window.pywebview.api.set_pinned(pinned);$('pin').setAttribute('aria-pressed',pinned);$('pin').style.color=pinned?'var(--lime)':'';
};
function updateVolume(value=audioOutput.percent) {
  const percent=audioOutput.setPercent(value);localStorage.setItem('apex-volume-v2',percent);
  $('volume').value=percent;$('volume-value').textContent=`${percent}%`;
  $('speaker-mute').textContent=audioOutput.muted?'Unmute voice':'Mute voice';
  $('speaker-mute').setAttribute('aria-pressed',audioOutput.muted);
}
$('volume').oninput=()=>updateVolume($('volume').value);
$('volume-down').onclick=()=>updateVolume(audioOutput.percent-10);
$('volume-up').onclick=()=>updateVolume(audioOutput.percent+10);
$('speaker-mute').onclick=()=>{audioOutput.setMuted(!audioOutput.muted);updateVolume();};
updateVolume();
document.addEventListener('keydown',event=>{
  if(event.ctrlKey && event.shiftKey && ['ArrowUp','ArrowDown'].includes(event.key)) {
    event.preventDefault();updateVolume(audioOutput.percent+(event.key==='ArrowUp'?10:-10));
  }
});
function handleVolumeSpeech(delta) {
  const now=Date.now();if(now-lastInputAt>2500)voiceInput='';lastInputAt=now;
  voiceInput=(voiceInput+delta).slice(-300);clearTimeout(volumeTimer);
  volumeTimer=setTimeout(()=>{
    const command=volumeCommand(voiceInput);if(!command)return;voiceInput='';
    if(command.type==='set')updateVolume(command.value);
    if(command.type==='step')updateVolume(audioOutput.percent+command.value);
    if(command.type==='mute'||command.type==='unmute') {audioOutput.setMuted(command.type==='mute');updateVolume();}
    send('session.thinking.append',`Local voice playback control completed: volume ${audioOutput.percent} percent; ${audioOutput.muted?'speaker muted':'speaker unmuted'}. Microphone state did not change.`);
  },1000);
}
$('mic-toggle').onclick=()=>{
  muted=!muted; microphone?.getAudioTracks().forEach(t=>t.enabled=!muted);
  $('mic-toggle').textContent=muted?'Mic muted':'Mic on';$('mic-toggle').setAttribute('aria-pressed',muted);
};

function cleanup() {
  clearTimeout(volumeTimer);voiceInput='';audioOutput.detach();
  voiceStyleReady=false;instructionUpdater.reset();radio.reset();
  for(const waiter of instructionWaiters.values())waiter.reject(new Error('Voice connection ended.'));
  instructionWaiters.clear();
  ready=false; microphone?.getTracks().forEach(t=>t.stop());microphone=null;
  channel?.close();channel=null;peer?.close();peer=null;
  $('engineer-audio').srcObject=null;$('mic-toggle').disabled=true;
  $('voice-toggle').textContent=sessionId?'Retry disconnect':'◉  Connect engineer';
  $('voice-badge').textContent='ENGINEER OFFLINE';document.querySelector('.engineer-panel').classList.remove('connected');
}
async function disconnect() {
  closing=true;
  try {
    if(channel?.readyState==='open' && ready && !finalized) {
      const confirmed=new Promise(resolve=>{closeResolve=resolve;});
      channel.send(JSON.stringify({type:'session.close',event_id:crypto.randomUUID()}));
      await Promise.race([confirmed,new Promise(resolve=>setTimeout(resolve,5000))]);
    }
    if(sessionId) await post(`/api/live/close/${encodeURIComponent(sessionId)}`,{confirmed:finalized});
    sessionId=null;
    $('voice-status').textContent='Engineer disconnected. Voice session ended.';
  } finally {cleanup();closing=false;closeResolve=null;}
}
async function connect() {
  const boostReady=await audioOutput.activate();
  if (!(await refreshConfig()).key_configured) { $('settings').showModal(); return; }
  notice(); $('voice-status').textContent='Requesting microphone and connecting…';
  try {
    finalized=false;peer=new RTCPeerConnection();
    peer.ontrack=e=>{audioOutput.attach(new MediaStream([e.track])).catch(()=>notice('Audio playback is blocked. Reconnect the engineer or allow audio playback.'));if(!boostReady && audioOutput.percent>100)notice('Audio boost is unavailable in this browser; playback is capped at 100%.');};
    microphone=await navigator.mediaDevices.getUserMedia({audio:{echoCancellation:true,noiseSuppression:true}});
    microphone.getTracks().forEach(t=>peer.addTrack(t,microphone));
    muted=false;$('mic-toggle').textContent='Mic on';$('mic-toggle').setAttribute('aria-pressed','false');
    channel=peer.createDataChannel('oai-events');
    const started=new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('The voice session did not start in time.')),35000);
      channel.onmessage=async({data})=>{
        const event=JSON.parse(data);
        if(event.type==='session.started') {ready=true;clearTimeout(timer);resolve();}
        if(event.type==='session.instructions.appended') {instructionWaiters.get(event.client_event_id)?.resolve();instructionWaiters.delete(event.client_event_id);}
        if(event.type==='session.closed') {finalized=true;closeResolve?.();$('voice-status').textContent=`Session ended · ${Math.round(event.usage?.seconds||0)} seconds.`;if(!closing) disconnect().catch(e=>notice(e.message));}
        if(event.type==='session.output_transcript.delta') {
          radio.heardEngineer(Date.now());
          const now=Date.now();transcript=now-lastTranscript>2200?'':transcript;lastTranscript=now;
          transcript=(transcript+event.delta).slice(-500);$('coach-caption').textContent=transcript;
        }
        if(event.type==='session.input_transcript.delta'){radio.heardUser(Date.now());handleVolumeSpeech(event.delta);}
        if(event.type==='session.delegation.created') {
          rosterContext(state?.telemetry.status==='live'?state.race:null,true).forEach(part=>send('session.thinking.append',part));
          send('session.thinking.append',cornerContext());
          send('session.commentary.append',`Fresh reference for the driver's question: ${context(true)}. Keep your usual calm, dry-witted engineer style and stay concise. Answer only an in-scope driving, racing, car, simulator or control question. If the request is unrelated, give one lightly amused redirect to driving, without answering it. No field rundown or continuing nearby-driver updates. Missing race facts remain unknown.`,event.delegation.id);
        }
        if(event.type==='error') {const id=event.client_event_id || event.error?.event_id;if(instructionWaiters.has(id)){instructionWaiters.get(id).reject(new Error(event.error?.message||'Voice style rejected.'));instructionWaiters.delete(id);}notice(event.error?.message || 'The voice connection reported an error.');if(!ready){clearTimeout(timer);reject(new Error(event.error?.message || 'Voice session failed.'));}}
      };
      channel.onclose=()=>{if(!closing && peer){notice('Voice channel closed. Reconnect the engineer.');disconnect().catch(e=>notice(e.message));}};
    });
    // Attach rejection handling before the network request can outlast the timer.
    started.catch(()=>{});
    const offer=await peer.createOffer();await peer.setLocalDescription(offer);
    if(peer.iceGatheringState!=='complete') await new Promise((resolve,reject)=>{
      const timer=setTimeout(()=>reject(new Error('Audio network discovery timed out.')),10000);
      const check=()=>{if(peer?.iceGatheringState==='complete'){clearTimeout(timer);peer.removeEventListener('icegatheringstatechange',check);resolve();}};
      peer.addEventListener('icegatheringstatechange',check);check();
    });
    const result=await post('/api/live/session',{sdp:peer.localDescription.sdp,voice:$('voice').value});
    sessionId=result.session.id;
    await peer.setRemoteDescription({type:'answer',sdp:result.transport.sdp});await started;
    lastContext=0;transcript='';
    radio.reset();await applyVoiceStyle(true);
    sessionAwareness.prime(state);
    send('session.thinking.append',context());
    send('session.commentary.append',`${mode==='demo'?'This is a simulated demo session. ':''}${sessionAwareness.greeting()}`);
    radio.heardEngineer(Date.now());
    $('voice-toggle').textContent='Disconnect engineer';$('mic-toggle').disabled=false;
    $('voice-badge').textContent='RADIO CONNECTED';$('voice-status').textContent='Live · Microphone on · GPT-Live 1';
    document.querySelector('.engineer-panel').classList.add('connected');
  } catch(error) {
    await disconnect().catch(()=>{});throw error;
  }
}
$('voice-toggle').onclick=async()=>{
  if(busy)return;busy=true;document.body.dataset.radioBusy='true';$('voice-toggle').disabled=true;
  try { if(peer || sessionId) await disconnect();else await connect(); }
  catch(error){notice(error.message);$('voice-status').textContent='Voice connection needs attention.';}
  finally{busy=false;document.body.dataset.radioBusy='false';$('voice-toggle').disabled=false;}
};
window.addEventListener('beforeunload',()=>{
  if(channel?.readyState==='open')channel.send(JSON.stringify({type:'session.close',event_id:crypto.randomUUID()}));
  if(sessionId) fetch(`/api/live/close/${encodeURIComponent(sessionId)}`,{method:'POST',headers:{'Content-Type':'application/json','X-Coach-Token':token},body:JSON.stringify({confirmed:finalized}),keepalive:true}).catch(()=>{});
  microphone?.getTracks().forEach(t=>t.stop());
});
refreshConfig().catch(()=>{});
// Later personality edits can reach an active session without restarting it.
setInterval(()=>{if(ready && !closing)applyVoiceStyle().catch(e=>notice(e.message));},30000);
