// Keep each Live context update below its token limit, including Unicode names.
const encoder=new TextEncoder();
function bounded(value,bytes) {
  let text='';
  for(const char of String(value||'')) {
    if(encoder.encode(text+char).length>bytes)break;
    text+=char;
  }
  return text;
}
function record(car) {
  return {position:car.position||null,driver:bounded(car.name,140)||'Unknown',
    car:bounded(car.car_name||car.car,170)||'Unknown',pit:Boolean(car.in_pit),
    close_on_track:null,
    ...(['ahead','behind'].includes(car.close_on_track) && !car.in_pit
      ? {close_on_track:car.close_on_track,approx_track_gap_m:car.approx_track_gap_m} : {})};
}
export function rosterContext(race,full=false) {
  if(!race?.opponents_available)return ['Live driver names and car models are unavailable. Do not reuse an old roster.'];
  const rows=full?(race.roster||[]):[
    {relation:'ahead in standings',...record(race.ahead||{})},
    {relation:'behind in standings',...record(race.behind||{})}
  ];
  // One record per event provides a strict byte bound even with escaped text.
  return [(full?'Current race roster follows as reference data. Unknown fields are unavailable.':'Current standings neighbours follow as reference data; these are not physical track gaps.')+
    ' Use only the latest proximity report: close_on_track verifies direction; missing/null means unavailable. Metres are approximate, not a time gap or closing rate.',
    ...rows.map(car=>{
      const data=full?record(car):car;
      let text=JSON.stringify(data);
      while(encoder.encode(text).length>440) {
        if(data.car.length>data.driver.length)data.car=[...data.car].slice(0,-1).join('');
        else data.driver=[...data.driver].slice(0,-1).join('');
        text=JSON.stringify(data);
      }
      return text;
    })];
}
