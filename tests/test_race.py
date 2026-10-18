import ast
import importlib.util
import json
import math
import socket
import sys
import time
from pathlib import Path
from types import SimpleNamespace

import pytest

from coach.race import RaceAwareness, spoken_position
from coach.opponents import OpponentBridge
from coach.telemetry import Sample
from coach.engine import CoachEngine


def car(t=0,**kwargs):
    args=dict(timestamp=10+t,status='live',session_type=2,position=5,car_count=12,
        speed=100,lap_ms=10000+int(t*1000),progress=.5+t*.001,x=t*20,z=0)
    args.update(kwargs)
    return Sample(**args)


def rival(**kwargs):
    args=dict(id=1,name='Rival',position=4,lap=0,progress=.501,x=20,z=0,speed=100,in_pit=False)
    args.update(kwargs)
    return args


def test_position_gain_is_debounced_and_never_claimed_as_pass():
    race=RaceAwareness()
    race.update(car())
    collected=[]
    for i in range(1,11):
        _,events=race.update(car(i*.2,position=4))
        collected.extend(events)
    assert len(collected)==1
    assert collected[0][0]=='position'
    assert 'Up one place to fourth' in collected[0][1]
    assert 'pass' not in collected[0][1].lower()
    assert race.overtakes==0


@pytest.mark.parametrize(('position','expected'),[
    (1,'first'),(2,'second'),(3,'third'),(4,'fourth'),(11,'eleventh'),
    (12,'twelfth'),(13,'thirteenth'),(20,'twentieth'),(21,'twenty-first'),
    (30,'thirtieth'),(99,'ninety-ninth'),(100,'one hundredth'),(0,'unknown')])
def test_spoken_positions_use_ordinals(position,expected):
    assert spoken_position(position)==expected


def test_lost_place_is_described_as_a_loss_without_inventing_a_passer():
    race=RaceAwareness()
    race.update(car())
    collected=[]
    for i in range(1,11):
        _,events=race.update(car(i*.2,position=6))
        collected.extend(events)
    assert collected==[('position_lost','Down one place to sixth in the standings.',False)]
    assert race.positions_lost==1


@pytest.mark.parametrize('override',[{'in_pit':True},{'session_type':0}])
def test_pit_running_and_practice_do_not_claim_race_gains(override):
    race=RaceAwareness()
    race.update(car(**override))
    for i in range(1,11):
        _,events=race.update(car(i*.2,position=4,**override))
        assert not events


def pass_sequence(race,pit=False):
    race.update(car(opponents_available=True,opponents=[rival()]))
    collected=[]
    for i in range(1,11):
        _,events=race.update(car(i*.2,position=4,progress=.502+i*.001,
            opponents_available=True,opponents=[rival(position=5,progress=.501+i*.001,in_pit=pit)]))
        collected.extend(events)
    return collected


def test_named_pass_requires_physical_crossing_and_persistent_position_gain():
    race=RaceAwareness()
    events=pass_sequence(race)
    assert race.overtakes==1
    assert [e[0] for e in events]==['overtake']
    assert events[0][1]=='You passed Rival for fourth.'


def test_engine_pass_keeps_full_roster_identity_as_structured_facts_for_radio(tmp_path):
    engine=CoachEngine(tmp_path)
    engine.update(car(opponents_available=True,opponents=[rival(name='Elfyn Cook',car='bmw_m4')]))
    for i in range(1,11):
        state=engine.update(car(i*.2,position=4,progress=.502+i*.001,opponents_available=True,
            opponents=[rival(name='Elfyn Cook',car='bmw_m4',position=5,progress=.501+i*.001)]))
    event=next(e for e in state['events'] if e['kind']=='overtake')
    assert event['speak'] is True
    assert event['facts']=={'driver_id':1,'driver_name':'Elfyn Cook','position':4}
    assert 'Elfyn Cook' in event['text']  # Detailed notes retain the full identity.


def test_opponent_pitting_is_not_an_on_track_pass():
    race=RaceAwareness()
    events=pass_sequence(race,pit=True)
    assert race.overtakes==0
    assert all(e[0]!='overtake' for e in events)


def test_lapping_a_car_without_race_position_gain_is_not_a_pass_for_position():
    race=RaceAwareness()
    race.update(car(lap=1,opponents_available=True,opponents=[rival(lap=0,position=12)]))
    for i in range(1,10):
        _,events=race.update(car(i*.2,lap=1,opponents_available=True,opponents=[rival(lap=0,position=12,progress=.49)]))
        assert all(e[0]!='overtake' for e in events)


def test_new_damage_counts_once_existing_damage_and_repairs_do_not():
    race=RaceAwareness()
    race.update(car(damage=[10,0,0,0,0]))
    _,events=race.update(car(.2,damage=[25,0,0,0,0]))
    assert events[0][0]=='incident'
    assert 'likely car contact' in events[0][1]
    assert 'unconfirmed' in race.incidents[0]['assessment']
    _,events=race.update(car(.4,damage=[25,0,0,0,0]))
    assert not events
    _,events=race.update(car(.6,damage=[0,0,0,0,0]))
    assert not events
    assert race.incident_count==1


def test_damage_can_name_one_consistently_nearby_possible_partner():
    race=RaceAwareness()
    race.update(car(length=4000,opponents_available=True,
        opponents=[rival(name='Jason',x=4,progress=.5005)]))
    state,events=race.update(car(.2,length=4000,damage=[20,0,0,0,0],opponents_available=True,
        opponents=[rival(name='Jason',x=8,progress=.5007)]))
    assert events==[('incident','Damage registered—possible contact with Jason.',True)]
    incident=state['recent_incidents'][0]
    assert incident['possible_other_driver']=='Jason'
    assert 'fault unconfirmed' in incident['evidence']


@pytest.mark.parametrize('case',['multiple','unnamed_neighbour','far','different_progress','renamed','stale','unknown_length','no_damage'])
def test_contact_does_not_invent_a_partner_from_ambiguous_or_unrelated_roster(case):
    race=RaceAwareness()
    before=[rival(x=4,progress=.5005)]
    after=[rival(x=8,progress=.5007)]
    kwargs=dict(length=4000,opponents_available=True,damage=[20,0,0,0,0])
    if case=='multiple':
        before.append(rival(id=2,name='Other',x=5,progress=.5006))
        after.append(rival(id=2,name='Other',x=9,progress=.5008))
    elif case=='unnamed_neighbour':after.append(rival(id=2,name='',x=9,progress=.5008))
    elif case=='far':after[0]['x']=100
    elif case=='different_progress':after[0]['progress']=.7
    elif case=='renamed':after[0]['name']='Someone new'
    elif case=='stale':kwargs['opponents_available']=False
    elif case=='unknown_length':kwargs['length']=0
    elif case=='no_damage':kwargs['damage']=[0,0,0,0,0]
    race.update(car(length=4000,opponents_available=True,opponents=before))
    state,events=race.update(car(.2,opponents=after,**kwargs))
    assert all('possible_other_driver' not in item for item in state['recent_incidents'])
    assert all('Everything okay' not in event[1] for event in events)
    if case=='no_damage':assert not events
    else:assert events[0][1]=='Damage registered—likely car contact.'


@pytest.mark.parametrize('status',['paused','replay','disconnected'])
def test_no_incidents_on_inactive_feeds_or_reconnect(status):
    race=RaceAwareness()
    race.update(car())
    _,events=race.update(car(.2,status=status,damage=[100,0,0,0,0]))
    assert not events
    _,events=race.update(car(.4,damage=[100,0,0,0,0]))
    assert not events


def test_teleport_or_sample_gap_does_not_look_like_contact():
    race=RaceAwareness()
    race.update(car())
    _,events=race.update(car(.2,x=1000,damage=[100,0,0,0,0]))
    assert not events
    _,events=race.update(car(5,x=1000,damage=[200,0,0,0,0]))
    assert not events


def test_possible_spin_requires_speed_loss_rotation_and_grip_loss():
    race=RaceAwareness()
    race.update(car(speed=120))
    events=[]
    for i in range(1,7):
        _,current=race.update(car(i*.2,heading=i*.4,speed=120-i*10,slip=[.1,.1,.8,.8]))
        events.extend(current)
    assert len(events)==1 and 'Possible spin' in events[0][1]


def test_normal_hairpin_and_angle_wrap_are_not_called_a_spin():
    race=RaceAwareness()
    race.update(car(speed=120,heading=3))
    for i in range(1,7):
        heading=(3+i*.4+math.pi)%math.tau-math.pi
        _,events=race.update(car(i*.2,heading=heading,speed=120-i*10))
        assert not events


def test_engine_carries_race_facts_to_state_export_and_excludes_damage_lap(tmp_path):
    engine=CoachEngine(tmp_path)
    engine.update(car())
    state=engine.update(car(.2,damage=[20,0,0,0,0]))
    assert state['race']['position']==5
    assert state['race']['incident_count']==1
    assert not state['analysis']['clean']
    assert engine.export()['race']['incident_count']==1
    assert state['events'][0]['speak']


def payload():
    return {'version':1,'identity':['test_car','test_track',''],
        'cars':[rival(id=0,name='Player',position=2,progress=.5,car='test_car',car_name='Test GT3'),
                rival(position=1,car='bmw_z4_gt3',car_name='BMW Z4 GT3')]}


def test_roster_udp_is_received_validated_identity_matched_and_expires():
    bridge=OpponentBridge(port=0)
    producer=socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
    try:
        producer.sendto(json.dumps(payload()).encode(),bridge.socket.getsockname())
        time.sleep(.02)
        s=car(car='test_car',track='test_track')
        result=bridge.enrich(s)
        assert result.opponents_available
        assert result.opponents[0]['name']=='Rival'
        assert result.opponents[0]['car_name']=='BMW Z4 GT3'
        assert result.driver=='Player' and result.car_display_name=='Test GT3'
        assert result.position==2
        assert not bridge.enrich(car(car='different_car',track='test_track')).opponents_available
        bridge.received_at-=2
        assert not bridge.enrich(car(car='test_car',track='test_track')).opponents_available
    finally:
        bridge.close();producer.close()


@pytest.mark.parametrize('mutation',[
    lambda p:p.update(version=2),
    lambda p:p['cars'][0].update(progress=float('nan')),
    lambda p:p['cars'][0].update(position=-1),
    lambda p:p['cars'][0].update(in_pit='false'),
    lambda p:p['cars'][0].update(car_name=['not a model']),
    lambda p:p['cars'][0].update(car='x'*101),
    lambda p:p['cars'].append(p['cars'][0]),
])
def test_invalid_roster_is_rejected(mutation):
    p=payload();mutation(p)
    with pytest.raises(ValueError):OpponentBridge.decode(json.dumps(p))


def test_roster_rank_index_is_normalized_only_when_unambiguous():
    p=payload();p['cars'][0]['position']=1;p['cars'][1]['position']=0
    decoded=OpponentBridge.decode(json.dumps(p))
    assert [c['position'] for c in decoded['cars']]==[2,1]
    p['cars'][0]['position']=0
    decoded=OpponentBridge.decode(json.dumps(p))
    assert [c['position'] for c in decoded['cars']]==[0,0]


def test_bridge_plugin_uses_python33_syntax_and_emits_supported_schema(monkeypatch):
    plugin=Path(__file__).resolve().parents[1]/'ac-plugin'/'ApexBridge'/'ApexBridge.py'
    ast.parse(plugin.read_text(),feature_version=(3,3))
    class State:
        WorldPosition='xyz';LapCount='lap';NormalizedSplinePosition='progress';SpeedKMH='speed'
    ac=SimpleNamespace(newApp=lambda name:1,setSize=lambda *a:None,addLabel=lambda *a:None,
        getCarsCount=lambda:2,isConnected=lambda i:True,getDriverName=lambda i:'Driver '+str(i),
        getCarRealTimeLeaderboardPosition=lambda i:i+1,isCarInPit=lambda i:False,
        isCarInPitline=lambda i:False,getCarName=lambda i:'test_car',getTrackName=lambda i:'test_track',
        getTrackConfiguration=lambda i:'',log=lambda s:None,
        getCarState=lambda i,key:{'xyz':[i*10,0,0],'lap':0,'progress':.5+i*.001,'speed':100}[key])
    monkeypatch.setitem(sys.modules,'ac',ac)
    monkeypatch.setitem(sys.modules,'acsys',SimpleNamespace(CS=State))
    spec=importlib.util.spec_from_file_location('test_apex_plugin',plugin)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Sender:
        def sendto(self,raw,address):self.raw,self.address=raw,address
    sender=Sender();module._socket=sender
    module.acUpdate(.21)
    assert sender.address==('127.0.0.1',9876)
    decoded=OpponentBridge.decode(sender.raw)
    assert len(decoded['cars'])==2
    assert decoded['cars'][1]['name']=='Driver 1'
    assert decoded['cars'][1]['car']=='test_car'


def test_roster_standings_neighbours_models_and_inactive_feed():
    race=RaceAwareness()
    s=car(position=2,car_count=3,driver='Player',car_display_name='Porsche 911 GT3 R',opponents_available=True,
          opponents=[rival(position=3,name='Behind',car='bmw_z4_gt3',car_name='BMW Z4 GT3'),
                     rival(id=2,position=1,name='Ahead',car='ks_ferrari_488_gt3',car_name='Ferrari 488 GT3')])
    state,_=race.update(s)
    assert [other['position'] for other in state['roster']]==[1,2,3]
    assert state['ahead']['name']=='Ahead' and state['ahead']['car_name']=='Ferrari 488 GT3'
    assert state['behind']['name']=='Behind'
    state,_=race.update(car(.2,status='paused',opponents_available=True,opponents=s.opponents))
    assert state['roster']==[] and state['ahead'] is None and state['behind'] is None


@pytest.mark.parametrize(('gap','direction'),[(.005,'ahead'),(-.005,'behind')])
def test_roster_proximity_requires_signed_track_distance_and_world_distance(gap,direction):
    state,_=RaceAwareness().update(car(length=4000,position=4,opponents_available=True,
        opponents=[rival(position=5,progress=.5+gap,x=18)]))
    assert state['behind']['close_on_track']==direction
    assert state['behind']['approx_track_gap_m']==20
    # Direction on track is independent of the standings relationship.
    assert state['behind']['position']==5


@pytest.mark.parametrize('override',[
    {'length':0}, {'in_pit':True}, {'other':{'in_pit':True}},
    {'other':{'progress':.4}}, {'other':{'x':500}},
    {'other':{'lap':1}}, {'status':'paused'}, {'opponents_available':False},
])
def test_standings_neighbour_does_not_imply_proximity(override):
    override=dict(override)
    other_args=dict(position=6,progress=.495,x=18)
    other_args.update(override.pop('other',{}))
    args=dict(length=4000,opponents_available=True,opponents=[rival(**other_args)])
    args.update(override)
    state,_=RaceAwareness().update(car(**args))
    assert all('close_on_track' not in entry for entry in state['roster'])


def test_proximity_across_finish_line_uses_lap_count():
    state,_=RaceAwareness().update(car(lap=1,progress=.002,length=4000,
        opponents_available=True,opponents=[rival(position=6,lap=0,progress=.998,x=10)]))
    assert state['behind']['close_on_track']=='behind'
    assert state['behind']['approx_track_gap_m']==16


def test_old_bridge_without_models_still_works():
    p=payload()
    for other in p['cars']:
        other.pop('car');other.pop('car_name')
    assert all(other['car_name']=='' for other in OpponentBridge.decode(json.dumps(p))['cars'])


def test_local_file_roster_works_without_a_udp_sender_and_expires(tmp_path):
    path=tmp_path/'roster.json';path.write_text(json.dumps(payload()))
    bridge=OpponentBridge(port=0,roster_path=path)
    try:
        result=bridge.enrich(car(car='test_car',track='test_track'))
        assert result.opponents_available and result.opponents_transport=='file'
        assert result.opponents[0]['name']=='Rival'
        assert result.opponents[0]['car_name']=='BMW Z4 GT3'
        bridge.received_at-=2
        stale=bridge.enrich(car(car='test_car',track='test_track'))
        assert not stale.opponents_available and 'stopped' in stale.opponents_status
    finally:bridge.close()


def test_missing_socket_in_ac_does_not_prevent_plugin_loading_or_file_output(tmp_path,monkeypatch):
    import builtins
    plugin=Path(__file__).resolve().parents[1]/'ac-plugin'/'ApexBridge'/'ApexBridge.py'
    class State:
        WorldPosition='xyz';LapCount='lap';NormalizedSplinePosition='progress';SpeedKMH='speed'
    ac=SimpleNamespace(newApp=lambda name:1,setSize=lambda *a:None,addLabel=lambda *a:None,
        getCarsCount=lambda:2,isConnected=lambda i:True,getDriverName=lambda i:'Driver '+str(i),
        getCarRealTimeLeaderboardPosition=lambda i:i+1,isCarInPit=lambda i:False,
        isCarInPitline=lambda i:False,getCarName=lambda i:'test_car',getTrackName=lambda i:'test_track',
        getTrackConfiguration=lambda i:'',log=lambda s:None,
        getCarState=lambda i,key:{'xyz':[i*10,0,0],'lap':0,'progress':.5+i*.001,'speed':100}[key])
    monkeypatch.setitem(sys.modules,'ac',ac);monkeypatch.setitem(sys.modules,'acsys',SimpleNamespace(CS=State))
    original=builtins.__import__
    def missing_socket(name,*args,**kwargs):
        if name in ('socket','_socket'):raise ImportError('No module named _socket')
        return original(name,*args,**kwargs)
    monkeypatch.setattr(builtins,'__import__',missing_socket)
    spec=importlib.util.spec_from_file_location('test_apex_no_socket',plugin)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.socket is None
    module.acMain('test');path=tmp_path/'roster.json';module._roster_path=str(path)
    module.acUpdate(.21)
    decoded=OpponentBridge.decode(path.read_bytes())
    assert len(decoded['cars'])==2 and decoded['cars'][1]['name']=='Driver 1'


def test_plugin_car_ui_names_are_read_from_its_game_folder(tmp_path,monkeypatch):
    plugin=Path(__file__).resolve().parents[1]/'ac-plugin'/'ApexBridge'/'ApexBridge.py'
    installed=tmp_path/'apps'/'python'/'ApexBridge'/'ApexBridge.py'
    installed.parent.mkdir(parents=True);installed.write_text(plugin.read_text())
    ui=tmp_path/'content'/'cars'/'test_gt3'/'ui'/'ui_car.json'
    ui.parent.mkdir(parents=True);ui.write_text('{"name":"Real GT3 Name","description":"line\nbreak"}')
    monkeypatch.setitem(sys.modules,'ac',SimpleNamespace(getCarName=lambda i:'test_gt3' if i==1 else -1))
    monkeypatch.setitem(sys.modules,'acsys',SimpleNamespace())
    spec=importlib.util.spec_from_file_location('test_roster_labels',installed)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    assert module.car_details(1)==('test_gt3','Real GT3 Name')
    assert module.car_details(0)==('','')
    ui.unlink()
    assert module.car_details(1)==('test_gt3','Real GT3 Name')


def test_pass_call_includes_observed_car_model():
    race=RaceAwareness()
    race.update(car(opponents_available=True,opponents=[rival(car='bmw_z4_gt3',car_name='BMW Z4 GT3')]))
    events=[]
    for i in range(1,11):
        _,found=race.update(car(i*.2,position=4,progress=.502+i*.001,opponents_available=True,
            opponents=[rival(position=5,progress=.501+i*.001,car='bmw_z4_gt3',car_name='BMW Z4 GT3')]))
        events.extend(found)
    assert len(events)==1 and 'Rival in the BMW Z4 GT3' in events[0][1]


def test_enabling_bridge_preserves_other_app_settings_and_is_idempotent():
    from install_bridge import enable_app
    original='[CHAT]\r\nACTIVE=1\r\n\r\n[GMETER]\r\nACTIVE=0\r\n'
    enabled=enable_app(original)
    assert original.rstrip() in enabled
    assert '[APEXBRIDGE]\r\nACTIVE=1\r\n' in enabled
    assert enable_app(enabled)==enabled
    assert enable_app('[APEXBRIDGE]\nACTIVE=0\n[CHAT]\nACTIVE=0\n')=='[APEXBRIDGE]\nACTIVE=1\n[CHAT]\nACTIVE=0\n'
