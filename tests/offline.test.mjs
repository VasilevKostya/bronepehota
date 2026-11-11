import test from 'node:test';
import assert from 'node:assert/strict';
import vm from 'node:vm';
import fs from 'node:fs';
import {webcrypto,createHash} from 'node:crypto';
const template=fs.readFileSync(new URL('../assets/sw-template.js',import.meta.url),'utf8');
const scope='https://example.org/bronepehota/';
const hash=x=>createHash('sha256').update(x).digest('hex');
function worker({broken=false,changed=false,largeBroken=false,largeChanged=false,quota=false}={}){
  const listeners={},stores=new Map(),assets={'index.html':'home','search.html':'search','assets/search-index.json':'index','book.pdf':'pdf','404.html':'missing'};
  assets['assets/units/small/example.webp']='small';
  assets['assets/catalog-large.json']=JSON.stringify({'assets/units/large/example.webp':{sha256:hash('large'),fallback:'assets/units/small/example.webp'}});
  const manifest={build:'test',files:Object.keys(assets),hashes:Object.fromEntries(Object.entries(assets).map(([k,v])=>[k,hash(v)]))};
  const key=r=>typeof r==='string'?r:r.url||r.href;
  const caches={async open(name){if(!stores.has(name))stores.set(name,new Map());const data=stores.get(name);return{async put(r,v){if(quota&&key(r).includes('/large/'))throw new Error('Quota exceeded');data.set(key(r),v)},async match(r){return data.get(key(r))?.clone()}}},async keys(){return [...stores.keys()]},async delete(name){return stores.delete(name)}};
  let offline=false,claimed=false,activated=false;
  const self={registration:{scope},addEventListener:(n,f)=>listeners[n]=f,clients:{async claim(){claimed=true}},async skipWaiting(){activated=true}};
  async function fetch(r){if(offline)throw new Error('offline');const path=key(r).replace(scope,'');if(path==='precache.json')return Response.json(manifest);if(path==='assets/units/large/example.webp')return new Response(largeChanged?'changed':'large',{status:largeBroken?503:200});if(broken&&path==='book.pdf')return new Response('',{status:503});return new Response(changed&&path==='search.html'?'changed':assets[path]||'',{status:path in assets?200:404});}
  vm.runInNewContext(template.replaceAll('__BUILD__','test').replaceAll('__VERSION__','0.1'),{self,caches,fetch,URL,Request,Response,crypto:webcrypto,Uint8Array});
  const event=async(name,extra={})=>{let pending;listeners[name]({...extra,waitUntil:p=>pending=p,respondWith:p=>pending=p});return await pending};
  return {event,stores,caches,goOffline:()=>offline=true,claimed:()=>claimed,activated:()=>activated};
}
test('complete release works offline, including search query URLs and PDF',async()=>{
  const w=worker();await w.event('install');await w.event('activate');assert.ok(w.claimed());assert.equal(w.activated(),false);
  w.goOffline();
  for(const [path,body] of [['','home'],['search.html?q=броня','search'],['assets/search-index.json','index'],['book.pdf','pdf']]){
    const response=await w.event('fetch',{request:new Request(scope+path)});assert.equal(await response.text(),body);
  }
  let status;await w.event('message',{data:{type:'STATUS'},source:{postMessage:m=>status=m}});assert.equal(status.ready,true);assert.equal(status.version,'0.1');
});

test('large images are optional, verified, and cached only after a view',async()=>{
  const w=worker();await w.event('install');await w.event('activate');
  const path=scope+'assets/units/large/example.webp';
  assert.equal([...w.stores.values()][0].has(path),false);
  assert.equal(await (await w.event('fetch',{request:new Request(path)})).text(),'large');
  w.goOffline();assert.equal(await (await w.event('fetch',{request:new Request(path)})).text(),'large');
});

test('unseen, unavailable or changed large images fall back to the complete native image',async()=>{
  for(const options of [{offline:true},{largeBroken:true},{largeChanged:true}]){
    const w=worker(options);await w.event('install');if(options.offline)w.goOffline();
    const response=await w.event('fetch',{request:new Request(scope+'assets/units/large/example.webp')});
    assert.equal(await response.text(),'small');
  }
});

test('optional image quota failure preserves the base offline release',async()=>{
  const w=worker({quota:true});await w.event('install');
  assert.equal(await (await w.event('fetch',{request:new Request(scope+'assets/units/large/example.webp')})).text(),'large');
  w.goOffline();assert.equal(await (await w.event('fetch',{request:new Request(scope+'index.html')})).text(),'home');
  assert.equal(await (await w.event('fetch',{request:new Request(scope+'assets/units/large/example.webp')})).text(),'small');
});
test('partial or mismatched release never replaces existing cache',async()=>{
  for(const options of [{broken:true},{changed:true}]){
    const w=worker(options);await w.caches.open('bronepehota:/bronepehota/:previous');
    await assert.rejects(w.event('install'));assert.deepEqual([...w.stores.keys()],['bronepehota:/bronepehota/:previous']);
  }
});
test('update activates only after acceptance and removes only own old cache',async()=>{
  const w=worker();await w.caches.open('another-app');await w.caches.open('bronepehota:/bronepehota/:previous');
  await w.event('install');assert.equal(w.activated(),false);assert.ok(w.stores.has('bronepehota:/bronepehota/:previous'));
  await w.event('message',{data:{type:'ACTIVATE'}});assert.equal(w.activated(),true);await w.event('activate');
  assert.ok(w.stores.has('another-app'));assert.equal(w.stores.has('bronepehota:/bronepehota/:previous'),false);
});
