export const WIDGETS={pace:'Lap timing',map:'Track map',race:'Race & nearby drivers',telemetry:'Car telemetry',summary:'Lap debrief',profile:'Driving profile',notes:'Engineer notes',history:'Session history'};
export const PARTS={sectors:'Sector times',reference:'Reference details',inputs:'Pedal & steering bars',tyres:'Tyre temperatures',balance:'Handling estimate',neighbours:'Nearby drivers',roster:'Full driver list',incidents:'Incident detail',upcoming:'Upcoming braking zone',caption:'Radio caption',volume:'Volume slider',session:'Car & session subtitle'};
const common={sectors:true,reference:false,inputs:false,tyres:false,balance:false,neighbours:true,roster:false,incidents:false,upcoming:true,caption:true,volume:true,session:false};
export const PRESETS={
  drive:{label:'Drive',widgets:['pace','map','race','telemetry','summary'],parts:common},
  race:{label:'Race',widgets:['race','pace','map','telemetry','summary'],parts:{...common,roster:true,incidents:true}},
  minimal:{label:'Minimal',widgets:['pace','map'],parts:{...common,sectors:false,caption:false}},
  review:{label:'Review',widgets:['summary','profile','notes','history','pace'],parts:{...common,reference:true}}
};
export function presetDisplay(name='drive',density='compact') {
  const preset=PRESETS[name]||PRESETS.drive;
  return {version:1,preset:PRESETS[name]?name:'drive',order:PRESETS[name]?name:'drive',density,transparent:true,opacity:100,
    widgets:Object.fromEntries(Object.keys(WIDGETS).map(key=>[key,preset.widgets.includes(key)])),
    parts:{...preset.parts},collapsed:{}};
}
export function loadDisplay(raw) {
  const config=presetDisplay();
  try {
    const saved=JSON.parse(raw);
    if(saved?.version!==1)return config;
    if(['drive','race','minimal','review','custom'].includes(saved.preset))config.preset=saved.preset;
    if(PRESETS[saved.order])config.order=saved.order;
    if(['compact','comfortable'].includes(saved.density))config.density=saved.density;
    if(typeof saved.transparent==='boolean')config.transparent=saved.transparent;
    if(Number.isInteger(saved.opacity))config.opacity=Math.max(60,Math.min(100,saved.opacity));
    for(const group of ['widgets','parts','collapsed']) {
      const allowed=group==='parts'?PARTS:WIDGETS;
      for(const key of Object.keys(allowed))if(typeof saved[group]?.[key]==='boolean')config[group][key]=saved[group][key];
    }
  } catch {}
  return config;
}
export function setupDisplay(token) {
  const byId=id=>document.getElementById(id),storageKey='apex-display-v1';
  let saved=null;try{saved=localStorage.getItem(storageKey);}catch{}
  let config=loadDisplay(saved);
  let edited=false,saves=Promise.resolve();
  const dialog=byId('display-settings');
  let regionTimer=null,lastRegions='';
  function updateRegions() {
    if(regionTimer!==null)return;
    regionTimer=setTimeout(()=>{
      regionTimer=null;
      if(!window.pywebview?.api?.set_regions)return;
      const modal=document.querySelector('dialog[open]') || document.body.dataset.radioBusy==='true';
      const rects=(!config.transparent || modal)?null:
        [...document.querySelectorAll('.topbar,.session-heading,.panel,footer,.notice,.display-empty')]
        .filter(node=>!node.hidden && node.getClientRects().length)
        .map(node=>node.getBoundingClientRect())
        .filter(rect=>rect.bottom>0 && rect.top<innerHeight && rect.width>0 && rect.height>0)
        .map(rect=>[Math.max(0,rect.left-2),Math.max(0,rect.top-2),rect.width+4,Math.min(innerHeight,rect.bottom+2)-Math.max(0,rect.top-2)]);
      const signature=JSON.stringify(rects);
      if(signature!==lastRegions) {
        lastRegions=signature;
        window.pywebview.api.set_regions(rects).catch(()=>{lastRegions='';});
      }
    },40);
  }
  function open(){dialog.showModal();}
  byId('layout').onclick=open;
  byId('display-empty-button').onclick=open;
  byId('display-close').onclick=()=>dialog.close();
  byId('display-done').onclick=()=>dialog.close();
  for(const [group,labels] of [['widgets',WIDGETS],['parts',PARTS]]) {
    const target=byId('display-'+group);
    for(const [key,label] of Object.entries(labels)) {
      const row=document.createElement('label');row.className='display-option';
      const input=document.createElement('input');input.type='checkbox';input.dataset.group=group;input.dataset.key=key;
      const text=document.createElement('span');text.textContent=label;
      row.append(input,text);target.append(row);
      input.onchange=()=>{config[group][key]=input.checked;config.preset='custom';apply();};
    }
  }
  for(const panel of document.querySelectorAll('[data-widget]')) {
    const heading=panel.querySelector('.panel-heading');
    if(!heading)continue;
    const key=panel.dataset.widget,button=document.createElement('button');
    button.type='button';button.className='panel-collapse';button.textContent='⌄';
    button.setAttribute('aria-label',`Collapse ${WIDGETS[key]}`);
    button.onclick=()=>{config.collapsed[key]=!config.collapsed[key];apply();};
    heading.append(button);
  }
  function apply(persist=true) {
    document.body.dataset.density=config.density;
    document.documentElement.dataset.transparent=String(config.transparent);
    if(window.pywebview?.api?.set_opacity)window.pywebview.api.set_opacity(config.opacity).catch(()=>{
      byId('display-saved').textContent='Native opacity unavailable';
    });
    for(const panel of document.querySelectorAll('[data-widget]')) {
      const key=panel.dataset.widget;panel.hidden=!config.widgets[key];
      panel.classList.toggle('is-collapsed',Boolean(config.collapsed[key]));
      const button=panel.querySelector('.panel-collapse');
      if(button) {
        button.setAttribute('aria-expanded',String(!config.collapsed[key]));
        button.setAttribute('aria-label',`${config.collapsed[key]?'Expand':'Collapse'} ${WIDGETS[key]}`);
      }
      const order=PRESETS[config.order].widgets.indexOf(key);
      panel.style.order=order<0?20:order;
    }
    for(const node of document.querySelectorAll('[data-display-part]'))node.hidden=!config.parts[node.dataset.displayPart];
    for(const input of dialog.querySelectorAll('input[data-group]'))input.checked=config[input.dataset.group][input.dataset.key];
    byId('display-density').value=config.density;
    byId('display-transparent').checked=config.transparent;
    byId('display-opacity').value=config.opacity;
    byId('display-opacity-value').textContent=`${config.opacity}%`;
    for(const button of dialog.querySelectorAll('[data-preset]'))button.setAttribute('aria-pressed',String(button.dataset.preset===config.preset));
    byId('display-empty').hidden=Object.values(config.widgets).some(Boolean);
    byId('layout').title=`Customize display · ${config.preset==='custom'?'Custom':PRESETS[config.preset].label}`;
    try {localStorage.setItem(storageKey,JSON.stringify(config));byId('display-saved').textContent='Saved on this device';}
    catch {byId('display-saved').textContent='Storage unavailable · changes last until reload';}
    if(persist) {
      edited=true;const snapshot=JSON.stringify(config);
      saves=saves.catch(()=>{}).then(async()=>{
        const response=await fetch('/api/display',{method:'POST',headers:{'Content-Type':'application/json','X-Coach-Token':token},body:snapshot});
        if(!response.ok)throw new Error('Display settings could not be saved');
        byId('display-saved').textContent='Saved on this device';
      }).catch(()=>{byId('display-saved').textContent='Saved for this page · restart Apex to enable permanent saving';});
    }
    updateRegions();
  }
  for(const button of dialog.querySelectorAll('[data-preset]'))button.onclick=()=>{
    const next=presetDisplay(button.dataset.preset,config.density);
    next.transparent=config.transparent;next.opacity=config.opacity;config=next;apply();
  };
  byId('display-density').onchange=event=>{config.density=event.target.value;apply();};
  byId('display-transparent').onchange=event=>{config.transparent=event.target.checked;apply();};
  byId('display-opacity').oninput=event=>{config.opacity=Number(event.target.value);apply();};
  byId('display-reset').onclick=()=>{config=presetDisplay();apply();};
  byId('window-size').onclick=async()=>{
    if(window.pywebview)await window.pywebview.api.set_compact(innerWidth>800);
    else byId('display-saved').textContent='Resize your browser window to change the sidebar width.';
  };
  // Reserve exactly the dock's height, including wrapping captions or hidden controls.
  const dock=document.querySelector('.engineer-panel');
  const observer=new ResizeObserver(()=>document.documentElement.style.setProperty('--radio-height',`${Math.ceil(dock.getBoundingClientRect().height)}px`));
  observer.observe(dock);
  const regionObserver=new ResizeObserver(updateRegions);
  document.querySelectorAll('.topbar,.session-heading,.panel,footer,.notice,.display-empty').forEach(node=>regionObserver.observe(node));
  const modalObserver=new MutationObserver(updateRegions);
  document.querySelectorAll('dialog').forEach(node=>modalObserver.observe(node,{attributes:true,attributeFilter:['open']}));
  modalObserver.observe(document.body,{attributes:true,attributeFilter:['data-radio-busy']});
  addEventListener('scroll',updateRegions,{passive:true});addEventListener('resize',updateRegions);
  window.addEventListener('pywebviewready',()=>apply(false));
  apply(false);
  fetch('/api/display').then(response=>response.ok?response.json():null).then(saved=>{
    if(!edited && saved?.version===1){config=loadDisplay(JSON.stringify(saved));apply(false);}
  }).catch(()=>{});
}
