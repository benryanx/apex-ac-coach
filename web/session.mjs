// Session awareness is inferred from AC status, lap clock and movement.
// The standard shared-memory prefix does not expose the start lights.
const inactive=new Set(['waiting','standby','paused','replay']);
const names={0:'practice',1:'qualifying',2:'race',3:'hotlap',4:'time attack',5:'drift',6:'drag'};

export class SessionAwareness {
  constructor() { this.reset(); }
  reset() {
    this.identity=null;this.lastLive=null;this.started=false;this.sawGrid=false;
    this.startAnnounced=false;this.standbyAnnounced=true;this.current=null;this.pending=null;
  }
  observe(state,now=Date.now()) {
    const t=state?.telemetry||{};
    if(t.status==='live') {
      const identity=JSON.stringify([state.session_id,t.source,t.car,t.track,t.configuration,t.session_type]);
      const restarted=this.lastLive && (t.lap<this.lastLive.lap ||
        (t.lap===this.lastLive.lap && t.lap_ms<this.lastLive.lap_ms-1500));
      if(identity!==this.identity || restarted) {
        this.started=false;this.sawGrid=false;this.startAnnounced=false;
        this.identity=identity;
      }
      if(t.session_type===2 && (t.lap>0 || (t.lap_ms>0 && t.speed>=5)))this.started=true;
      this.lastLive=t;
    }
    let phase;
    if(t.status!=='live')phase=({paused:'paused',replay:'replay',disconnected:'standby'})[t.status]||'waiting';
    else if(t.flag===5)phase='chequered';
    else if(t.in_pit)phase='pits';
    else if(t.session_type===2 && this.started)phase='racing';
    else if(t.session_type===2 && t.lap===0 && t.lap_ms<=0 && t.speed<5)phase='pre_start';
    else phase=t.speed>=5?'driving':'ready';
    const previous=this.current?.phase;
    this.current={phase,session:names[t.session_type]||'session',race_started:this.started,
      lights_known:false,driving_allowed:!inactive.has(phase) && phase!=='pre_start'};
    if(phase==='pre_start')this.sawGrid=true;
    if(phase!==previous) {
      this.pending=previous?{phase,since:now}:null;
    }
    if(!this.pending || now-this.pending.since<1200)return null;
    this.pending=null;
    let text=null;
    if(inactive.has(phase)) {
      if(!this.standbyAnnounced)text='Driving is on hold. Say only: Ready when you are. Do not mention telemetry, connection status or technical faults.';
      this.standbyAnnounced=true;
    } else {
      this.standbyAnnounced=false;
      if(phase==='pre_start')text='The race session is loaded, but the start is unconfirmed. Say only a short ready acknowledgment. Do not count down or call the lights.';
      else if(phase==='racing' && this.sawGrid && !this.startAnnounced && t.speed>=5) {
        this.startAnnounced=true;
        text='The car has moved away and the lap clock is running after the observed pre-start wait. Acknowledge that we are away in one short sentence. Do not call lights out or give a launch command.';
      }
    }
    return text?{kind:'session_stage',phase,text,speak:true}:null;
  }
  prime(state,now=Date.now()) {
    this.reset();this.observe(state,now);this.pending=null;
    this.standbyAnnounced=inactive.has(this.current.phase);
    this.startAnnounced=this.started;
  }
  context() {
    const s=this.current;
    if(!s)return 'Session stage not established. Wait for the driver; do not assume racing.';
    return `Session stage ${s.phase}; session type ${s.session}; race start ${s.race_started?'inferred from lap clock and movement':'not confirmed'}. Start lights and countdown unavailable. Stages are observations, not speaking cues. Inactive means ready when the driver is, not a technical-failure announcement.`;
  }
  greeting() {
    const phase=this.current?.phase;
    const detail=phase==='pre_start'
      ? 'The race session is loaded but its start is unconfirmed. End with ready when you are. Do not count down or call lights.'
      : inactive.has(phase) || !phase
        ? 'Driving is on hold or not loaded. End with ready when you are; do not discuss telemetry or technical status.'
        : 'The driver is already in a driving session. Say you will keep calls short; do not pretend a new race is starting.';
    return `Introduce yourself once as Apex, their race engineer, in your usual calm, friendly engineer voice. Use at most two short sentences. ${detail} No questions, roster, position recap or technical report.`;
  }
}
