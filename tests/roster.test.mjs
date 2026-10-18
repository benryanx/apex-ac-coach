import test from 'node:test';
import assert from 'node:assert/strict';
import {rosterContext} from '../web/roster.mjs';

test('standings context carries observed names and cars without implying physical gaps',()=>{
  const race={opponents_available:true,ahead:{position:4,name:'Jamie',car_name:'BMW Z4 GT3'}};
  const parts=rosterContext(race);
  assert.match(parts[0],/not physical track gaps/);
  assert.equal(JSON.parse(parts[1]).driver,'Jamie');
  assert.equal(JSON.parse(parts[1]).car,'BMW Z4 GT3');
  assert.equal(JSON.parse(parts[2]).driver,'Unknown');
});
test('full roster supports fresh questions and context remains bounded with Unicode or escaped names',()=>{
  const roster=Array.from({length:100},(_,i)=>({position:i+1,name:'😀\\"'.repeat(20),car_name:'赛车'.repeat(50),
    close_on_track:'behind',approx_track_gap_m:60}));
  const parts=rosterContext({opponents_available:true,roster},true);
  assert.equal(parts.length,101);
  for(const part of parts.slice(1)) {
    assert.ok(new TextEncoder().encode(part).length<=440);
    assert.ok(JSON.parse(part).position);
  }
});

test('fresh proximity facts preserve track direction and clear old pressure claims when unavailable',()=>{
  const race={opponents_available:true,behind:{position:5,name:'Jack',close_on_track:'behind',approx_track_gap_m:20}};
  let parts=rosterContext(race);
  assert.equal(JSON.parse(parts[2]).close_on_track,'behind');
  assert.equal(JSON.parse(parts[2]).approx_track_gap_m,20);
  delete race.behind.close_on_track;
  parts=rosterContext(race);
  assert.equal(JSON.parse(parts[2]).close_on_track,null);
  race.behind.close_on_track='behind';race.behind.in_pit=true;
  assert.equal(JSON.parse(rosterContext(race)[2]).close_on_track,null);
});
test('an unavailable roster clears old identities rather than inventing cars',()=>{
  assert.match(rosterContext({opponents_available:false,roster:[{name:'Old'}]},true)[0],/Do not reuse an old roster/);
});
