import ctypes
import math
from dataclasses import replace

import pytest

from coach.engine import CoachEngine
from coach.telemetry import Sample, Physics, Graphics, Static, ACReader, utf16


def sample(p=0, lap=0, **kwargs):
    data = dict(timestamp=lap * 100 + p * 100 + 1, status="live", car="test_car", track="test_track",
        speed=100, progress=p, lap=lap, lap_ms=int(p * 100000), length=5000,
        x=100 * math.cos(p*math.tau), z=100 * math.sin(p*math.tau),
        sector=min(2, int(p * 3)), last_sector_ms=33333)
    data.update(kwargs)
    return Sample(**data)


def complete(engine, lap=0, duration=100000, **kwargs):
    for i in range(100):
        p = i / 100
        engine.update(sample(p, lap, lap_ms=int(p * duration), **kwargs))
    return engine.update(sample(0, lap+1, last_ms=duration))


def test_reference_delta_compares_same_track_position_and_persists(tmp_path):
    engine = CoachEngine(tmp_path)
    result = complete(engine)
    assert result["analysis"]["reference_ms"] == 100000
    assert result["laps"][0]["best"]
    result = engine.update(sample(.5, 1, lap_ms=49000))
    assert result["analysis"]["delta_ms"] == pytest.approx(-1000)
    assert result["analysis"]["speed_delta"] == 0
    reloaded = CoachEngine(tmp_path)
    reloaded.update(sample())
    assert reloaded.reference["time_ms"] == 100000


@pytest.mark.parametrize("incident", [{"tyres_out": 3}, {"in_pit": True}, {"penalty": 1}])
def test_incident_lap_never_replaces_reference(tmp_path, incident):
    engine = CoachEngine(tmp_path)
    complete(engine)
    result = complete(engine, lap=1, duration=90000, **incident)
    assert result["analysis"]["reference_ms"] == 100000
    assert result["laps"][0]["clean"] is False


def test_attaching_mid_lap_does_not_create_partial_reference(tmp_path):
    engine = CoachEngine(tmp_path)
    for i in range(30,100):
        engine.update(sample(i/100))
    result = engine.update(sample(0, 1, last_ms=100000))
    assert result["laps"][0]["partial"]
    assert not engine.reference


def test_reset_and_track_switch_clear_live_lap_state(tmp_path):
    engine = CoachEngine(tmp_path)
    complete(engine)
    engine.update(sample(.5,1))
    engine.update(sample(0,0))
    assert engine.laps == []
    assert engine.reference  # reusable reference for the same car/track
    engine.update(sample(0,0,track="different_track"))
    assert engine.reference is None


@pytest.mark.parametrize("status", ["paused","replay","disconnected","waiting"])
def test_inactive_feed_cannot_generate_driving_cues(tmp_path,status):
    engine = CoachEngine(tmp_path)
    engine.update(sample(.1))
    for i in range(20):
        result = engine.update(sample(.1,timestamp=20+i,status=status,steer=.3,slip=[.1,.1,.7,.7],throttle=.7))
    assert not result["events"]
    assert result["analysis"]["delta_ms"] is None
    assert result["analysis"]["next_zone"] is None


def test_slip_requires_turning_sustained_duration_and_cooldown(tmp_path):
    engine = CoachEngine(tmp_path)
    for n in range(10):
        engine.update(sample(.1+n/1000,timestamp=1+n*.1,steer=.3,slip=[.1,.1,.5,.5],throttle=.8))
    assert [e["kind"] for e in engine.events] == ["oversteer"]
    # Wheelspin on a straight must not create an oversteer classification.
    clean_engine=CoachEngine(tmp_path / "other")
    for n in range(10):
        result=clean_engine.update(sample(.1+n/1000,timestamp=1+n*.1,steer=0,slip=[.1,.1,.5,.5],throttle=.8))
    assert not result["events"]


def test_demo_cannot_load_real_reference(tmp_path):
    engine = CoachEngine(tmp_path)
    complete(engine)
    engine.update(sample(source="demo"))
    assert engine.reference is None


def test_braking_zones_are_learned_not_hardcoded(tmp_path):
    engine=CoachEngine(tmp_path)
    for i in range(100):
        engine.update(sample(i/100,brake=.8 if .2 < i/100 < .3 else 0))
    engine.update(sample(0,1,last_ms=100000))
    assert len(engine.reference["corners"]) == 1
    result=engine.update(sample(.18,1))
    assert result["analysis"]["next_zone"]["distance"] == 150


def test_lap_debrief_takes_priority_over_recent_zone_cue(tmp_path):
    engine=CoachEngine(tmp_path)
    engine.emit('zone','A learned zone is ahead.',100)
    engine.emit('lap','Lap complete.',101,cooldown=0)
    assert engine.events[0]['speak']


def test_handling_pattern_is_not_repeated_several_times_in_one_lap(tmp_path):
    engine=CoachEngine(tmp_path)
    complete(engine,steer=.3,slip=[.5,.5,.1,.1])
    hints=[e for e in engine.events if e['kind']=='understeer']
    assert len(hints)==1
    # It can be discussed again on a later lap rather than suppressed forever.
    for i in range(1,5):
        engine.update(sample(i/100,1,steer=.3,slip=[.5,.5,.1,.1]))
    assert len([e for e in engine.events if e['kind']=='understeer'])==2


def test_sector_without_reference_is_logged_without_automatic_speech(tmp_path):
    engine=CoachEngine(tmp_path)
    engine.update(sample(.32))
    result=engine.update(sample(.34))
    event=next(e for e in result['events'] if e['kind']=='sector')
    assert not event['speak']
    assert event['facts']['delta_ms'] is None


def test_sdk_binary_layout_uses_windows_utf16_and_pack4():
    assert Physics.speed.offset == 28
    assert Physics.slip.offset == 56
    assert Graphics.laps.offset == 132
    assert Graphics.progress.offset == 248
    assert Graphics.coordinates.offset == 252
    assert Static.car.offset == 68
    g=Graphics()
    g.progress=.75
    g.laps=7
    clone=ACReader.snapshot(ctypes.addressof(g), Graphics)
    assert clone.progress==.75 and clone.laps==7
    raw=(ctypes.c_uint16*5)(65,112,101,120,0)
    assert utf16(raw)=="Apex"
