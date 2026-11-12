import test from 'node:test';
import assert from 'node:assert/strict';
import {checkOfflineUpdate,activateOfflineUpdate,offlineProgressText} from '../assets/offline-update.js';

class Worker extends EventTarget{
  constructor(state='installing'){super();this.state=state;this.listeners=new Set();}
  addEventListener(type,fn){super.addEventListener(type,fn);this.listeners.add(fn);}
  removeEventListener(type,fn){super.removeEventListener(type,fn);this.listeners.delete(fn);}
  change(state){this.state=state;this.dispatchEvent(new Event('statechange'));}
}
const tick=()=>new Promise(resolve=>setImmediate(resolve));

test('manual check contacts the site and reports an unchanged release',async()=>{
  let calls=0;
  const registration={async update(){calls++;}};
  assert.equal(await checkOfflineUpdate(registration),null);
  assert.equal(calls,1);
});

test('manual update waits for the complete installation before offering activation',async()=>{
  const worker=new Worker();let finished=false;
  const registration={async update(){this.installing=worker;}};
  const result=checkOfflineUpdate(registration).then(next=>{finished=true;return next;});
  await tick();assert.equal(finished,false);
  registration.installing=null;registration.waiting=worker;worker.change('installed');
  assert.equal(await result,worker);assert.equal(worker.listeners.size,0);
});

test('an already ready update switches immediately without another network check',async()=>{
  const worker=new Worker('installed');let checked=false;
  const registration={waiting:worker,async update(){checked=true;}};
  assert.equal(await checkOfflineUpdate(registration),worker);assert.equal(checked,false);
});

test('a background download is awaited without launching another update',async()=>{
  const worker=new Worker();
  const registration={installing:worker,update(){throw new Error('Duplicate update');}};
  const result=checkOfflineUpdate(registration);
  registration.waiting=worker;registration.installing=null;worker.change('installed');
  assert.equal(await result,worker);
});

test('a failed or partial installation cannot be activated',async()=>{
  const worker=new Worker();
  const result=checkOfflineUpdate({installing:worker});
  worker.change('redundant');
  await assert.rejects(result,/installation failed/);assert.equal(worker.listeners.size,0);
});

test('a failed network check is retryable without deleting the active release',async()=>{
  const active=new Worker('activated');let offline=true;
  const registration={active,async update(){if(offline)throw new Error('network offline');}};
  await assert.rejects(checkOfflineUpdate(registration),/network offline/);
  assert.equal(registration.active,active);offline=false;
  assert.equal(await checkOfflineUpdate(registration),null);
});

test('stalled checks and installations time out and clean up their listeners',async()=>{
  const worker=new Worker();
  await assert.rejects(checkOfflineUpdate({installing:worker},{installTimeoutMs:10}),/timed out/);
  assert.equal(worker.listeners.size,0);
  let complete;
  await assert.rejects(checkOfflineUpdate({update:()=>new Promise(resolve=>complete=resolve)},{timeoutMs:10}),/timed out/);
  complete();await tick();
});

test('first installation can become active without a waiting worker',async()=>{
  const worker=new Worker();const registration={installing:worker};
  const result=checkOfflineUpdate(registration);
  registration.installing=null;registration.active=worker;worker.change('activating');
  assert.equal(await result,null);
});

const progressEvent=(source,completed)=>Object.assign(new Event('message'),{source,data:{type:'OFFLINE_PROGRESS',phase:'downloading',completed,total:100}});

test('useful installation progress extends the inactivity deadline and is reported',async()=>{
  const worker=new Worker(),serviceWorker=new EventTarget(),registration={installing:worker};
  const values=[];
  const result=checkOfflineUpdate(registration,{installTimeoutMs:80,serviceWorker,onProgress:data=>values.push(data.completed)});
  for(const completed of [1,2,3]){await new Promise(resolve=>setTimeout(resolve,40));serviceWorker.dispatchEvent(progressEvent(worker,completed));}
  registration.installing=null;registration.waiting=worker;worker.change('installed');
  assert.equal(await result,worker);assert.deepEqual(values,[1,2,3]);
});

test('heartbeats without progress and messages from other workers do not hide a stall',async()=>{
  const worker=new Worker(),other=new Worker(),serviceWorker=new EventTarget();let calls=0;
  const result=checkOfflineUpdate({installing:worker},{installTimeoutMs:40,serviceWorker,onProgress:()=>calls++});
  serviceWorker.dispatchEvent(progressEvent(worker,0));
  const interval=setInterval(()=>{serviceWorker.dispatchEvent(progressEvent(worker,0));serviceWorker.dispatchEvent(progressEvent(other,99));},5);
  await assert.rejects(result,/timed out/);clearInterval(interval);
  const previous=calls;serviceWorker.dispatchEvent(progressEvent(worker,3));assert.equal(calls,previous);
});

test('activation waits for the requested controller, including an offline ready worker',async()=>{
  const worker=new Worker('installed'),serviceWorker=new EventTarget();let sent;
  worker.postMessage=data=>sent=data;
  const result=activateOfflineUpdate(worker,serviceWorker);
  assert.deepEqual(sent,{type:'ACTIVATE'});
  serviceWorker.controller=new Worker('activated');serviceWorker.dispatchEvent(new Event('controllerchange'));
  serviceWorker.controller=worker;serviceWorker.dispatchEvent(new Event('controllerchange'));
  await result;assert.equal(worker.listeners.size,0);
});

test('stalled or failed activation is retryable and removes listeners',async()=>{
  const worker=new Worker('installed'),serviceWorker=new EventTarget();worker.postMessage=()=>{};
  await assert.rejects(activateOfflineUpdate(worker,serviceWorker,{timeoutMs:10}),/timed out/);
  assert.equal(worker.listeners.size,0);
  const result=activateOfflineUpdate(worker,serviceWorker);worker.change('redundant');
  await assert.rejects(result,/activation failed/);assert.equal(worker.listeners.size,0);
});

test('progress copy separates first save, update, readiness and retry',()=>{
  const data={phase:'downloading',completed:9,total:10,completedBytes:20,totalBytes:100};
  assert.equal(offlineProgressText(data,true),'Загружаем изменения: 20%.');
  assert.equal(offlineProgressText(data,false),'Сохраняем для чтения без интернета: 20%.');
  assert.equal(offlineProgressText({phase:'ready'},true),'Обновление готово.');
  assert.match(offlineProgressText({phase:'failed'},true),/Сохранённая копия доступна/);
});
