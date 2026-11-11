/* Atomic, versioned offline releases. Old tabs remain on the previous release until update is accepted. */
const BUILD='__BUILD__', VERSION='__VERSION__';
const PREFIX='bronepehota:'+new URL(self.registration.scope).pathname+':';
const CACHE=PREFIX+BUILD;
self.addEventListener('install',event=>event.waitUntil((async()=>{
  const response=await fetch(new URL('precache.json',self.registration.scope),{cache:'no-store'});
  if(!response.ok)throw new Error('Manifest unavailable');
  const manifest=await response.json();
  if(manifest.build!==BUILD)throw new Error('Release changed during installation');
  const cache=await caches.open(CACHE);
  try{
    for(let i=0;i<manifest.files.length;i+=6){
      await Promise.all(manifest.files.slice(i,i+6).map(async path=>{
        const request=new Request(new URL(path,self.registration.scope),{cache:'reload'});
        const asset=await fetch(request);
        if(!asset.ok)throw new Error('Incomplete offline release: '+path);
        const digest=await crypto.subtle.digest('SHA-256',await asset.clone().arrayBuffer());
        const hash=[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
        if(hash!==manifest.hashes[path])throw new Error('Release asset changed: '+path);
        await cache.put(request,asset);
      }));
    }
    await cache.put(new URL('__ready__',self.registration.scope),new Response(JSON.stringify({build:BUILD,version:VERSION})));
  }catch(error){await caches.delete(CACHE);throw error;}
})()));
self.addEventListener('activate',event=>event.waitUntil((async()=>{
  const cache=await caches.open(CACHE);
  if(!await cache.match(new URL('__ready__',self.registration.scope)))throw new Error('Incomplete cache');
  for(const name of await caches.keys())if(name.startsWith(PREFIX)&&name!==CACHE)await caches.delete(name);
  await self.clients.claim();
})()));
self.addEventListener('message',event=>{
  if(event.data?.type==='ACTIVATE')self.skipWaiting();
  if(event.data?.type==='STATUS')event.waitUntil((async()=>{
    const cache=await caches.open(CACHE), ready=await cache.match(new URL('__ready__',self.registration.scope));
    event.source?.postMessage({type:'OFFLINE_STATUS',ready:!!ready,version:VERSION,build:BUILD});
  })());
});
self.addEventListener('fetch',event=>{
  const request=event.request,url=new URL(request.url),scope=new URL(self.registration.scope);
  if(request.method!=='GET'||url.origin!==scope.origin||!url.pathname.startsWith(scope.pathname))return;
  if(/\/(sw\.js|precache\.json|build\.json)$/.test(url.pathname))return;
  event.respondWith((async()=>{
    const key=new URL(url);key.search='';key.hash='';
    if(key.pathname.endsWith('/'))key.pathname+='index.html';
    const cache=await caches.open(CACHE),hit=await cache.match(key);
    if(hit)return hit;
    const path=key.pathname.slice(scope.pathname.length);
    if(path.startsWith('assets/units/large/')){
      const manifest=await cache.match(new URL('assets/catalog-large.json',scope));
      const entry=manifest&&(await manifest.json())[path];
      if(entry){
        try{
          const image=await fetch(request);
          if(!image.ok)throw new Error('Image unavailable');
          const digest=await crypto.subtle.digest('SHA-256',await image.clone().arrayBuffer());
          const hash=[...new Uint8Array(digest)].map(b=>b.toString(16).padStart(2,'0')).join('');
          if(hash!==entry.sha256)throw new Error('Image changed');
          // Optional images must not make the complete base cache unusable at quota.
          try{await cache.put(key,image.clone());}catch{/* Show the downloaded image without storing it. */}
          return image;
        }catch{
          return await cache.match(new URL(entry.fallback,scope))||Response.error();
        }
      }
    }
    try{return await fetch(request);}catch(error){
      if(request.mode==='navigate')return await cache.match(new URL('404.html',self.registration.scope))||Response.error();
      return Response.error();
    }
  })());
});
