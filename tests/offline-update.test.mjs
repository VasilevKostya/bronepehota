import test from 'node:test';
import assert from 'node:assert/strict';
import {checkOfflineUpdate} from '../assets/offline-update.js';

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

test('a ready update is returned after checking the site again',async()=>{
  const worker=new Worker('installed');let checked=false;
  const registration={waiting:worker,async update(){checked=true;}};
  assert.equal(await checkOfflineUpdate(registration),worker);assert.ok(checked);
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
  await assert.rejects(checkOfflineUpdate({installing:worker},{timeoutMs:10}),/timed out/);
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
