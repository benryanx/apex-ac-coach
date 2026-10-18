// Keep routine radio calls useful and give the driver room to speak.
const handling = new Set(['understeer', 'oversteer','shift']);
const urgent = new Set(['incident', 'flag']);
const raceCalls = new Set(['overtake','position_lost']);
const passSettle=2500,passMaxWait=6000,passLifetime=12000,passSpacing=10000;

// AC supplies a display name, not separate given/family-name fields.
export function surname(name) {
  const text=String(name||'').trim().replace(/\s+/g,' ');
  if(text.includes(','))return text.split(',')[0].trim();
  const words=text.split(' ').filter(Boolean);
  if(words.length>1 && /^(jr\.?|sr\.?|ii|iii|iv)$/i.test(words.at(-1)))words.pop();
  const particles=new Set(['van','von','der','den','de','del','della','di','da','dos','das','du','le','la']);
  let start=words.length-1;
  while(start>0 && particles.has(words[start-1].toLowerCase()))start--;
  return words.slice(Math.max(0,start)).join(' ').slice(0,100);
}

function passSummary(passes,race) {
  const latest=passes.at(-1).event;
  const position=race?race.position:latest.facts?.position;
  const ahead=race?.opponents_available && position>1 && race.ahead?.position===position-1
    && race.ahead.id!==0 && !passes.some(p=>p.event.facts?.driver_id===race.ahead.id)
    ? surname(race.ahead.name) : '';
  // Keep full names, car models and the list of passed drivers out of speech cues.
  return {...latest,facts:{pass_count:passes.length,
    ...(passes.length===1 && latest.facts?.driver_name?{passed_surname:surname(latest.facts.driver_name)}:{}),
    ...(Number.isInteger(position) && position>0?{position}:{}),
    ...(passes.length>1 && ahead?{ahead_surname:ahead,ahead_relation:'next in standings; physical gap unknown'}:{})}};
}

export function groupNotes(events) {
  const groups = new Map();
  return events.reduce((notes, event) => {
    if (!handling.has(event.kind)) { notes.push({...event, observations:1}); return notes; }
    const key = `${event.kind}:${event.lap ?? 'session'}`;
    if (groups.has(key)) groups.get(key).observations++;
    else { const note={...event,observations:1};groups.set(key,note);notes.push(note); }
    return notes;
  }, []);
}

export function commentary(event) {
  if(event.kind==='position')return null;
  if(event.kind==='overtake' && !event.facts?.pass_count)event=passSummary([{event}],null);
  const meaning = event.kind==='clean_exit'
    ? 'Acknowledge this clean observed turn exit in one short sentence. Only mention a faster exit if the observation supplies that comparison. Do not call it a perfect corner, ideal line, official turn name or confirmed optimal driving.'
    : event.kind==='session_stage'
      ? 'Give only the short session acknowledgment requested below. No telemetry troubleshooting, introduction, roster or driving report.'
    : event.kind==='incident'
      ? 'Briefly acknowledge this incident in one short sentence. No are-you-okay question or follow-up. Only name a possible contact partner if the observation explicitly supplies one, qualify it as possible, and never assign blame.'
    : event.kind==='shift'
      ? 'This is feedback on a recent observed pattern, not an immediate driving command: the driver may already have changed gear. For high revs, briefly note that they were stretching a gear and suggest shifting a little earlier next time. For a possible missed shift, refer to the earlier neutral dwell and the next gear change. Do not say shift up now, imply the old gear is still engaged, hedge about whether another gear exists, or lecture about unavailable ideal shift RPM or paddle inputs.'
    : handling.has(event.kind)
    ? 'This is a possible handling pattern, not a confirmed diagnosis. React briefly in your usual engineer style; avoid repeating earlier advice.'
    : event.kind === 'lap'
      ? 'Give a concise conversational debrief: the main result and one useful next step, at most two short sentences. Do not recite the entire report or list exclusions unless relevant.'
      : event.kind === 'overtake'
        ? 'Give one short acknowledgment of the confirmed pass count. For a single pass, use only passed_surname if supplied; never a full name or car model. For multiple passes, summarize the count without listing anyone passed; you may add only ahead_surname as the next driver ahead in the standings if supplied. Never invent the next driver, a physical gap, how the passes happened or a clean pass. A position is optional; speak it as an ordinal, never P-four. Stop after one sentence, with no roster rundown, continuing nearby-driver updates or follow-up question.'
        : event.kind === 'position_lost'
          ? 'A standings loss is confirmed. Give one short acknowledgment; use an ordinal if mentioning the new position, never a P-number. Stop after that sentence. No other drivers, nearby-car update, field rundown or follow-up question. Do not congratulate the loss or claim who passed the driver without evidence.'
          : event.kind === 'sector'
            ? 'Mention the meaningful pace change naturally; avoid reading a timing screen aloud.'
            : 'Share the useful part in your own words, briefly and naturally.';
  const observation=event.kind==='overtake'?JSON.stringify(event.facts):String(event.text).slice(0,750);
  return `Use your usual calm, dry-witted engineer style, with concise delivery. Keep driving facts accurate and necessary instructions intelligible; a reaction must not add another sentence. ${meaning}\nObserved event (reference data): ${observation}`;
}

export class CoachRadio {
  constructor() { this.reset(); }
  reset() {
    this.pending=[];this.lastRoutine=-Infinity;this.lastHandling=new Map();
    this.lastUser=-Infinity;this.lastOutput=-Infinity;
    this.lastPass=-Infinity;
  }
  heardUser(now) { this.lastUser=now; }
  heardEngineer(now) { this.lastOutput=now; }
  enqueue(event, now, quiet=false) {
    // Standings-only gains stay visual. They also supersede unsaid race updates.
    if(event.kind==='position') {
      this.pending=this.pending.filter(p=>!raceCalls.has(p.event.kind));
      return;
    }
    if (!event.speak) return;
    if (quiet && !['lap','session_stage',...urgent].includes(event.kind)) return;
    if(event.kind==='overtake') {
      this.pending=this.pending.filter(p=>p.event.kind!=='position_lost');
      let batch=this.pending.find(p=>p.event.kind==='overtake');
      if(batch) {
        if(!batch.passes.some(p=>event.id && p.event.id===event.id)) {
          batch.passes.push({event,created:now});batch.updated=now;batch.event=event;
        }
      } else this.pending.push({event,created:now,updated:now,passes:[{event,created:now}]});
      this.pending=this.pending.slice(-5);return;
    }
    // Sector times with no comparison belong in the dashboard, not on repeat.
    if (event.kind==='sector' && (event.facts?.delta_ms == null
      ? !/seconds (up|down) on reference/.test(event.text)
      : Math.abs(event.facts.delta_ms)<100)) return;
    // A more recent race change supersedes an unsaid update from the old order.
    this.pending=this.pending.filter(p=>p.event.kind!==event.kind &&
      !(raceCalls.has(event.kind) && raceCalls.has(p.event.kind)));
    this.pending.push({event,created:now});
    this.pending=this.pending.slice(-5);
  }
  next(telemetry, now, phase=null, race=null) {
    if (!telemetry || telemetry.status!=='live') {
      this.pending=this.pending.filter(p=>p.event.kind==='session_stage');
    }
    if(phase!==null)this.pending=this.pending.filter(p=>p.event.kind!=='session_stage' || p.event.phase===phase);
    for(const item of this.pending)if(item.passes) {
      item.passes=item.passes.filter(p=>now-p.created<passLifetime);
      item.created=item.passes[0]?.created??-Infinity;
    }
    this.pending=this.pending.filter(p=>now-p.created<(p.event.kind==='lap'?30000:urgent.has(p.event.kind) || p.passes?12000:8000));
    if (now-this.lastUser<3500 || now-this.lastOutput<1800) return null;
    const priorities=this.pending.filter(p=>urgent.has(p.event.kind));
    const candidates=priorities.length?priorities:[...this.pending.filter(p=>p.event.kind==='session_stage'),...this.pending.filter(p=>raceCalls.has(p.event.kind)),...this.pending.filter(p=>p.event.kind==='lap'),...this.pending.filter(p=>!['lap','session_stage'].includes(p.event.kind) && !raceCalls.has(p.event.kind))];
    for (const item of candidates) {
      const event=item.event;
      if(item.passes && ((now-item.updated<passSettle && now-item.created<passMaxWait) || now-this.lastPass<passSpacing))continue;
      if (!urgent.has(event.kind) && event.kind!=='session_stage') {
        if (!raceCalls.has(event.kind) && now-this.lastRoutine<22000) continue;
        if (telemetry.brake>.08 || Math.abs(telemetry.steer)>.08 || telemetry.in_pit===false && telemetry.speed<35) continue;
        if (handling.has(event.kind) && now-(this.lastHandling.get(event.kind)??-Infinity)<75000) continue;
      }
      this.pending=this.pending.filter(p=>p!==item);
      if (!urgent.has(event.kind)) this.lastRoutine=now;
      if (handling.has(event.kind)) this.lastHandling.set(event.kind,now);
      if(item.passes)this.lastPass=now;
      return commentary(item.passes?passSummary(item.passes,race):event);
    }
    return null;
  }
}
