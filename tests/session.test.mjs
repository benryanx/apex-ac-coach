import test from 'node:test';
import assert from 'node:assert/strict';
import {SessionAwareness} from '../web/session.mjs';
import {CoachRadio} from '../web/coaching.mjs';

const state=(overrides={},session_id='one')=>({session_id,telemetry:{
  status:'live',source:'ac',car:'gt3',track:'imola',configuration:'',
  session_type:2,lap:0,lap_ms:0,speed:0,brake:0,steer:0,in_pit:false,flag:0,
  ...overrides}});

test('connection introduces Apex without assuming a race or inventing start lights',()=>{
  const session=new SessionAwareness();
  session.prime(state({status:'waiting'}));
  assert.equal(session.current.phase,'waiting');
  assert.equal(session.current.race_started,false);
  assert.match(session.greeting(),/Introduce yourself once as Apex/);
  assert.match(session.greeting(),/ready when you are/);
  session.prime(state());
  assert.equal(session.current.phase,'pre_start');
  assert.equal(session.current.driving_allowed,false);
  assert.equal(session.current.lights_known,false);
  assert.match(session.greeting(),/start is unconfirmed/);
});

test('observing the grid then movement with a running clock yields one restrained start cue',()=>{
  const session=new SessionAwareness();session.prime(state(),0);
  assert.equal(session.observe(state({lap_ms:200,speed:20}),1000),null);
  const cue=session.observe(state({lap_ms:1400,speed:80}),2200);
  assert.equal(cue.kind,'session_stage');assert.equal(cue.phase,'racing');
  assert.equal(session.current.race_started,true);
  assert.match(cue.text,/car has moved away/);
  assert.equal(session.observe(state({lap_ms:3000,speed:100}),4000),null);
});

test('movement alone is not confirmation that the race has started',()=>{
  const session=new SessionAwareness();session.prime(state(),0);
  session.observe(state({speed:20}),2000);
  assert.equal(session.observe(state({speed:30}),4000),null);
  assert.equal(session.current.race_started,false);
  assert.equal(session.current.phase,'driving');
});

test('connecting mid-race and resuming from a pause do not manufacture another start',()=>{
  const session=new SessionAwareness();
  session.prime(state({lap:2,lap_ms:10000,speed:100}),0);
  assert.equal(session.current.phase,'racing');
  assert.match(session.greeting(),/already in a driving session/);
  session.observe(state({status:'paused'}),1000);
  assert.ok(session.observe(state({status:'paused'}),2200));
  session.observe(state({lap:2,lap_ms:10000,speed:100}),3000);
  assert.equal(session.observe(state({lap:2,lap_ms:12000,speed:100}),5000),null);
});

test('pause, a frozen feed and waiting yield one ready acknowledgment, not repeated technical alerts',()=>{
  const session=new SessionAwareness();session.prime(state({lap:1,speed:100}),0);
  session.observe(state({status:'paused'}),1000);
  const cue=session.observe(state({status:'paused'}),2200);
  assert.match(cue.text,/Ready when you are/);
  for(const [i,status] of ['disconnected','waiting','replay'].entries()) {
    session.observe(state({status}),4000+i*3000);
    assert.equal(session.observe(state({status}),5500+i*3000),null);
  }
});

test('practice, pits and a restarted race keep their own stage',()=>{
  const session=new SessionAwareness();
  session.prime(state({session_type:0,speed:100,lap_ms:15000}),0);
  assert.equal(session.current.phase,'driving');assert.equal(session.current.race_started,false);
  session.observe(state({in_pit:true}),1000);
  assert.equal(session.current.phase,'pits');
  session.observe(state({lap:1,lap_ms:15000,speed:100}),2000);
  assert.equal(session.current.phase,'racing');
  session.observe(state({},'two'),3000);
  assert.equal(session.current.phase,'pre_start');assert.equal(session.current.race_started,false);
});

test('session transition must persist rather than announcing a brief status flicker',()=>{
  const session=new SessionAwareness();session.prime(state({lap:1,speed:100}),0);
  session.observe(state({status:'disconnected'}),1000);
  session.observe(state({lap:1,speed:100}),1300);
  assert.equal(session.observe(state({lap:1,speed:100}),3000),null);
});

test('a standby cue can speak with no live driving feed and is discarded once its stage changes',()=>{
  const radio=new CoachRadio();
  const cue={kind:'session_stage',phase:'paused',text:'Ready when you are.',speak:true};
  radio.enqueue({kind:'incident',text:'Old incident.',speak:true},0);
  radio.enqueue(cue,0);
  assert.match(radio.next({status:'paused'},2000,'paused'),/Ready when you are/);
  assert.equal(radio.next(state().telemetry,3000,'pre_start'),null);
  radio.enqueue(cue,4000);
  assert.equal(radio.next(state({speed:100}).telemetry,6000,'racing'),null);
});
