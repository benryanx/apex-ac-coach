import test from 'node:test';
import assert from 'node:assert/strict';
import {loadDisplay,presetDisplay} from '../web/display.mjs';

test('sidebar preferences survive reload with disabled and collapsed panels',()=>{
  const config=presetDisplay('race');
  config.preset='custom';config.widgets.telemetry=false;config.collapsed.map=true;
  config.parts.volume=false;config.transparent=false;config.opacity=75;
  assert.deepEqual(loadDisplay(JSON.stringify(config)),config);
});
test('damaged or older preferences recover to the balanced driving layout',()=>{
  for(const raw of [null,'broken','{}','{"version":99}'])assert.deepEqual(loadDisplay(raw),presetDisplay());
  const saved=loadDisplay(JSON.stringify({version:1,preset:'untrusted',density:'tiny',widgets:{pace:false,map:'false',unknown:true},opacity:999}));
  assert.equal(saved.widgets.pace,false);assert.equal(saved.widgets.map,true);
  assert.equal(saved.widgets.unknown,undefined);assert.equal(saved.opacity,100);
});
