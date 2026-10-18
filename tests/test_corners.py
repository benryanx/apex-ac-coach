import math

import pytest

from coach.corners import CornerCoach,learn_turns
from coach.engine import CoachEngine
from coach.telemetry import Sample


TURN={'id':1,'label':'Learned turn 1','entry_p':.2,'apex_p':.22,'exit_p':.24,'span':.04}


def trace(**overrides):
    for i in range(76):
        p=.19+i*.001
        values=dict(timestamp=10+i*.1,status='live',progress=p,lap_ms=int(p*100000),
            car='test_car',track='test_track',x=p*1000,z=0,
            speed=60+abs(p-.22)*1000,steer=.25 if .2<=p<.24 else .01,
            throttle=.3 if p<.23 else .9,brake=.3 if p<.215 else 0,
            slip=[.07]*4)
        for key,value in overrides.items():values[key]=value(p) if callable(value) else value
        yield Sample(**values)


def collect(coach,**overrides):
    return [result for sample in trace(**overrides) if (result:=coach.observe(sample))]


def stadium():
    radius=50;total=800+math.tau*radius;points=[]
    for i in range(1000):
        p=i/1000;d=p*total
        if d<400:x,z=-200+d,-50
        elif d<400+math.pi*radius:
            a=-math.pi/2+(d-400)/radius;x,z=200+radius*math.cos(a),radius*math.sin(a)
        elif d<800+math.pi*radius:x,z=200-(d-400-math.pi*radius),50
        else:
            a=math.pi/2+(d-800-math.pi*radius)/radius;x,z=-200+radius*math.cos(a),radius*math.sin(a)
        points.append({'p':p,'x':x,'z':z,'ms':p*100000,'speed':100,'brake':0,'throttle':.8})
    return points


def test_geometry_learns_two_distinct_turns_from_an_existing_coordinate_only_reference():
    turns=learn_turns(stadium())
    assert len(turns)==2
    assert turns[0]['entry_p']<turns[0]['apex_p']<turns[0]['exit_p']
    assert turns[1]['span']<.24
    assert turns[0]['label']=='Learned turn 1'
    assert learn_turns(stadium()[200:])==[]


def test_clean_exit_requires_observed_turn_unwind_power_and_acceleration():
    coach=CornerCoach([TURN]);events=collect(coach)
    assert len(events)==1
    assert events[0]['exit_speed']>80 and events[0]['speed_gain']>=20
    assert events[0]['estimated'] is True
    assert coach.snapshot(Sample(lap=0))['lap_counts']=={'observed_turns':1,'clean_exits':1}
    assert coach.last_result['clean'] is True


@pytest.mark.parametrize('override',[
    {'steer':.01}, {'throttle':.1}, {'brake':.3},
    {'tyres_out':lambda p:3 if .22<p<.23 else 0},
    {'penalty':lambda p:1 if p>.22 else 0},
    {'damage':lambda p:[10 if p>.22 else 0,0,0,0,0]},
    {'slip':lambda p:[.1,.1,.6,.6] if .241<p<.25 else [.07]*4},
    {'status':lambda p:'paused' if .22<p<.23 else 'live'},
    {'x':lambda p:p*1000+1000 if .22<p<.23 else p*1000},
])
def test_no_praise_for_unobserved_or_unclean_exit(override):
    assert collect(CornerCoach([TURN]),**override)==[]


def test_joining_mid_corner_or_missing_packets_does_not_imply_clean_driving():
    coach=CornerCoach([TURN])
    samples=list(trace())
    assert not [result for s in samples[25:] if (result:=coach.observe(s))]
    coach=CornerCoach([TURN])
    assert not [result for i,s in enumerate(samples) if i not in range(15,30) and (result:=coach.observe(s))]
    assert not collect(CornerCoach())


def test_existing_damage_is_a_baseline_not_new_contact():
    assert len(collect(CornerCoach([TURN]),damage=[10,0,0,0,0]))==1


def test_praise_is_limited_and_quiet_compatible():
    coach=CornerCoach([TURN])
    s=Sample(timestamp=50,lap=0)
    assert coach.allow_praise(s);coach.praised_exit(s)
    assert not coach.allow_praise(Sample(timestamp=60,lap=0))
    assert coach.allow_praise(Sample(timestamp=96,lap=0));coach.praised_exit(Sample(timestamp=96,lap=0))
    assert not coach.allow_praise(Sample(timestamp=150,lap=0))
    assert coach.allow_praise(Sample(timestamp=150,lap=1))


def test_engine_emits_grounded_exit_event_and_exposes_corner_state(tmp_path):
    engine=CoachEngine(tmp_path)
    initial=next(trace());engine.update(initial)
    engine.corners.set_turns([TURN])
    engine.reference={'samples':[{'p':.19,'ms':19000,'speed':65,'x':190,'z':0},{'p':.27,'ms':27000,'speed':65,'x':270,'z':0}],
        'time_ms':100000,'corners':[]}
    for s in trace():state=engine.update(s)
    exits=[event for event in state['events'] if event['kind']=='clean_exit']
    assert len(exits)==1 and exits[0]['speak']
    assert exits[0]['facts']['reference_speed_delta']>15
    assert 'same exit position' in exits[0]['text']
    assert state['analysis']['corner']['last_clean_exit']['turn_id']==1


def test_turn_crossing_finish_line_stays_one_region_and_one_assessment():
    points=stadium()
    shifted=[{**points[(i+400)%1000],'p':i/1000} for i in range(1000)]
    turns=learn_turns(shifted)
    assert len(turns)==2 and any(turn['exit_p']<turn['entry_p'] for turn in turns)
    coach=CornerCoach([{**TURN,'entry_p':.98,'exit_p':.02,'span':.04}]);events=[]
    for i in range(76):
        absolute=.97+i*.001;p=absolute%1
        s=Sample(timestamp=10+i*.1,status='live',lap=int(absolute),progress=p,
            x=100*math.cos(p*math.tau),z=100*math.sin(p*math.tau),
            speed=60+abs(absolute-1)*1000,steer=.25 if .98<=absolute<1.02 else .01,
            throttle=.9 if absolute>1.01 else .3)
        if result:=coach.observe(s):events.append(result)
    assert len(events)==1 and events[0]['lap']==1


def test_saved_coordinate_reference_is_reused_for_positioning_and_exit_analysis(tmp_path):
    import json
    from pathlib import Path
    engine=CoachEngine(tmp_path);engine.update(next(trace()))
    path=engine.reference_path();path.parent.mkdir(parents=True)
    path.write_text(json.dumps({'identity':list(engine.identity),'samples':stadium(),
        'time_ms':100000,'sectors':[],'corners':[]}),encoding='utf-8')
    reloaded=CoachEngine(tmp_path);state=reloaded.update(next(trace()))
    assert state['analysis']['corner']['learned_turns']==2
    assert state['analysis']['corner']['next_turn']['distance'] is None
