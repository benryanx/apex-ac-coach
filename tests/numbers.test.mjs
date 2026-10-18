import test from 'node:test';
import assert from 'node:assert/strict';
import {TelemetryNumbers} from '../web/numbers.mjs';

function harness() {
  let clock=0,reduced=false,next=0;
  const frames=new Map(),painted={};
  const numbers=new TelemetryNumbers({now:()=>clock,request:cb=>{frames.set(++next,cb);return next;},cancel:id=>frames.delete(id),reduced:()=>reduced});
  return {numbers,painted,frames,set:(key,value,options)=>numbers.set(key,value,v=>painted[key]=v,options),
    tick:ms=>{clock=ms;const callbacks=[...frames.values()];frames.clear();callbacks.forEach(cb=>cb());},reduce:()=>{reduced=true;}};
}
test('RPM climbs and falls through intermediate readings and lands exactly on target',()=>{
  const h=harness();h.set('rpm',100);assert.equal(h.painted.rpm,100);
  h.set('rpm',1000);h.tick(90);assert.equal(h.painted.rpm,550);
  h.tick(180);assert.equal(h.painted.rpm,1000);assert.equal(h.frames.size,0);
  h.set('rpm',100);h.tick(270);assert.equal(h.painted.rpm,550);
  h.tick(360);assert.equal(h.painted.rpm,100);
});
test('retargeting during animation starts at current reading without jumps or overshoot',()=>{
  const h=harness();h.set('speed',0);h.set('speed',180);h.tick(90);
  assert.equal(h.painted.speed,90);h.set('speed',0);assert.equal(h.painted.speed,90);
  h.tick(180);assert.equal(h.painted.speed,45);h.tick(270);assert.equal(h.painted.speed,0);
});
test('all numbers share one animation frame and duplicate samples do not stall progress',()=>{
  const h=harness();h.set('rpm',100);h.set('fuel',30);h.set('rpm',1000);h.set('fuel',29);
  assert.equal(h.frames.size,1);h.tick(90);h.set('rpm',1000);h.tick(180);
  assert.deepEqual(h.painted,{rpm:1000,fuel:29});assert.equal(h.frames.size,0);
});
test('lap/zone resets snap immediately, missing values cancel old motion',()=>{
  const h=harness();h.set('lap',60000);h.set('lap',60200);h.tick(90);h.set('lap',0,{snap:true});
  assert.equal(h.painted.lap,0);h.set('delta',100);h.set('delta',200);h.set('delta',null);h.tick(180);
  assert.equal(h.painted.delta,null);assert.equal(h.painted.lap,0);
  h.set('lap',200);h.numbers.reset();assert.equal(h.frames.size,0);
  h.set('lap',500);assert.equal(h.painted.lap,500);
});
test('reduced motion snaps both new and in-flight values',()=>{
  const h=harness();h.set('rpm',100);h.set('rpm',1000);h.reduce();h.tick(90);
  assert.equal(h.painted.rpm,1000);h.set('rpm',200);assert.equal(h.painted.rpm,200);assert.equal(h.frames.size,0);
});
