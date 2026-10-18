import test from 'node:test';
import assert from 'node:assert/strict';
import {EngineerAudio,volumeCommand,clampVolume} from '../web/audio.mjs';

test('new default is 50 percent more output gain than the previous 80 percent',()=>{
  const output=new EngineerAudio({});assert.equal(output.percent/80,1.5);
  assert.equal(clampVolume(250),200);assert.equal(clampVolume(-10),0);
});
test('voice volume requests are recognized without changing microphone settings',()=>{
  assert.deepEqual(volumeCommand('Can you turn your volume up please?'),{type:'step',value:10});
  assert.deepEqual(volumeCommand('Volume up!'),{type:'step',value:10});
  assert.deepEqual(volumeCommand('volume down'),{type:'step',value:-10});
  assert.deepEqual(volumeCommand('Apex set your volume to 60 percent'),{type:'set',value:60});
  assert.deepEqual(volumeCommand('turn it down'),{type:'step',value:-10});
  assert.deepEqual(volumeCommand('mute yourself'),{type:'mute'});
  assert.deepEqual(volumeCommand('unmute yourself'),{type:'unmute'});
  assert.equal(volumeCommand('mute the microphone'),null);
  assert.equal(volumeCommand('What does turn your volume up mean?'),null);
});
test('boost routes audio through one gain path and local mute preserves saved volume',async()=>{
  const gains=[],sources=[];
  const context={state:'running',currentTime:0,destination:{},resume:async()=>{},
    createGain:()=>({gain:{setTargetAtTime:value=>gains.push(value)},connect:()=>{}}),
    createDynamicsCompressor:()=>({threshold:{},ratio:{},attack:{},release:{},connect:()=>{}}),
    createMediaStreamSource:()=>{const source={connections:0,disconnected:false,connect(){this.connections++;},disconnect(){this.disconnected=true;}};sources.push(source);return source;}};
  const element={play:async()=>{}};const audio=new EngineerAudio(element,120,()=>context);
  assert.equal(await audio.activate(),true);await audio.attach({id:'first'});
  assert.equal(gains.at(-1),1.2);assert.equal(element.muted,true);assert.equal(sources[0].connections,1);
  audio.setPercent(160);audio.setMuted(true);assert.equal(gains.at(-1),0);assert.equal(audio.percent,160);
  audio.setMuted(false);assert.equal(gains.at(-1),1.6);
  await audio.attach({id:'second'});assert.equal(sources[0].disconnected,true);assert.equal(sources[1].connections,1);
  audio.detach();assert.equal(sources[1].disconnected,true);assert.equal(element.srcObject,null);
});
test('unavailable Web Audio falls back to ordinary bounded playback',async()=>{
  const element={play:async()=>{}};const audio=new EngineerAudio(element,120,()=>{throw new Error('unavailable');});
  assert.equal(await audio.activate(),false);await audio.attach({});
  assert.equal(element.volume,1);assert.equal(audio.boosted,false);
});
