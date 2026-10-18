"""Persistent habits and measured improvements for each car/track/layout."""
import hashlib
import json
import math
import statistics


def metrics():
    return {'observed_seconds':0.0,'high_rev_seconds':0.0,'understeer_seconds':0.0,'oversteer_seconds':0.0,
            'late_shifts':0,'missed_shifts':0,'passes':0,'positions_lost':0,'contacts':0,'spins':0}


class DrivingProfile:
    count=20

    def __init__(self,directory,identity):
        self.identity=list(identity)
        key=hashlib.sha256(json.dumps(identity).encode()).hexdigest()[:20]
        self.path=directory/'profiles'/(key+'.json')
        self.data={'version':1,'identity':self.identity,'laps':0,'clean_laps':0,
            'clean_times':[],'best_clean_ms':None,'last_lap':None,'sections':[{'section':i+1,'observed_laps':0,
            'high_rev_laps':0,'missed_shift_laps':0,'best_ms':None,'last_ms':None,
            **metrics()} for i in range(self.count)]}
        try:
            saved=json.loads(self.path.read_text(encoding='utf-8'))
            if saved['version']==1 and saved['identity']==self.identity and len(saved['sections'])==self.count:
                self.data=saved
        except (OSError,ValueError,KeyError,TypeError):pass
        self.reset_lap()

    def record_race_event(self,kind,s,position_change=0,incident_kind=None):
        section=self.current[self.section(s.progress)]
        if kind=='overtake':section['passes']+=1
        elif kind=='position_lost':section['positions_lost']+=abs(position_change)
        elif kind=='incident' and incident_kind=='damage_increase':section['contacts']+=1
        elif kind=='incident' and incident_kind=='possible_spin':section['spins']+=1

    def reset_lap(self):
        self.current=[metrics() for _ in range(self.count)]
        self.starts={};self.previous=None
        self.high_since=None;self.neutral_since=None
        self.high_reported=False;self.neutral_reported=False

    @staticmethod
    def section(progress):return min(19,max(0,int(progress*20)))

    def observe(self,s,grip=None):
        events=[];prev=self.previous;idx=self.section(s.progress)
        if s.status!='live' or s.in_pit:
            self.previous=None;self.high_since=None;self.neutral_since=None
            self.high_reported=False;self.neutral_reported=False
            return events
        continuous=prev is not None and 0<s.timestamp-prev.timestamp<=.6 and s.lap==prev.lap
        if continuous:
            dt=s.timestamp-prev.timestamp
            continuous=(math.hypot(s.x-prev.x,s.z-prev.z)<max(15,max(s.speed,prev.speed)/3.6*dt*3+5)
                and 0<=s.progress-prev.progress<=.025 and 0<=s.lap_ms-prev.lap_ms<=600)
        if s.progress<.002 and s.lap_ms<1500:self.starts.setdefault(0,0)
        if continuous:
            for boundary in range(self.section(prev.progress)+1,idx+1):
                fraction=(boundary/self.count-prev.progress)/max(1e-9,s.progress-prev.progress)
                self.starts[boundary]=prev.lap_ms+(s.lap_ms-prev.lap_ms)*fraction
        else:
            dt=0;self.high_since=None;self.neutral_since=None
            self.high_reported=False;self.neutral_reported=False
        ceiling=s.rpm_limit_known and s.max_rpm>1000
        self.current[idx]['observed_seconds']+=dt
        near_limit=ceiling and s.gear>0 and s.speed>45 and s.throttle>.65 and s.brake<.1 and s.rpm/s.max_rpm>=.96
        if near_limit:
            self.current[idx]['high_rev_seconds']+=dt
            if self.high_since is None:self.high_since=s.timestamp
            if s.timestamp-self.high_since>=.85 and not self.high_reported:
                self.high_reported=True;self.current[idx]['late_shifts']+=1
                events.append(('shift',f"You held gear {s.gear} near the rev limit. Try shifting a little earlier next time."))
        else:self.high_since=None;self.high_reported=False
        neutral=ceiling and s.gear==0 and s.speed>40 and s.throttle>.6 and s.rpm/s.max_rpm>.75
        if neutral:
            if self.neutral_since is None and prev and prev.gear>0 and continuous:self.neutral_since=s.timestamp
            if self.neutral_since is not None and s.timestamp-self.neutral_since>=.75 and not self.neutral_reported:
                self.neutral_reported=True;self.current[idx]['missed_shifts']+=1
                events.append(('shift',f"Possible missed shift in track section {idx+1}: neutral was held under throttle while moving. Make sure the gear engages on the next change."))
        else:self.neutral_since=None;self.neutral_reported=False
        if continuous and grip in ('understeer','oversteer'):self.current[idx][grip+'_seconds']+=dt
        self.previous=s
        return events

    def finish_lap(self,time_ms,complete,clean):
        if not complete:self.reset_lap();return None
        self.data['laps']+=1;self.starts[20]=time_ms
        improvements=[];total=metrics()
        for idx,current in enumerate(self.current):
            section=self.data['sections'][idx];section['observed_laps']+=int(current['observed_seconds']>.1)
            for key in total:section[key]+=current[key];total[key]+=current[key]
            section['high_rev_laps']+=int(current['high_rev_seconds']>=.85)
            section['missed_shift_laps']+=int(current['missed_shifts']>0)
            elapsed=self.starts.get(idx+1,0)-self.starts.get(idx,0)
            if clean and idx in self.starts and idx+1 in self.starts and elapsed>0:
                before=section['best_ms'];section['last_ms']=round(elapsed)
                if before is not None and before-elapsed>=100:
                    improvements.append({'section':idx+1,'gain_ms':round(before-elapsed)})
                if before is None or elapsed<before:section['best_ms']=round(elapsed)
        previous=self.data['last_lap'];encouragement=None
        if clean:
            old_best=self.data['best_clean_ms']
            if old_best is not None and old_best-time_ms>=100:
                encouragement=f"That's {((old_best-time_ms)/1000):.2f} seconds quicker than your previous best clean lap here."
            elif improvements:
                best=max(improvements,key=lambda v:v['gain_ms'])
                encouragement=f"Track section {best['section']} was {best['gain_ms']/1000:.2f} seconds quicker than your previous best through there."
            self.data['clean_laps']+=1
            if old_best is None or time_ms<old_best:self.data['best_clean_ms']=time_ms
            self.data['clean_times']=(self.data['clean_times']+[time_ms])[-50:]
        comparable=previous and total['observed_seconds']>=time_ms/1000*.8 and previous['observed_seconds']>=previous['time_ms']/1000*.8
        if not encouragement and comparable and previous['high_rev_seconds']-total['high_rev_seconds']>=1:
            saved=previous['high_rev_seconds']-total['high_rev_seconds']
            encouragement=f"You spent {saved:.1f} fewer seconds near the rev ceiling than the previous observed lap."
        report={**{k:round(v,2) for k,v in total.items()},'time_ms':time_ms,'clean':clean,
            'improvements':sorted(improvements,key=lambda v:-v['gain_ms'])[:3],'encouragement':encouragement}
        self.data['last_lap']=report
        self.path.parent.mkdir(parents=True,exist_ok=True)
        temp=self.path.with_suffix('.tmp');temp.write_text(json.dumps(self.data),encoding='utf-8');temp.replace(self.path)
        self.reset_lap()
        return report

    def snapshot(self,s):
        idx=self.section(s.progress);hotspots=[]
        for section in self.data['sections']:
            if section['high_rev_laps']>=2 or section['missed_shift_laps']>=2 or section['understeer_seconds']>=2 or section['oversteer_seconds']>=2:
                score=section['high_rev_laps']*3+section['missed_shift_laps']*4+section['understeer_seconds']+section['oversteer_seconds']
                hotspots.append({**section,'score':score,'progress':(section['section']-.5)/20})
        hotspots.sort(key=lambda v:-v['score']);recent=self.data['clean_times'][-5:]
        current={k:round(sum(section[k] for section in self.current),2) for k in metrics()}
        return {'laps':self.data['laps'],'clean_laps':self.data['clean_laps'],
            'current_section':idx+1,'section_count':20,'section_start_percent':idx*5,'section_end_percent':(idx+1)*5,
            'current_lap':current,'last_lap':self.data['last_lap'],'hotspots':hotspots[:5],
            'best_clean_ms':self.data['best_clean_ms'],
            'consistency_ms':round(statistics.pstdev(recent)) if len(recent)>=3 else None,
            'consistency_laps':len(recent),'shift_note':'Near reported RPM ceiling; ideal shift points and paddle inputs are unavailable.'}
