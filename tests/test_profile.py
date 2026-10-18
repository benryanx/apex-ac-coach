from coach.profile import DrivingProfile
from coach.telemetry import Sample


IDENTITY=('ac','test_car','test_track','gp')


def driving(t=0,**kwargs):
    values=dict(timestamp=1+t,status='live',car='test_car',track='test_track',configuration='gp',
        speed=100,gear=3,rpm=7900,max_rpm=8000,rpm_limit_known=True,throttle=.9,
        progress=.2+t*.001,lap_ms=4000+int(t*1000),x=t*10,z=0)
    values.update(kwargs)
    return Sample(**values)


def drive_lap(profile,lap=0,duration=20000,high=True):
    events=[]
    for i in range(200):
        p=i/200
        s=driving(lap*30+i*duration/200000,lap=lap,lap_ms=int(p*duration),progress=p,x=p*1000,
            rpm=7900 if high and .2<=p<.4 else 5000)
        events.extend(profile.observe(s,'understeer' if .5<=p<.6 else None))
    return events,profile.finish_lap(duration,True,True)


def test_near_limit_holds_give_retrospective_feedback_once(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    events=[]
    for i in range(30):events+=profile.observe(driving(i*.1))
    assert len(events)==1
    assert events[0][1]=="You held gear 3 near the rev limit. Try shifting a little earlier next time."
    assert profile.snapshot(driving())['current_lap']['late_shifts']==1
    assert profile.snapshot(driving())['current_lap']['high_rev_seconds']>2.5


def test_rev_warnings_require_known_ceiling_load_and_live_driving(tmp_path):
    for condition in ({'rpm_limit_known':False},{'throttle':.1},{'status':'replay'},{'in_pit':True},{'speed':0}):
        profile=DrivingProfile(tmp_path,IDENTITY)
        events=[]
        for i in range(20):events+=profile.observe(driving(i*.1,**condition))
        assert not events


def test_neutral_dwell_is_only_a_possible_missed_shift(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    profile.observe(driving(rpm=5000))
    events=[]
    for i in range(1,15):events+=profile.observe(driving(i*.1,gear=0,rpm=7000))
    assert len(events)==1 and 'Possible missed shift' in events[0][1]
    assert profile.snapshot(driving())['current_lap']['missed_shifts']==1


def test_normal_shift_or_neutral_on_reconnect_is_not_a_missed_shift(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    assert not profile.observe(driving())
    assert not profile.observe(driving(.1,gear=0))
    assert not profile.observe(driving(.2,gear=4))
    profile.observe(driving(.3,status='paused'))
    for i in range(4,20):assert not profile.observe(driving(i*.1,gear=0,rpm=7000))


def test_profile_sections_persist_and_repeated_habits_are_location_specific(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    _,first=drive_lap(profile)
    assert first['encouragement'] is None
    _,second=drive_lap(profile,lap=1,duration=19000)
    assert '1.00 seconds quicker' in second['encouragement']
    assert any(s['high_rev_laps']==2 for s in profile.snapshot(driving())['hotspots'])
    loaded=DrivingProfile(tmp_path,IDENTITY)
    snapshot=loaded.snapshot(driving(progress=.73))
    assert snapshot['laps']==2 and snapshot['clean_laps']==2
    assert snapshot['current_section']==15
    assert loaded.data['sections'][0]['best_ms']==950
    assert DrivingProfile(tmp_path,('demo',*IDENTITY[1:])).data['laps']==0
    assert DrivingProfile(tmp_path,('ac','other_car',*IDENTITY[2:])).data['laps']==0


def test_less_rev_time_encouragement_requires_comparable_observation_coverage(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    drive_lap(profile)
    _,report=drive_lap(profile,lap=1,high=False)
    assert 'fewer seconds near the rev ceiling' in report['encouragement']
    profile.observe(driving(61,rpm=5000))
    report=profile.finish_lap(20000,True,False)
    assert report['encouragement'] is None


def test_partial_lap_does_not_create_a_profile_baseline(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    for i in range(15):profile.observe(driving(i*.1))
    assert profile.finish_lap(20000,False,False) is None
    assert profile.data['laps']==0 and not profile.path.exists()


def test_lost_positions_and_contacts_are_recorded_at_track_location(tmp_path):
    profile=DrivingProfile(tmp_path,IDENTITY)
    s=driving(progress=.42)
    profile.record_race_event('overtake',s)
    profile.record_race_event('position_lost',s,-2)
    profile.record_race_event('incident',s,incident_kind='damage_increase')
    profile.record_race_event('incident',s,incident_kind='possible_spin')
    totals=profile.snapshot(s)['current_lap']
    assert totals['passes']==1 and totals['positions_lost']==2
    assert totals['contacts']==1 and totals['spins']==1
