"""Optional localhost-only AC roster bridge. Invalid/stale packets are ignored."""
import json
import math
import socket
import time
from pathlib import Path


class OpponentBridge:
    def __init__(self, port=9876, roster_path=None, config_path=None):
        self.socket=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
        try:
            self.socket.bind(('127.0.0.1',port))
        except OSError:
            self.socket.close()
            self.socket=None
        if self.socket:self.socket.setblocking(False)
        self.latest=None
        self.received_at=0
        self.roster_path=Path(roster_path) if roster_path else None
        if self.roster_path is None and config_path:
            try:
                self.roster_path=Path(json.loads(Path(config_path).read_text(encoding='utf-8'))['roster_file'])
            except (OSError,ValueError,KeyError,TypeError):pass
        self.file_stamp=None
        self.transport=''
        self.read_error=''

    def read_file(self):
        if self.roster_path is None:return
        try:
            stat=self.roster_path.stat()
            stamp=(stat.st_mtime_ns,stat.st_size)
            # Windows file timestamps can lead the wall clock by a small tick.
            # Allow that skew without accepting genuinely future or stale files.
            if stamp==self.file_stamp or not -.25<=time.time()-stat.st_mtime<=1.5:return
            self.file_stamp=stamp
            if stat.st_size>65507:raise ValueError('Roster is too large')
            latest=self.decode(self.roster_path.read_bytes())
            self.latest=latest;self.received_at=time.monotonic();self.transport='file';self.read_error=''
        except FileNotFoundError:pass
        except (OSError,ValueError,TypeError,KeyError,UnicodeError,AttributeError):
            self.read_error='Roster file could not be read or validated'

    @staticmethod
    def decode(raw):
        payload=json.loads(raw)
        if payload.get('version')!=1 or not isinstance(payload.get('cars'),list) or len(payload['cars'])>100:
            raise ValueError('Invalid roster')
        identity=payload.get('identity')
        if not isinstance(identity,list) or len(identity)!=3 or not all(isinstance(s,str) and len(s)<=100 for s in identity):
            raise ValueError('Invalid roster identity')
        cars=[]
        ids=set()
        for item in payload['cars']:
            if not isinstance(item,dict):raise ValueError('Invalid car')
            car={key:item[key] for key in ('id','name','position','lap','progress','speed','x','z','in_pit')}
            if not isinstance(car['name'],str) or len(car['name'])>80:raise ValueError('Invalid driver name')
            for key in ('car','car_name'):
                value=item.get(key,'')
                if not isinstance(value,str) or len(value)>100:raise ValueError('Invalid car model')
                car[key]=' '.join(value.split())
            car['name']=' '.join(car['name'].split())
            if any(not isinstance(car[k],int) or isinstance(car[k],bool) or car[k]<0 or car[k]>100000 for k in ('id','position','lap')):raise ValueError('Invalid car integer')
            if any(not isinstance(car[k],(int,float)) or not math.isfinite(car[k]) for k in ('progress','speed','x','z')):raise ValueError('Invalid car number')
            if not 0<=car['progress']<=1 or not 0<=car['speed']<=1000 or type(car['in_pit']) is not bool:raise ValueError('Invalid car state')
            if car['id'] in ids:raise ValueError('Duplicate car')
            ids.add(car['id']);cars.append(car)
        ranks=sorted(c['position'] for c in cars)
        if ranks==list(range(len(cars))):
            # Accept a zero-based leaderboard only when the complete roster
            # unambiguously establishes its indexing; expose canonical P1+.
            for c in cars:c['position']+=1
        elif ranks!=list(range(1,len(cars)+1)):
            # Incomplete/duplicate ranks cannot safely establish racing order.
            for c in cars:c['position']=0
        return {'identity':identity,'cars':cars}

    def enrich(self,sample):
        if self.socket:
            for _ in range(20):
                try:
                    raw,_=self.socket.recvfrom(65507)
                except BlockingIOError:break
                try:
                    self.latest=self.decode(raw)
                    self.received_at=time.monotonic()
                    self.transport='udp';self.read_error=''
                except (ValueError,TypeError,KeyError,UnicodeError,AttributeError):pass
        self.read_file()
        if sample.source!='ac':return sample
        sample.opponents_status='Waiting for Apex Bridge in AC. Restart the driving session after installing it.'
        if self.read_error:sample.opponents_status=self.read_error
        elif not self.socket and self.roster_path is None:sample.opponents_status='Roster port is busy and file transport is not configured'
        if sample.status!='live':
            sample.opponents_status='Live roster resumes with a driving session'
            return sample
        if not self.latest or time.monotonic()-self.received_at>1:
            if self.latest:sample.opponents_status='Roster feed stopped; check Apex Bridge is active in AC'
            return sample
        if self.latest['identity']!=[sample.car,sample.track,sample.configuration]:
            sample.opponents_status='Roster belongs to a different car, circuit or layout'
            return sample
        player=next((c for c in self.latest['cars'] if c['id']==0),None)
        if not player or player['lap']!=sample.lap or abs((player['progress']-sample.progress+.5)%1-.5)>.025:
            sample.opponents_status='Roster is not synchronized with the current lap position'
            return sample
        sample.opponents=[c for c in self.latest['cars'] if c['id']!=0]
        sample.opponents_available=True
        sample.opponents_status='Live roster connected'
        sample.opponents_transport=self.transport
        sample.driver=player['name']
        sample.car_display_name=player['car_name'] or player['car']
        # The Python API's real-time standings supplement shared-memory position.
        if player['position']>0:sample.position=player['position']
        sample.car_count=len(self.latest['cars'])
        return sample

    def close(self):
        if self.socket:self.socket.close()
