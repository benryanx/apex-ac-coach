import test from 'node:test';
import assert from 'node:assert/strict';
import {CoachRadio, groupNotes, commentary, surname} from '../web/coaching.mjs';

const straight={status:'live',speed:150,brake:0,steer:.01,in_pit:false};
const cue=(kind='understeer',extra={})=>({id:'example',kind,text:'Possible front slip on entry.',speak:true,...extra});

test('routine advice waits until after a corner',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);
  assert.equal(radio.next({...straight,brake:.7,steer:.3},1000),null);
  assert.match(radio.next(straight,3000),/Possible front slip/);
});
test('driver speech takes priority and stale advice is discarded',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);radio.heardUser(1000);
  assert.equal(radio.next(straight,2000),null);
  assert.equal(radio.next(straight,10000),null);
});
test('new output leaves a pause before another routine call',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);radio.heardEngineer(1500);
  assert.equal(radio.next(straight,2000),null);
  assert.ok(radio.next(straight,4000));
});
test('the same handling tip cannot repeat every few corners',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);assert.ok(radio.next(straight,0));
  radio.enqueue(cue(),30000);assert.equal(radio.next(straight,30000),null);
  radio.enqueue(cue(),76000);assert.ok(radio.next(straight,76000));
});
test('minor or unbenchmarked sector readouts stay on the dashboard',()=>{
  const radio=new CoachRadio();
  radio.enqueue(cue('sector',{text:'Sector 1: 20.55.'}),0);
  assert.equal(radio.next(straight,0),null);
  radio.enqueue(cue('sector',{facts:{delta_ms:-30}}),1000);
  assert.equal(radio.next(straight,1000),null);
  radio.enqueue(cue('sector',{text:'Sector one improved.',facts:{delta_ms:-250}}),2000);
  assert.match(radio.next(straight,2000),/Sector one improved/);
});
test('quiet mode preserves incidents and drops routine chatter',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0,true);
  radio.enqueue(cue('incident',{text:'New damage.'}),0,true);
  assert.match(radio.next({...straight,brake:.8},0),/New damage/);
  assert.equal(radio.next(straight,30000),null);
});
test('old queued calls cannot escape after telemetry disconnects',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);
  assert.equal(radio.next({...straight,status:'disconnected'},1000),null);
  assert.equal(radio.next(straight,1500),null);
});
test('notes group repeated handling observations without hiding incidents',()=>{
  const grouped=groupNotes([cue(),cue(),cue('incident'),cue('understeer',{lap:2})]);
  assert.equal(grouped.length,3);assert.equal(grouped[0].observations,2);
  assert.equal(grouped[1].kind,'incident');assert.equal(grouped[2].lap,2);
});
test('voice gets an observation and speaking context instead of just a script',()=>{
  const text=commentary(cue('lap',{text:'Lap 2, 0.3 seconds faster.'}));
  assert.match(text,/conversational debrief/);assert.match(text,/0.3 seconds faster/);
});

test('race position calls can follow routine advice without increasing routine frequency',()=>{
  const radio=new CoachRadio();radio.enqueue(cue(),0);assert.ok(radio.next(straight,0));
  radio.enqueue(cue('position_lost',{text:'Lost one spot. P5.'}),4000);
  assert.match(radio.next(straight,4000),/Lost one spot/);
  radio.enqueue(cue('oversteer'),6000);assert.equal(radio.next(straight,6000),null);
});

test('standings-only gains stay silent while actual passes and losses still get a call',()=>{
  const radio=new CoachRadio();
  const gain=cue('position',{text:'Up one place to fourth in the standings.'});
  radio.enqueue(gain,0);
  assert.equal(commentary(gain),null);
  assert.equal(radio.next(straight,1000),null);
  radio.enqueue(cue('overtake',{text:'You passed Jason Cook for fourth.',facts:{driver_name:'Jason Cook',position:4}}),2000);
  assert.equal(radio.next(straight,2000),null);
  assert.match(radio.next(straight,4500),/"passed_surname":"Cook"/);
  radio.enqueue(cue('position_lost',{text:'Down one place to fifth in the standings.'}),7000);
  assert.match(radio.next(straight,7000),/Down one place to fifth/);
  radio.enqueue(cue('understeer'),30000);
  assert.match(radio.next(straight,30000),/Possible front slip/);
});

const pass=(id,name,position=4)=>cue('overtake',{id,text:`You passed ${name} in the BMW M4 for fourth.`,facts:{driver_id:id,driver_name:name,position}});
test('surname extraction keeps hyphens, common compound surnames and single-word aliases',()=>{
  for(const [name,expected] of [['Elfyn Cook','Cook'],['Marvin Renchet','Renchet'],['Jean-Pierre Smith-Jones','Smith-Jones'],['Juan de la Rosa','de la Rosa'],['Ludwig van der Linde','van der Linde'],['Cook, Elfyn','Cook'],['Rival','Rival'],['John Smith Jr.','Smith'],['','']])assert.equal(surname(name),expected);
});
test('three quick confirmed passes become one count with only the fresh next surname',()=>{
  const radio=new CoachRadio();radio.enqueue(pass(1,'Elfyn Cook',5),0);
  assert.equal(radio.next(straight,1000),null);
  radio.enqueue(pass(2,'Marvin Renchet',4),1500);radio.enqueue(pass(3,'Bernard Bensimon',3),3000);
  assert.equal(radio.next(straight,5000),null);
  const cue=radio.next(straight,5500,null,{position:3,opponents_available:true,ahead:{id:4,name:'Jack Brown',position:2}});
  assert.match(cue,/"pass_count":3/);assert.match(cue,/"ahead_surname":"Brown"/);
  assert.doesNotMatch(cue,/Elfyn|Cook|Marvin|Renchet|Bernard|Bensimon|Jack|BMW/);
  assert.equal(radio.next(straight,10000),null);
});
test('a single pass uses only surname; old full-name prose cannot leak into a cue',()=>{
  const radio=new CoachRadio();radio.enqueue(pass(1,'Elfyn Cook'),0);
  const text=radio.next(straight,2500,null,{position:4,opponents_available:true,ahead:{id:4,name:'Jack Brown',position:3}});
  assert.match(text,/"passed_surname":"Cook"/);assert.doesNotMatch(text,/Elfyn|BMW|Brown/);
  const legacy=commentary(cue('overtake',{text:'You passed Elfyn Cook in the BMW M4 for fourth.'}));
  assert.doesNotMatch(legacy,/Elfyn|Cook|BMW/);
});
test('batch suppresses unavailable, inconsistent or already-passed next drivers',()=>{
  const variants=[null,{position:3,opponents_available:false,ahead:{id:4,name:'Jack Brown',position:2}},
    {position:1,opponents_available:true,ahead:{id:4,name:'Jack Brown',position:2}},
    {position:3,opponents_available:true,ahead:{id:4,name:'Jack Brown',position:1}},
    {position:3,opponents_available:true,ahead:{id:2,name:'Marvin Renchet',position:2}}];
  for(const race of variants){
    const radio=new CoachRadio();radio.enqueue(pass(1,'Elfyn Cook'),0);radio.enqueue(pass(2,'Marvin Renchet'),500);
    const text=radio.next(straight,3000,null,race);assert.match(text,/"pass_count":2/);assert.doesNotMatch(text,/"ahead_surname"/);
  }
});
test('pass bursts have a maximum grouping wait and subsequent passes respect radio spacing',()=>{
  const radio=new CoachRadio();
  for(let i=0;i<4;i++)radio.enqueue(pass(i+1,'Driver Cook'),i*1800);
  const text=radio.next(straight,6000);assert.match(text,/"pass_count":4/);
  radio.enqueue(pass(5,'Driver Renchet'),7000);assert.equal(radio.next(straight,10000),null);
  assert.match(radio.next(straight,16000),/"passed_surname":"Renchet"/);
});
test('expired passes and duplicate events do not inflate a fresh summary',()=>{
  const radio=new CoachRadio();radio.enqueue(pass(1,'Elfyn Cook'),0);radio.enqueue(pass(1,'Elfyn Cook'),100);
  radio.enqueue(pass(2,'Marvin Renchet'),11000);
  const text=radio.next(straight,13500);assert.match(text,/"pass_count":1/);assert.match(text,/"passed_surname":"Renchet"/);
  assert.doesNotMatch(text,/"passed_surname":"Cook"/);
});
test('pause discards an unsaid pass batch and urgent incidents do not wait for it',()=>{
  const radio=new CoachRadio();radio.enqueue(pass(1,'Elfyn Cook'),0);radio.enqueue(cue('incident',{text:'New damage.'}),500);
  assert.match(radio.next(straight,500),/New damage/);
  assert.equal(radio.next({...straight,status:'paused'},3000),null);assert.equal(radio.next(straight,4000),null);
});
test('rev feedback remains retrospective even when delivered after the driver has shifted',()=>{
  const radio=new CoachRadio();radio.enqueue(cue('shift',{text:'You held gear 3 near the rev limit. Try shifting a little earlier next time.'}),0);
  assert.equal(radio.next({...straight,gear:3,brake:.5},500),null);
  const text=radio.next({...straight,gear:4,rpm:4500},3000);
  assert.match(text,/recent observed pattern/);assert.match(text,/may already have changed gear/);
  assert.match(text,/Try shifting a little earlier next time/);
});

test('a silent standings change clears old queued race speech and preserves incident alerts',()=>{
  const radio=new CoachRadio();
  radio.enqueue(cue('position_lost',{text:'Down one place to fifth.'}),0);
  radio.enqueue(cue('incident',{text:'New damage.'}),1000);
  radio.enqueue(cue('position',{text:'Up one place to fourth.'}),1500);
  assert.match(radio.next(straight,2000),/New damage/);
  assert.equal(radio.next(straight,4000),null);
});

test('a lost place replaces queued praise about an earlier gain while keeping incident alerts',()=>{
  const radio=new CoachRadio();
  radio.enqueue(cue('overtake',{text:'You passed Jason for fourth.'}),0);
  assert.equal(radio.next({...straight,brake:.8},500),null);
  radio.enqueue(cue('incident',{text:'New damage.'}),1000);
  radio.enqueue(cue('position_lost',{text:'Down one place to fifth in the standings.'}),1500);
  assert.match(radio.next(straight,2000),/New damage/);
  assert.match(radio.next(straight,4000),/Down one place to fifth/);
  assert.equal(radio.next(straight,5000),null);
});

test('clean-exit praise stays quiet in quiet mode and waits for a straight and the normal radio gap',()=>{
  const radio=new CoachRadio();radio.enqueue(cue('clean_exit',{text:'Clean observed exit.'}),0,true);
  assert.equal(radio.next(straight,0),null);
  radio.enqueue(cue('clean_exit',{text:'Clean observed exit.'}),0);
  assert.equal(radio.next({...straight,steer:.3},1000),null);
  assert.match(radio.next(straight,2000),/Clean observed exit/);
  radio.enqueue(cue('clean_exit'),4000);assert.equal(radio.next(straight,4000),null);
  assert.match(commentary(cue('clean_exit')),/Do not call it a perfect corner/);
});
