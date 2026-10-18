import test from 'node:test';
import assert from 'node:assert/strict';
import {InstructionUpdater} from '../web/instructions.mjs';
const catalog={version:'1',instructions:['style','scope','driving']};
const deferred=()=>{let resolve;const promise=new Promise(r=>resolve=r);return {promise,resolve};};

test('instructions apply at startup, skip unchanged versions, and refresh after edits',async()=>{
  const sent=[],updater=new InstructionUpdater({load:async()=>catalog,append:async text=>sent.push(text)});
  await updater.apply();assert.deepEqual(sent,catalog.instructions);
  sent.length=0;await updater.apply();assert.deepEqual(sent,[]);
  await updater.apply(true);assert.deepEqual(sent,catalog.instructions);
  sent.length=0;updater.load=async()=>({version:'2',instructions:['updated']});
  await updater.apply();assert.deepEqual(sent,['updated']);
});
test('overlapping refreshes serialize whole instruction sets',async()=>{
  const sent=[],gate=deferred(),started=deferred();let first=true;
  const updater=new InstructionUpdater({load:async()=>catalog,append:async text=>{
    sent.push(text);if(first){first=false;started.resolve();await gate.promise;}
  }});
  const initial=updater.apply();await started.promise;
  const refresh=updater.apply(true);gate.resolve();await Promise.all([initial,refresh]);
  assert.deepEqual(sent,[...catalog.instructions,...catalog.instructions]);
});
test('failed updates stay unready and can recover',async()=>{
  let fail=true,ready=false;
  const updater=new InstructionUpdater({load:async()=>catalog,onReady:v=>ready=v,append:async()=>{if(fail)throw Error('disconnected');}});
  await assert.rejects(updater.apply(),/disconnected/);assert.equal(ready,false);
  fail=false;await updater.apply();assert.equal(ready,true);
});
test('disconnect invalidates pending work before the next session applies instructions',async()=>{
  const sent=[],gate=deferred(),started=deferred();let first=true;
  const updater=new InstructionUpdater({load:async()=>catalog,append:async text=>{
    sent.push(text);if(first){first=false;started.resolve();await gate.promise;}
  }});
  const old=updater.apply();await started.promise;updater.reset();
  updater.load=async()=>({version:'2',instructions:['new session']});
  await updater.apply();gate.resolve();await old;
  assert.deepEqual(sent,['style','new session']);assert.equal(updater.version,'2');
});
