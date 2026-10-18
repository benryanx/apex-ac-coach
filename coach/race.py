"""Conservative race-event inference, independent of lap timing and speech."""
from collections import deque
import math


SESSION_NAMES = {-1:"Unknown",0:"Practice",1:"Qualifying",2:"Race",3:"Hotlap",4:"Time attack",5:"Drift",6:"Drag"}
FLAGS = {0:"None",1:"Blue",2:"Yellow",3:"Black",4:"White",5:"Chequered",6:"Penalty"}


def spoken_position(position):
    """Use normal racing language in observations that reach the radio."""
    ordinals = ('unknown', 'first', 'second', 'third', 'fourth', 'fifth', 'sixth',
                'seventh', 'eighth', 'ninth', 'tenth', 'eleventh', 'twelfth',
                'thirteenth', 'fourteenth', 'fifteenth', 'sixteenth',
                'seventeenth', 'eighteenth', 'nineteenth')
    tens = {20:'twenty', 30:'thirty', 40:'forty', 50:'fifty', 60:'sixty',
            70:'seventy', 80:'eighty', 90:'ninety'}
    if 0 < position < 20:
        return ordinals[position]
    if 20 <= position < 100:
        base, remainder = divmod(position, 10)
        return (tens[base*10]+'-'+ordinals[remainder] if remainder
                else tens[base*10][:-1]+'ieth')
    if position == 100:
        return 'one hundredth'
    return 'unknown'


def possible_contact_driver(previous, current):
    """A unique nearby car is a possible partner, never proof of impact or blame."""
    if not (previous.opponents_available and current.opponents_available and current.length>0):
        return None
    old={other['id']:other for other in previous.opponents}
    nearby=[]
    for other in current.opponents:
        distance=math.hypot(current.x-other['x'],current.z-other['z'])
        progress_gap=abs((other['progress']-current.progress+.5)%1-.5)
        if distance<=8 and progress_gap*current.length<=15:
            nearby.append((distance,other))
    # Even an unnamed/new car makes the contact area ambiguous.
    if len(nearby)!=1 or nearby[0][0]>6:
        return None
    other=nearby[0][1]
    before=old.get(other['id'])
    if (not before or not other['name'] or before['name']!=other['name']
            or before.get('car')!=other.get('car') or other['in_pit'] or before['in_pit']):
        return None
    old_distance=math.hypot(previous.x-before['x'],previous.z-before['z'])
    # Require a stable neighbour, not an opponent teleporting beside us.
    movement=math.hypot(other['x']-before['x'],other['z']-before['z'])
    max_move=max(15,max(other['speed'],before['speed'])/3.6*(current.timestamp-previous.timestamp)*3+5)
    return other['name'] if old_distance<=12 and movement<=max_move else None


class RaceAwareness:
    def __init__(self):
        self.last = None
        self.stable_position = None
        self.candidate_position = None
        self.candidate_since = 0
        self.trajectory = deque()
        self.incidents = deque(maxlen=12)
        self.incident_count = 0
        self.overtakes = 0
        self.positions_lost = 0
        self.last_position_change = 0
        self.last_incident_at = -100
        self.last_pass_at = {}
        self.pending_passes = {}
        self.pass_facts = []

    def snapshot(self, s, active):
        roster=[]
        if active and s.opponents_available:
            roster=[{key:other.get(key) for key in ('id','name','car','car_name','position','in_pit')}
                    for other in s.opponents]
            for entry, other in zip(roster, s.opponents):
                # Standings alone cannot support "right behind". Require both
                # a short signed race-distance gap and nearby world coordinates.
                gap=(other['lap']+other['progress'])-(s.lap+s.progress)
                metres=abs(gap)*s.length
                if (s.length>0 and not s.in_pit and not other['in_pit']
                        and 0<metres<=60
                        and math.hypot(s.x-other['x'],s.z-other['z'])<=60):
                    entry['close_on_track']='ahead' if gap>0 else 'behind'
                    entry['approx_track_gap_m']=round(metres)
            roster.append({'id':0,'name':s.driver or '', 'car':s.car,
                           'car_name':s.car_display_name or s.car,'position':s.position,'in_pit':s.in_pit})
            roster.sort(key=lambda other:(other['position'] or 100001,other['id']))
        ahead=next((other for other in roster if s.position>1 and other['position']==s.position-1),None)
        behind=next((other for other in roster if s.position>0 and other['position']==s.position+1),None)
        return {"position":s.position if active and s.position>0 else None,
            "roster":roster,"ahead":ahead,"behind":behind,
            "car_count":s.car_count if active else None,
            "session":SESSION_NAMES.get(s.session_type,"Unknown"),
            "flag":FLAGS.get(s.flag,"Unknown") if active else "Unavailable",
            "damage_readings":s.damage if active else None,
            "damage_note":"Raw game damage values; not a percentage or a mechanical diagnosis.",
            "opponents_available":active and s.opponents_available,
            "roster_status":s.opponents_status,"roster_transport":s.opponents_transport,
            "overtakes":self.overtakes,"positions_lost":self.positions_lost,"incident_count":self.incident_count,
            "recent_incidents":list(self.incidents)}

    def update(self, s):
        events=[]
        self.pass_facts=[]
        if s.status != "live":
            self.last=None
            self.candidate_position=None
            self.stable_position=None
            self.trajectory.clear()
            self.pending_passes.clear()
            return self.snapshot(s,False),events
        prev=self.last
        now=s.timestamp
        continuous=prev is not None and 0<now-prev.timestamp<=.6
        if continuous:
            moved=math.hypot(s.x-prev.x,s.z-prev.z)
            max_move=max(15,max(s.speed,prev.speed)/3.6*(now-prev.timestamp)*3+5)
            continuous=moved<=max_move and s.lap>=prev.lap
        if not continuous:
            self.trajectory.clear()
            self.pending_passes.clear()
            self.stable_position=s.position if s.position>0 else None
            self.candidate_position=None
        # Damage delta is evidence of new damage, not proof of collision or fault.
        if continuous and not s.in_pit and not prev.in_pit:
            increase=max((b-a for a,b in zip(prev.damage,s.damage)),default=0)
            if increase>1:
                if now-self.last_incident_at>3:
                    self.last_incident_at=now
                    self.incident_count+=1
                    incident={"kind":"damage_increase","lap":s.lap+1,"progress":round(s.progress,4),
                              "evidence":"New damage reading","assessment":"Assumed car contact; unconfirmed"}
                    candidate=possible_contact_driver(prev,s)
                    if candidate:
                        incident['possible_other_driver']=candidate
                        incident['evidence']='New damage reading and one consistently nearby car; impact partner and fault unconfirmed'
                    self.incidents.appendleft(incident)
                    text=(f"Damage registered—possible contact with {candidate}." if candidate
                          else "Damage registered—likely car contact.")
                    events.append(("incident",text,True))
        # Spin estimate: substantial rapid rotation plus speed loss over a window.
        if continuous and not s.in_pit:
            self.trajectory.append((now,s.heading,s.speed))
            while self.trajectory and now-self.trajectory[0][0]>1.5:
                self.trajectory.popleft()
            if self.trajectory and now-self.trajectory[0][0]>=.7:
                _,heading,speed=self.trajectory[0]
                rotation=abs((s.heading-heading+math.pi)%math.tau-math.pi)
                loss_of_grip=s.tyres_out>2 or max((abs(v) for v in s.slip),default=0)>.5
                if rotation>1.8 and speed>65 and speed-s.speed>30 and loss_of_grip and now-self.last_incident_at>8:
                    self.last_incident_at=now
                    self.incident_count+=1
                    self.incidents.appendleft({"kind":"possible_spin","lap":s.lap+1,
                        "progress":round(s.progress,4),"evidence":"Rapid rotation with speed loss",
                        "assessment":"Possible spin; contact not established"})
                    events.append(("incident","Possible spin detected from rotation and speed loss. Take a moment to settle the car.",True))
        # Opponent data supports a pass only when racing order and physical order
        # both reverse nearby, neither car pits, and the gain persists.
        named_pass=False
        if continuous and s.session_type==2 and s.opponents_available and prev.opponents_available and not s.in_pit and not prev.in_pit:
            old={p["id"]:p for p in prev.opponents}
            current={p["id"]:p for p in s.opponents}
            for car_id,other in current.items():
                before=old.get(car_id)
                if not before or before["name"]!=other["name"] or before.get('car')!=other.get('car') or before["in_pit"] or other["in_pit"]:
                    self.pending_passes.pop(car_id,None)
                    continue
                old_gap=(prev.lap+prev.progress)-(before["lap"]+before["progress"])
                gap=(s.lap+s.progress)-(other["lap"]+other["progress"])
                close=math.hypot(s.x-other["x"],s.z-other["z"])<100
                plausible=abs(gap-old_gap)<.015 and abs(gap)<.02 and abs(old_gap)<.02
                racing_behind=prev.position>=before["position"]>0
                if plausible and close and racing_behind and old_gap<0<=gap and now-self.last_pass_at.get(car_id,-100)>15:
                    self.pending_passes[car_id]=(now,other["name"],prev.position)
                pending=self.pending_passes.get(car_id)
                if pending:
                    if now-pending[0]>5 or gap<-.001 or not plausible:
                        self.pending_passes.pop(car_id,None)
                    elif now-pending[0]>=1 and gap>=0 and 0<s.position<other["position"] and s.position<pending[2]:
                        self.overtakes+=1
                        self.last_pass_at[car_id]=now
                        self.pending_passes.pop(car_id,None)
                        model=other.get('car_name') or other.get('car')
                        description=f"{other['name']} in the {model}" if model else other['name']
                        events.append(("overtake",f"You passed {description} for {spoken_position(s.position)}.",False))
                        self.pass_facts.append({'driver_id':car_id,'driver_name':other['name'],
                                                'position':s.position})
                        named_pass=True
            for car_id in list(self.pending_passes):
                if car_id not in current:self.pending_passes.pop(car_id,None)
        else:
            self.pending_passes.clear()
        if named_pass:
            self.stable_position=s.position
            self.candidate_position=None
        # Debounce standings; never call a standings-only gain an overtake.
        if continuous and s.session_type==2 and s.position>0 and s.position!=self.stable_position:
            if self.candidate_position!=s.position:
                self.candidate_position=s.position
                self.candidate_since=now
            elif now-self.candidate_since>=1.2:
                old_position=self.stable_position
                self.stable_position=s.position
                self.candidate_position=None
                if old_position and not named_pass and not self.pending_passes and not s.in_pit and not prev.in_pit:
                    change=old_position-s.position
                    self.last_position_change=change
                    if change<0:self.positions_lost+=abs(change)
                    places='one place' if abs(change)==1 else f'{abs(change)} places'
                    events.append(("position_lost" if change<0 else "position",
                        f"{'Up' if change>0 else 'Down'} {places} to {spoken_position(s.position)} in the standings.",False))
        else:
            self.candidate_position=None
        if continuous and s.flag!=prev.flag and s.flag in (1,2,5,6):
            events.append(("flag",f"{FLAGS[s.flag]} flag reported by the game.",s.flag==2))
        self.last=s
        return self.snapshot(s,True),events
