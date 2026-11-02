const CACHE="gan-david-v13";
const SHELL=["./","./index.html","./manifest.json","./icons/icon-192.png","./icons/icon-512.png"];
self.addEventListener("install",e=>{e.waitUntil(caches.open(CACHE).then(c=>c.addAll(SHELL)).then(()=>self.skipWaiting()));});
self.addEventListener("activate",e=>{e.waitUntil(caches.keys().then(ks=>Promise.all(ks.filter(k=>k!==CACHE).map(k=>caches.delete(k)))).then(()=>self.clients.claim()));});
self.addEventListener("fetch",e=>{
  const u=new URL(e.request.url);
  if(e.request.method!=="GET") return;
  // news and the page: network first, fall back to cache (so the last issue opens even offline)
  e.respondWith(fetch(e.request).then(r=>{ if(r.ok && u.origin===location.origin){ const c=r.clone(); caches.open(CACHE).then(x=>x.put(e.request,c)); } return r; }).catch(()=>caches.match(e.request,{ignoreSearch:true})));
});
