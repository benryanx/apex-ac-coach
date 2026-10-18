// Display-only interpolation. Telemetry, analysis and radio always keep raw values.
export class TelemetryNumbers {
  constructor({duration=180,now=()=>performance.now(),request=cb=>requestAnimationFrame(cb),cancel=id=>cancelAnimationFrame(id),reduced=()=>false}={}) {
    Object.assign(this,{duration,now,request,cancel,reduced});
    this.values=new Map();this.frame=null;
  }
  sample(item,now) {
    const p=Math.min(1,Math.max(0,(now-item.start)/this.duration));
    return item.from+(item.target-item.from)*p;
  }
  set(key,target,paint,{snap=false}={}) {
    const now=this.now(),old=this.values.get(key);
    if(!Number.isFinite(target)) {this.values.delete(key);paint(null);return;}
    if(old && target===old.target && !snap && !this.reduced()) {old.paint=paint;return;}
    const immediate=snap || this.reduced() || !old;
    const from=immediate?target:this.sample(old,now);
    const item={from,target,start:now,paint};
    this.values.set(key,item);paint(from);
    if(from!==target)this.schedule();
  }
  schedule() {if(this.frame===null)this.frame=this.request(()=>this.tick());}
  tick() {
    this.frame=null;const now=this.now();let active=false;
    for(const item of this.values.values()) {
      if(item.from===item.target)continue;
      const value=this.reduced()?item.target:this.sample(item,now);
      item.paint(value);
      if(value===item.target)item.from=item.target;else active=true;
    }
    if(active)this.schedule();
  }
  reset() {
    if(this.frame!==null)this.cancel(this.frame);
    this.frame=null;this.values.clear();
  }
}
