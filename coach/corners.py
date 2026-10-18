"""Learn turn regions from a driven reference line; assess observed exits.

These are geometric estimates, not official corner names or an ideal line.
"""
import bisect
import math


def learn_turns(samples):
    if len(samples)<30 or samples[0]['p']>.02 or samples[-1]['p']<.97:
        return []
    points=sorted(samples,key=lambda point:point['p'])
    progress=[point['p'] for point in points]
    n=400;line=[]
    for i in range(n):
        p=i/n;index=bisect.bisect_right(progress,p)
        a=points[index-1] if index else {**points[-1],'p':points[-1]['p']-1}
        b=points[index] if index<len(points) else {**points[0],'p':points[0]['p']+1}
        weight=(p-a['p'])/max(1e-8,b['p']-a['p'])
        line.append((a['x']+(b['x']-a['x'])*weight,a['z']+(b['z']-a['z'])*weight))
    smooth=[tuple(sum(line[(i+j)%n][axis] for j in range(-2,3))/5 for axis in (0,1)) for i in range(n)]
    bend=[]
    for i in range(n):
        a,b,c=smooth[(i-3)%n],smooth[i],smooth[(i+3)%n]
        incoming=(b[0]-a[0],b[1]-a[1]);outgoing=(c[0]-b[0],c[1]-b[1])
        if min(math.hypot(*incoming),math.hypot(*outgoing))<.5:
            bend.append(0);continue
        bend.append(math.atan2(incoming[0]*outgoing[1]-incoming[1]*outgoing[0],
                               incoming[0]*outgoing[0]+incoming[1]*outgoing[1]))
    signs=[(1 if value>0 else -1) if abs(value)>=.1 else 0 for value in bend]
    # Start after a break so a turn crossing the finish line stays one region.
    anchor=next((i for i in range(n) if signs[i]!=signs[(i-1)%n]),None)
    if anchor is None:return []
    runs=[];start=anchor;sign=signs[anchor]
    for i in range(anchor+1,anchor+n+1):
        current=signs[i%n] if i<anchor+n else None
        if current!=sign:
            if sign and 3<=i-start<=n*.24:
                # The local tangent window spans three bins; sum/3 estimates
                # the total heading change rather than triple-counting it.
                heading_change=abs(sum(bend[j%n] for j in range(start,i)))/3
                if heading_change>=.3:
                    apex=max(range(start,i),key=lambda j:abs(bend[j%n]))
                    runs.append({'entry_p':(start%n)/n,'apex_p':(apex%n)/n,
                        'exit_p':((i+2)%n)/n,'span':(i+2-start)/n})
            start=i;sign=current
    runs.sort(key=lambda turn:turn['entry_p'])
    return [{**turn,'id':i+1,'label':f'Learned turn {i+1}'} for i,turn in enumerate(runs)]


class CornerCoach:
    def __init__(self,turns=None):
        self.turns=turns or [];self.last_exit=None;self.last_result=None;self.laps={};self.praised={}
        self.last_praise=-100;self.reset()

    def reset(self):
        self.previous=None;self.active=None;self.seen=set()

    def set_turns(self,turns):
        self.turns=turns;self.reset()

    def observe(self,s,grip=None,incident=False):
        prev=self.previous;self.previous=s
        if s.status!='live' or s.in_pit:
            self.reset();return None
        if not prev:return None
        dt=s.timestamp-prev.timestamp
        advance=(s.lap+s.progress)-(prev.lap+prev.progress)
        moved=math.hypot(s.x-prev.x,s.z-prev.z)
        continuous=(0<dt<=.6 and 0<=advance<=.025 and
            moved<=max(15,max(s.speed,prev.speed)/3.6*dt*3+5))
        if not continuous:
            self.active=None;return None
        absolute=s.lap+s.progress;old_absolute=prev.lap+prev.progress
        for turn in self.turns:
            for lap in (prev.lap,s.lap):
                entry=lap+turn['entry_p'];key=(lap,turn['id'])
                if key not in self.seen and old_absolute<=entry<=absolute and advance>0:
                    self.seen.add(key)
                    stats=self.laps.setdefault(lap,{'observed_turns':0,'clean_exits':0})
                    stats['observed_turns']+=1
                    self.active={'turn':turn,'lap':lap,'end':entry+turn['span'],
                        'started':s.timestamp,'min_speed':s.speed,'peak_steer':0,
                        'turn_seconds':0,'slip_seconds':0,'settled_seconds':0,'invalid':prev.in_pit}
        self.seen={key for key in self.seen if key[0]>=s.lap-1}
        self.laps={lap:stats for lap,stats in self.laps.items() if lap>=s.lap-2}
        active=self.active
        if not active:return None
        if absolute>active['end']+.025 or s.timestamp-active['started']>45:
            self.last_result={'label':active['turn']['label'],'lap':active['lap']+1,'clean':False,
                'outcome':'Exit not confirmed before leaving the learned turn region.'}
            self.active=None;return None
        active['min_speed']=min(active['min_speed'],s.speed)
        steer=abs(s.steer);active['peak_steer']=max(active['peak_steer'],steer)
        if steer>.04:active['turn_seconds']+=dt
        slip_pattern=bool(grip) or max((abs(value) for value in s.slip),default=0)>.35
        active['slip_seconds']=active['slip_seconds']+dt if slip_pattern else 0
        new_damage=max((b-a for a,b in zip(prev.damage,s.damage)),default=0)>1
        active['invalid']|=(s.tyres_out>2 or prev.tyres_out>2 or s.penalty>0 or prev.penalty>0 or
            new_damage or incident or active['slip_seconds']>=.25 or s.speed<10)
        unwind=max(.025,min(.08,active['peak_steer']*.45))
        settled=(absolute>=active['end'] and active['turn_seconds']>=.4 and
            steer<=unwind and s.brake<.05 and s.throttle>=.55 and not slip_pattern and
            s.speed>=max(35,active['min_speed']+4))
        active['settled_seconds']=active['settled_seconds']+dt if settled else 0
        if active['settled_seconds']<.6:return None
        self.active=None
        if active['invalid']:
            self.last_result={'label':active['turn']['label'],'lap':active['lap']+1,'clean':False,
                'outcome':'Clean exit not confirmed; observed slip, damage, track limits, penalty or low-speed interruption.'}
            return None
        report={'turn_id':active['turn']['id'],'label':active['turn']['label'],
            'lap':active['lap']+1,'progress':round(s.progress,4),'exit_speed':round(s.speed,1),
            'speed_gain':round(s.speed-active['min_speed'],1),'reference_speed_delta':None,
            'estimated':True}
        self.last_exit=report;self.last_result={**report,'clean':True};self.laps[active['lap']]['clean_exits']+=1
        return report

    def allow_praise(self,s):
        return s.timestamp-self.last_praise>=45 and self.praised.get(s.lap,0)<2

    def praised_exit(self,s):
        self.last_praise=s.timestamp;self.praised={s.lap:self.praised.get(s.lap,0)+1}

    def snapshot(self,s):
        current=self.active['turn'] if self.active else None
        if not current:
            current=next((turn for turn in self.turns if (s.progress-turn['entry_p'])%1<=turn['span']),None)
        upcoming=min(self.turns,key=lambda turn:(turn['entry_p']-s.progress)%1) if self.turns else None
        return {'learned_turns':len(self.turns),'current':current,
            'phase':('Checking exit' if s.lap+s.progress>=self.active['end'] else 'In turn') if self.active else 'Turn region' if current else None,
            'next_turn':({**upcoming,'distance':round((upcoming['entry_p']-s.progress)%1*s.length) if s.length>0 else None} if upcoming else None),
            'last_clean_exit':self.last_exit,'last_result':self.last_result,
            'lap_counts':self.laps.get(s.lap,{'observed_turns':0,'clean_exits':0}),
            'note':'Turn regions estimated from your clean reference line; clean observed is not a perfect or officially valid corner.'}
