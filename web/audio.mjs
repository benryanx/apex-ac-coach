export const clampVolume=value=>Math.max(0,Math.min(200,Math.round(Number.isFinite(Number(value))?Number(value):120)));

export function volumeCommand(transcript) {
  const text=transcript.toLowerCase().replace(/[.,!?]/g,'').trim()
    .replace(/^(?:(?:hey )?apex\s+|please\s+|can you\s+|could you\s+|would you\s+)+/,'').replace(/\s+please$/,'');
  if(/microphone|\bmic\b/.test(text))return null;
  const set=text.match(/^(?:set|turn) (?:your |the )?(?:(?:voice|radio|engineer) )?volume (?:to |at )?(\d{1,3})\s*(?:percent|per cent|%)?$/);
  if(set)return {type:'set',value:clampVolume(set[1])};
  if(/^(?:unmute|unmute (?:yourself|your voice|the radio|the engineer))$/.test(text))return {type:'unmute'};
  if(/^(?:mute|mute (?:yourself|your voice|the radio|the engineer))$/.test(text))return {type:'mute'};
  if(/^(?:volume up|speak louder|a bit louder|louder|turn (?:your |the )?(?:voice |radio )?volume up|turn it up)(?: (?:a bit|a little))?$/.test(text))return {type:'step',value:10};
  if(/^(?:volume down|speak quieter|a bit quieter|quieter|turn (?:your |the )?(?:voice |radio )?volume down|turn it down)(?: (?:a bit|a little))?$/.test(text))return {type:'step',value:-10};
  return null;
}

export class EngineerAudio {
  constructor(element,percent=120,contextFactory=null) {
    this.element=element;this.percent=clampVolume(percent);this.muted=false;
    this.contextFactory=contextFactory || (()=>new (globalThis.AudioContext||globalThis.webkitAudioContext)());
    this.context=null;this.source=null;this.gain=null;
  }
  async activate() {
    try {
      if(!this.context) {
        this.context=this.contextFactory();this.gain=this.context.createGain();
        this.limiter=this.context.createDynamicsCompressor();
        this.limiter.threshold.value=-3;this.limiter.ratio.value=20;
        this.limiter.attack.value=.003;this.limiter.release.value=.15;
        this.gain.connect(this.limiter);this.limiter.connect(this.context.destination);
      }
      await this.context.resume();this.apply();
      return this.context.state==='running';
    } catch {return false;}
  }
  attach(stream) {
    this.detach();this.element.srcObject=stream;
    if(this.context?.state==='running' && this.gain) {
      this.source=this.context.createMediaStreamSource(stream);this.source.connect(this.gain);
    }
    this.apply();
    return this.element.play();
  }
  detach() {this.source?.disconnect();this.source=null;this.element.srcObject=null;}
  setPercent(value) {this.percent=clampVolume(value);this.apply();return this.percent;}
  setMuted(value) {this.muted=Boolean(value);this.apply();}
  apply() {
    if(this.gain)this.gain.gain.setTargetAtTime(this.muted?0:this.percent/100,this.context.currentTime,.02);
    // The media element stays muted on the Web Audio path to avoid double audio.
    this.element.muted=this.source?true:this.muted;
    this.element.volume=this.source?1:Math.min(1,this.percent/100);
  }
  get boosted() {return Boolean(this.source);}
}
