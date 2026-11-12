/* Complete releases, shared immutable files. Only verified changes cross the network. */
const BUILD='__BUILD__', VERSION='__VERSION__';
const SCOPE=new URL(self.registration.scope), PREFIX='bronepehota:'+SCOPE.pathname+':';
const RELEASES=PREFIX+'release:', CACHE=RELEASES+BUILD;
const ASSETS=PREFIX+'assets', IMAGES=PREFIX+'images';
const url=path=>new URL(path,SCOPE), blobKey=hash=>url('__offline__/sha256/'+hash);
const MANIFEST=url('__manifest__'), READY=url('__ready__');
let progress=null,lastReport=0,manifestPromise;
const inFlight=new Map();
const pause=ms=>new Promise(resolve=>setTimeout(resolve,ms));
async function report(force=false){
  if(!progress||(!force&&Date.now()-lastReport<500))return;
  lastReport=Date.now();
  const message={type:'OFFLINE_PROGRESS',build:BUILD,...progress};
  for(const client of await self.clients.matchAll({type:'window',includeUncontrolled:true}))client.postMessage(message);
}
async function matchesHash(bytes,hash){
  const digest=await crypto.subtle.digest('SHA-256',bytes);
  return [...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('')===hash;
}
async function verified(response,hash){return !!response?.ok&&await matchesHash(await response.clone().arrayBuffer(),hash);}
async function download(path,hash){
  for(let attempt=0;attempt<3;attempt++){
    const controller=new AbortController();let timer,receiving=0,reader;
    const track=!!hash&&progress?.phase==='downloading';
    const alive=()=>{clearTimeout(timer);timer=setTimeout(()=>controller.abort(),30000);};
    alive();
    try{
      const response=await fetch(url(path),{cache:'no-store',signal:controller.signal});
      if(!response.ok)throw new Error('Resource unavailable: '+path);
      // The deadline measures inactivity, not total time: slow PDF downloads can finish.
      reader=response.clone().body?.getReader();const chunks=[];let length=0;
      if(reader)while(true){
        const {done,value}=await reader.read();if(done)break;
        alive();chunks.push(value);length+=value.length;
        if(track){receiving+=value.length;progress.receivingBytes+=value.length;progress.transferredBytes+=value.length;await report();}
      }
      const bytes=new Uint8Array(length);let offset=0;
      for(const chunk of chunks){bytes.set(chunk,offset);offset+=chunk.length;}
      if(hash&&!await matchesHash(bytes,hash))throw new Error('Release asset changed: '+path);
      return response;
    }catch(error){if(attempt===2)throw error;}
    finally{clearTimeout(timer);reader?.releaseLock();if(track)progress.receivingBytes-=receiving;}
    await pause(300*(attempt+1));
  }
}
async function putRequired(cache,key,response){
  try{await cache.put(key,response.clone());}
  catch(error){
    if(error.name!=='QuotaExceededError')throw error;
    // Optional enlargements can be reloaded; never evict an active base release.
    await caches.delete(IMAGES);
    await cache.put(key,response.clone());
  }
}
async function legacyCaches(){
  const result=[];
  for(const name of await caches.keys()){
    if(!name.startsWith(PREFIX)||name.startsWith(RELEASES)||[ASSETS,IMAGES].includes(name))continue;
    const cache=await caches.open(name);
    // Even an interrupted legacy cache is reusable after each file passes its hash check.
    result.push({name,cache});
  }
  return result;
}
async function legacyFile(path,hash,legacy){
  for(const {cache} of legacy){
    const response=await cache.match(url(path));
    if(await verified(response,hash))return response;
  }
}
async function parallel(items,fn){
  let cursor=0,error;
  await Promise.all(Array.from({length:Math.min(6,items.length)},async()=>{
    while(!error&&cursor<items.length){
      const item=items[cursor++];
      try{await fn(item);}catch(e){error=e;}
    }
  }));
  // All writes finish before failure is reported; verified files remain resumable.
  if(error)throw error;
}
function validateManifest(manifest){
  if(manifest.build!==BUILD||!Array.isArray(manifest.files)||!manifest.files.length)throw new Error('Release changed during installation');
  if(new Set(manifest.files).size!==manifest.files.length)throw new Error('Duplicate release paths');
  for(const path of manifest.files){
    if(typeof path!=='string'||path.startsWith('/')||path.includes('..')||/[?#\\]/.test(path)||url(path).href!==SCOPE.href+path||!/^[a-f0-9]{64}$/.test(manifest.hashes?.[path]))throw new Error('Invalid release path or hash');
  }
}
async function release(){
  return manifestPromise||(manifestPromise=(async()=>{
    const response=await (await caches.open(CACHE)).match(MANIFEST);
    if(!response)throw new Error('Release manifest missing');
    return response.json();
  })().catch(error=>{manifestPromise=null;throw error;}));
}
async function optionalEntries(manifest){
  const hash=manifest.hashes['assets/catalog-large.json'];
  const response=hash&&await (await caches.open(ASSETS)).match(blobKey(hash));
  return response?response.json():{};
}
self.addEventListener('install',event=>event.waitUntil((async()=>{
  progress={phase:'checking',completed:0,total:0,reused:0,downloaded:0,completedBytes:0,totalBytes:0,receivingBytes:0,transferredBytes:0};
  await report(true);
  try{
    const manifest=await (await download('precache.json')).json();
    validateManifest(manifest);
    const metadata=await caches.open(CACHE),assets=await caches.open(ASSETS),legacy=await legacyCaches();
    // Publish references before inserting blobs, so concurrent cleanup can protect them.
    await metadata.put(MANIFEST,Response.json({...manifest,createdAt:Date.now()}));
    progress.phase='downloading';progress.total=manifest.files.length;
    progress.totalBytes=manifest.files.reduce((n,path)=>n+(manifest.sizes?.[path]||1),0);
    await report(true);
    await parallel(manifest.files,async path=>{
      const hash=manifest.hashes[path],key=blobKey(hash);
      let response=await assets.match(key);
      if(response)progress.reused++;
      else{
        response=await legacyFile(path,hash,legacy);
        if(response)progress.reused++;
        else{response=await download(path,hash);progress.downloaded++;}
        await putRequired(assets,key,response);
      }
      progress.completed++;progress.completedBytes+=manifest.sizes?.[path]||1;
      await report();
    });
    // Migrate only enlargements already viewed in the old format. Never download them here.
    if(legacy.length){
      const optional=await optionalEntries(manifest),images=await caches.open(IMAGES);
      const paths=new Set();
      for(const {cache} of legacy)for(const request of await cache.keys()){
        const path=new URL(request.url).pathname.slice(SCOPE.pathname.length);
        if(optional[path])paths.add(path);
      }
      await parallel([...paths],async path=>{
        const hash=optional[path].sha256,key=blobKey(hash);
        if(await images.match(key))return;
        const response=await legacyFile(path,hash,legacy);
        if(response)try{await images.put(key,response);}catch{/* Optional; the small image remains available. */}
      });
    }
    await metadata.put(READY,Response.json({build:BUILD,version:VERSION,installedAt:Date.now()}));
    progress.phase='ready';await report(true);
  }catch(error){
    progress.phase='failed';progress.reason=error.name==='QuotaExceededError'?'storage':'download';await report(true);
    // The active release is untouched. Keep verified blobs for the next attempt.
    throw error;
  }
})()));
async function cleanup(){
  if(self.registration.installing)return;
  const assets=await caches.open(ASSETS),images=await caches.open(IMAGES);
  // Snapshot keys first: blobs added by a later installer cannot enter this deletion set.
  const assetKeys=await assets.keys(),imageKeys=await images.keys(),releases=[];
  for(const name of await caches.keys())if(name.startsWith(RELEASES)){
    const cache=await caches.open(name),entry=await cache.match(MANIFEST),ready=await cache.match(READY);
    if(entry)releases.push({name,manifest:await entry.json(),ready:ready&&await ready.json()});
  }
  const newest=items=>items.reverse().sort((a,b)=>(b.ready?.installedAt||b.manifest.createdAt||0)-(a.ready?.installedAt||a.manifest.createdAt||0))[0];
  const keep=new Set([CACHE,newest(releases.filter(r=>r.ready&&r.name!==CACHE))?.name,newest(releases.filter(r=>!r.ready))?.name]);
  const baseHashes=new Set(),imageHashes=new Set();
  for(const entry of releases.filter(r=>keep.has(r.name))){
    Object.values(entry.manifest.hashes).forEach(h=>baseHashes.add(blobKey(h).href));
    Object.values(await optionalEntries(entry.manifest)).forEach(e=>imageHashes.add(blobKey(e.sha256).href));
  }
  for(const {name} of releases)if(!keep.has(name)){
    if(self.registration.installing)return;
    await caches.delete(name);
  }
  for(const {name} of await legacyCaches()){
    if(self.registration.installing)return;
    await caches.delete(name);
  }
  for(const [cache,keys,hashes] of [[assets,assetKeys,baseHashes],[images,imageKeys,imageHashes]])for(const key of keys){
    if(self.registration.installing)return;
    if(!hashes.has(key.url))await cache.delete(key);
  }
}
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  if(!await (await caches.open(CACHE)).match(READY))throw new Error('Incomplete release');
  await self.clients.claim();
  // Maintenance must never turn a verified installation into a failed activation.
  try{await cleanup();}catch{/* Retry maintenance on the next successful release. */}
})()));
self.addEventListener('message',event=>{
  if(event.data?.type==='ACTIVATE')event.waitUntil((async()=>{
    if(await (await caches.open(CACHE)).match(READY))await self.skipWaiting();
  })());
  if(event.data?.type==='STATUS')event.waitUntil((async()=>{
    const ready=await (await caches.open(CACHE)).match(READY);
    event.source?.postMessage({type:'OFFLINE_STATUS',ready:!!ready,version:VERSION,build:BUILD});
    if(progress)event.source?.postMessage({type:'OFFLINE_PROGRESS',build:BUILD,...progress});
  })());
});
async function cachedFile(path,hash,optional=false){
  const name=optional?IMAGES:ASSETS,key=blobKey(hash),cache=await caches.open(name),hit=await cache.match(key);
  if(hit)return hit;
  const id=name+hash;
  if(!inFlight.has(id))inFlight.set(id,(async()=>{
    const response=await download(path,hash);
    if(optional){try{await cache.put(key,response.clone());}catch{/* Keep the base release at quota. */}}
    else await putRequired(cache,key,response);
    return response;
  })().finally(()=>inFlight.delete(id)));
  return (await inFlight.get(id)).clone();
}
self.addEventListener('fetch',event=>{
  const request=event.request,requested=new URL(request.url);
  if(request.method!=='GET'||requested.origin!==SCOPE.origin||!requested.pathname.startsWith(SCOPE.pathname))return;
  if(/\/(sw\.js|precache\.json|build\.json)$/.test(requested.pathname))return;
  event.respondWith((async()=>{
    const path=requested.pathname.slice(SCOPE.pathname.length)+(requested.pathname.endsWith('/')?'index.html':'');
    const manifest=await release(),hash=manifest.hashes[path];
    if(hash){try{return await cachedFile(path,hash);}catch{return Response.error();}}
    if(path.startsWith('assets/units/large/')){
      const entry=(await optionalEntries(manifest))[path];
      if(entry){
        try{return await cachedFile(path,entry.sha256,true);}
        catch{return await (await caches.open(ASSETS)).match(blobKey(manifest.hashes[entry.fallback]))||Response.error();}
      }
    }
    try{return await fetch(request);}catch{
      if(request.mode==='navigate')return await (await caches.open(ASSETS)).match(blobKey(manifest.hashes['404.html']))||Response.error();
      return Response.error();
    }
  })());
});
