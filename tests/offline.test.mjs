import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {webcrypto,createHash} from 'node:crypto';
const template=fs.readFileSync(new URL('../assets/sw-template.js',import.meta.url),'utf8');
const scope='https://example.org/bronepehota/',prefix='bronepehota:/bronepehota/:';
const hash=x=>createHash('sha256').update(x).digest('hex');
const blob=x=>scope+'__offline__/sha256/'+hash(x);
const key=r=>typeof r==='string'?r:r.url||r.href;

function world(){
  const stores=new Map(),requests=[],messages=[],faults=new Map();
  let offline=false,quota=null,releaseBuild='one',large='large';
  const assets={'index.html':'home','search.html':'search','assets/site.css':'css','assets/search-index.json':'index','book.pdf':'pdf','404.html':'missing','assets/units/small/example.webp':'small'};
  const largePath='assets/units/large/example.webp';
  const updateOptional=()=>assets['assets/catalog-large.json']=JSON.stringify({[largePath]:{sha256:hash(large),fallback:'assets/units/small/example.webp'}});
  updateOptional();
  const manifest=()=>({build:releaseBuild,files:Object.keys(assets),hashes:Object.fromEntries(Object.entries(assets).map(([k,v])=>[k,hash(v)])),sizes:Object.fromEntries(Object.entries(assets).map(([k,v])=>[k,Buffer.byteLength(v)]))});
  const caches={
    async open(name){
      if(!stores.has(name))stores.set(name,new Map());
      const data=stores.get(name);
      return {
        async put(r,v){if(quota?.(name,key(r)))throw Object.assign(new Error('Quota exceeded'),{name:'QuotaExceededError'});data.set(key(r),v.clone());},
        async match(r){return data.get(key(r))?.clone();},
        async keys(){return [...data.keys()].map(k=>new Request(k));},
        async delete(r){return data.delete(key(r));}
      };
    },
    async keys(){return [...stores.keys()];},
    async delete(name){return stores.delete(name);}
  };
  async function fetch(r,options={}){
    const path=key(r).replace(scope,'');requests.push(path);
    if(offline)throw new Error('offline');
    if(faults.has(path)){const result=await faults.get(path)(options);if(result)return result;}
    if(path==='precache.json')return Response.json(manifest());
    if(path===largePath)return new Response(large);
    return new Response(assets[path]||'',{status:path in assets?200:404});
  }
  function worker(build=releaseBuild){
    const listeners={};let claimed=false,activated=false;
    const self={registration:{scope,installing:null},addEventListener:(n,f)=>listeners[n]=f,clients:{async claim(){claimed=true;},async matchAll(){return[{postMessage:m=>messages.push(m)}];}},async skipWaiting(){activated=true;}};
    // Fast deadlines in this harness; fetch still has to observe a real AbortSignal.
    const fastTimer=(fn,ms)=>setTimeout(fn,ms===30000?25:0);
    vm.runInNewContext(template.replaceAll('__BUILD__',build).replaceAll('__VERSION__','0.3'),{self,caches,fetch,URL,Request,Response,crypto:webcrypto,Uint8Array,AbortController,setTimeout:fastTimer,clearTimeout});
    const event=async(name,extra={})=>{const pending=[];listeners[name]({...extra,waitUntil:p=>pending.push(p),respondWith:p=>pending.push(p)});return(await Promise.all(pending))[0];};
    return {event,self,claimed:()=>claimed,activated:()=>activated,read:async path=>event('fetch',{request:new Request(scope+path)})};
  }
  return {stores,caches,assets,requests,messages,faults,manifest,worker,largePath,
    next(build,patch={}){releaseBuild=build;Object.assign(assets,patch);},
    setLarge(value){large=value;updateOptional();},
    setQuota(fn){quota=fn;},
    goOffline(){offline=true;},goOnline(){offline=false;},
    async seedLegacy(patch={},withLarge=false){
      const cache=await caches.open(prefix+'legacy');
      for(const [path,value]of Object.entries({...assets,...patch}))await cache.put(scope+path,new Response(value));
      if(withLarge)await cache.put(scope+largePath,new Response(large));
      await cache.put(scope+'__ready__',Response.json({build:'legacy',version:'0.3'}));
    }
  };
}

test('complete release works offline, including query URLs, PDF and saved status',async()=>{
  const w=world(),worker=w.worker();await worker.event('install');await worker.event('activate');
  assert.ok(worker.claimed());assert.equal(worker.activated(),false);w.goOffline();
  for(const [path,body]of [['','home'],['search.html?q=броня','search'],['assets/search-index.json','index'],['book.pdf','pdf']])assert.equal(await(await worker.read(path)).text(),body);
  let status;await worker.event('message',{data:{type:'STATUS'},source:{postMessage:m=>{if(m.type==='OFFLINE_STATUS')status=m;}}});
  assert.equal(status.ready,true);assert.equal(status.version,'0.3');
});

test('a CSS-only release downloads only CSS, with no copies of unchanged files',async()=>{
  const w=world(),old=w.worker();await old.event('install');await old.event('activate');
  const before=w.stores.get(prefix+'assets').size;w.requests.length=0;w.next('two',{'assets/site.css':'new css'});
  const next=w.worker();await next.event('install');
  assert.deepEqual(w.requests.sort(),['assets/site.css','precache.json']);
  assert.equal(w.stores.get(prefix+'assets').size,before+1);
  assert.equal(await(await old.read('assets/site.css')).text(),'css');
  assert.equal(w.messages.at(-1).downloaded,1);assert.equal(w.messages.at(-1).reused,Object.keys(w.assets).length-1);
  await next.event('activate');w.goOffline();
  assert.equal(await(await next.read('assets/site.css')).text(),'new css');
  assert.equal(await(await next.read('book.pdf')).text(),'pdf');
  assert.equal(await(await old.read('assets/site.css')).text(),'css');
});

test('migration reuses the deployed legacy cache, checks bytes and keeps viewed enlargements',async()=>{
  const w=world();await w.seedLegacy({'assets/site.css':'old css'},true);
  const worker=w.worker();await worker.event('install');
  assert.deepEqual(w.requests.sort(),['assets/site.css','precache.json']);
  assert.ok(w.stores.has(prefix+'legacy'));await worker.event('activate');
  assert.equal(w.stores.has(prefix+'legacy'),false);w.goOffline();
  assert.equal(await(await worker.read(w.largePath)).text(),'large');
  assert.equal(await(await worker.read('book.pdf')).text(),'pdf');
});

test('interrupted legacy storage can be salvaged only after verifying individual files',async()=>{
  const w=world();await w.seedLegacy({'book.pdf':'incomplete bytes'});
  w.stores.get(prefix+'legacy').delete(scope+'__ready__');
  const worker=w.worker();await worker.event('install');
  assert.deepEqual(w.requests.sort(),['book.pdf','precache.json']);
  assert.equal(await(await worker.read('book.pdf')).text(),'pdf');
});

test('interrupted download resumes verified chunks and never activates partial content',async()=>{
  const w=world(),old=w.worker();await old.event('install');await old.event('activate');
  w.next('two',{'index.html':'new home','book.pdf':'new pdf'});
  w.faults.set('book.pdf',()=>new Response('bad',{status:503}));
  const broken=w.worker();await assert.rejects(broken.event('install'));
  await broken.event('message',{data:{type:'ACTIVATE'}});assert.equal(broken.activated(),false);
  await assert.rejects(broken.event('activate'),/Incomplete release/);
  assert.equal(await(await old.read('index.html')).text(),'home');
  assert.equal(w.stores.get(prefix+'release:two').has(scope+'__ready__'),false);
  const downloaded=w.stores.get(prefix+'assets').has(blob('new home'));assert.ok(downloaded);
  w.faults.clear();w.requests.length=0;
  const retry=w.worker();await retry.event('install');await retry.event('activate');
  assert.deepEqual(w.requests.sort(),['book.pdf','precache.json']);
  assert.equal(await(await retry.read('index.html')).text(),'new home');
});

test('hash mismatch or mixed deployment keeps the previous release',async()=>{
  for(const wrongManifest of [false,true]){
    const w=world(),old=w.worker();await old.event('install');await old.event('activate');
    w.next('two',{'index.html':'new home'});
    if(!wrongManifest)w.faults.set('index.html',()=>new Response('wrong bytes'));
    const next=w.worker(wrongManifest?'stale':'two');
    await assert.rejects(next.event('install'));
    await next.event('message',{data:{type:'ACTIVATE'}});assert.equal(next.activated(),false);
    assert.equal(await(await old.read('index.html')).text(),'home');
  }
});

test('temporary HTTP failure retries just that file',async()=>{
  const w=world();let calls=0;
  w.faults.set('book.pdf',()=>++calls===1?new Response('',{status:503}):null);
  await w.worker().event('install');
  assert.equal(calls,2);assert.equal(w.requests.filter(p=>p==='index.html').length,1);
});

test('stalled downloads abort, leave the old cache usable and can resume',async()=>{
  const w=world(),old=w.worker();await old.event('install');await old.event('activate');w.next('two',{'book.pdf':'new pdf'});
  let aborts=0;
  w.faults.set('book.pdf',({signal})=>new Promise((resolve,reject)=>signal.addEventListener('abort',()=>{aborts++;reject(new Error('aborted'));},{once:true})));
  await assert.rejects(w.worker().event('install'));assert.equal(aborts,3);
  assert.equal(await(await old.read('book.pdf')).text(),'pdf');
  w.faults.clear();await w.worker().event('install');
});

test('a slow but advancing response body outlives the inactivity deadline',async()=>{
  const w=world();let offset=0;
  const bytes=new TextEncoder().encode('slow download remains valid');w.assets['book.pdf']=new TextDecoder().decode(bytes);
  w.faults.set('book.pdf',()=>new Response(new ReadableStream({async pull(controller){
    await new Promise(resolve=>setTimeout(resolve,10));
    if(offset===bytes.length)controller.close();else controller.enqueue(bytes.slice(offset,++offset));
  }})));
  const worker=w.worker();await worker.event('install');
  assert.equal(w.requests.filter(p=>p==='book.pdf').length,1);
  assert.equal(await(await worker.read('book.pdf')).text(),w.assets['book.pdf']);
});

test('a response body that stalls after headers is aborted too',async()=>{
  const w=world();let aborts=0;
  w.faults.set('book.pdf',({signal})=>new Response(new ReadableStream({start(controller){
    signal.addEventListener('abort',()=>{aborts++;controller.error(new Error('body aborted'));},{once:true});
  }})));
  await assert.rejects(w.worker().event('install'));assert.equal(aborts,3);
});

test('large images stay optional, are shared across releases, and concurrent views fetch once',async()=>{
  const w=world(),first=w.worker();await first.event('install');await first.event('activate');
  assert.equal(w.requests.includes(w.largePath),false);
  const responses=await Promise.all([first.read(w.largePath),first.read(w.largePath)]);
  assert.deepEqual(await Promise.all(responses.map(r=>r.text())),['large','large']);
  assert.equal(w.requests.filter(p=>p===w.largePath).length,1);
  for(const build of ['two','three','four']){w.next(build,{'assets/site.css':build});const next=w.worker();await next.event('install');await next.event('activate');}
  w.goOffline();assert.equal(await(await w.worker().read(w.largePath)).text(),'large');
});

test('unseen, unavailable and changed enlargements fall back to the current small image',async()=>{
  for(const mode of ['offline','unavailable','wrong-hash']){
    const w=world(),worker=w.worker();await worker.event('install');
    if(mode==='offline')w.goOffline();
    else w.faults.set(w.largePath,()=>new Response('wrong',{status:mode==='unavailable'?503:200}));
    assert.equal(await(await worker.read(w.largePath)).text(),'small');
  }
  const w=world(),first=w.worker();await first.event('install');await first.read(w.largePath);
  w.setLarge('new large');w.next('two');const second=w.worker();await second.event('install');await second.event('activate');w.goOffline();
  assert.equal(await(await second.read(w.largePath)).text(),'small');
});

test('optional image quota failure preserves the complete base release',async()=>{
  const w=world(),worker=w.worker();await worker.event('install');
  w.setQuota(name=>name===prefix+'images');
  assert.equal(await(await worker.read(w.largePath)).text(),'large');w.goOffline();
  assert.equal(await(await worker.read('index.html')).text(),'home');
  assert.equal(await(await worker.read(w.largePath)).text(),'small');
});

test('required quota failure cannot replace or delete the active release',async()=>{
  const w=world(),old=w.worker();await old.event('install');await old.event('activate');await old.read(w.largePath);
  w.next('two',{'book.pdf':'new pdf'});w.setQuota((name,key)=>name===prefix+'assets'&&key===blob('new pdf'));
  const failed=w.worker();await assert.rejects(failed.event('install'),/Quota/);
  assert.equal(w.stores.has(prefix+'images'),false);
  assert.equal(await(await old.read('book.pdf')).text(),'pdf');
  w.setQuota(null);await w.worker().event('install');
});

test('a missing shared file is recovered individually and still checked for integrity',async()=>{
  const w=world(),worker=w.worker();await worker.event('install');
  w.stores.get(prefix+'assets').delete(blob('pdf'));w.requests.length=0;
  assert.equal(await(await worker.read('book.pdf')).text(),'pdf');assert.deepEqual(w.requests,['book.pdf']);
  w.stores.get(prefix+'assets').delete(blob('pdf'));w.faults.set('book.pdf',()=>new Response('wrong'));
  assert.equal((await worker.read('book.pdf')).type,'error');
});

test('cleanup retains current/previous releases and does not touch another app',async()=>{
  const w=world();await w.caches.open('another-app');
  for(const build of ['one','two','three']){
    w.next(build,{'assets/site.css':build});const worker=w.worker();await worker.event('install');await worker.event('activate');
  }
  assert.ok(w.stores.has('another-app'));
  assert.equal(w.stores.has(prefix+'release:one'),false);
  assert.ok(w.stores.has(prefix+'release:two'));assert.ok(w.stores.has(prefix+'release:three'));
  assert.equal(w.stores.get(prefix+'assets').has(blob('one')),false);
  assert.ok(w.stores.get(prefix+'assets').has(blob('two')));
});

test('cleanup defers while a different installation is in progress',async()=>{
  const w=world(),worker=w.worker();await worker.event('install');
  const cache=await w.caches.open(prefix+'assets');await cache.put(blob('future'),new Response('future'));
  worker.self.registration.installing={state:'installing'};await worker.event('activate');
  assert.ok(w.stores.get(prefix+'assets').has(blob('future')));
});
