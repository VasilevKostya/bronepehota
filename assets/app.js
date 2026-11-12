import{prepareIndex,search,queryTerms,hit,excerpt}from'./search.js';
import{checkOfflineUpdate,activateOfflineUpdate,offlineProgressText}from'./offline-update.js';
const $=(s,r=document)=>r.querySelector(s),$$=(s,r=document)=>[...r.querySelectorAll(s)];
const escapeHtml=s=>s.replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function marked(text,terms){return text.split(/([А-Яа-яЁёA-Za-z0-9]+)/g).map(t=>hit(t,terms)?'<mark>'+escapeHtml(t)+'</mark>':escapeHtml(t)).join('');}
const dialog=$('.chapter-dialog');let opener;
$$('[data-open-chapters]').forEach(b=>b.addEventListener('click',()=>{opener=b;dialog.showModal();$('.dialog-close',dialog).focus();}));
$('.dialog-close')?.addEventListener('click',()=>dialog.close());
dialog?.addEventListener('click',e=>{if(e.target===dialog){const r=dialog.getBoundingClientRect();if(e.clientX<r.left||e.clientX>r.right||e.clientY<r.top||e.clientY>r.bottom)dialog.close();}});
dialog?.addEventListener('close',()=>opener?.focus());
document.addEventListener('keydown',e=>{if((e.ctrlKey||e.metaKey)&&e.key.toLowerCase()==='k'){e.preventDefault();$('#catalog-query, .top-search input')?.focus();}});
const queryInput=$('#rule-query');
if(queryInput){
  let docsPromise=null,timer,seq=0;
  const load=()=>docsPromise||(docsPromise=fetch('assets/search-index.json').then(r=>{if(!r.ok)throw new Error('index');return r.json();}).then(prepareIndex).catch(e=>{docsPromise=null;throw e;}));
  async function run(){const runId=++seq,q=queryInput.value.trim(),terms=queryTerms(q);const info=$('#search-info'),target=$('#search-content');
    const locationUrl=new URL(location.href);q?locationUrl.searchParams.set('q',q):locationUrl.searchParams.delete('q');history.replaceState(null,'',locationUrl);
    if(!q){target.removeAttribute('aria-busy');info.textContent='Ищем по тексту, таблицам и обозначениям.';target.innerHTML='<p>Попробуйте название правила, игровой термин или сокращение.</p><div class="search-suggestions">'+['Тест брони','гранаты','ББ','ремонт','паника'].map(x=>'<a class="button secondary" href="search.html?q='+encodeURIComponent(x)+'">'+escapeHtml(x)+'</a>').join('')+'</div>';return;}
    info.textContent='Ищем…';target.setAttribute('aria-busy','true');
    try{
      const docs=await load();if(runId!==seq)return;const results=search(docs,q);
      info.textContent=results.length?'Найдено разделов: '+results.length+(results.some(x=>x.fuzzy)?' · включая близкие совпадения':''):'По запросу «'+q+'» ничего не найдено';
      target.innerHTML=results.length?'<ol class="search-results">'+results.slice(0,50).map(r=>'<li class="search-result"><div class="search-path">'+String(r.number).padStart(2,'0')+' · '+escapeHtml(r.chapter)+'</div><h2><a href="'+r.url.split('#')[0]+'?highlight='+encodeURIComponent(q)+'#'+r.url.split('#')[1]+'">'+marked(r.title,terms)+'</a></h2><p>'+marked(excerpt(r.text,terms),terms)+'</p></li>').join('')+'</ol>':'<p>Попробуйте более короткий запрос или другое название. Например: «броня», «Д12», «ББ», «прыжок».</p><a href="index.html">Открыть оглавление</a>';
    }catch(e){if(runId!==seq)return;info.textContent='Не удалось загрузить поиск';target.innerHTML='<p>Проверьте соединение или дождитесь сохранения офлайн-версии.</p><button class="button secondary" id="retry-search">Повторить</button>';$('#retry-search').addEventListener('click',run);}
    finally{if(runId===seq)target.removeAttribute('aria-busy');}
  }
  queryInput.value=new URLSearchParams(location.search).get('q')||'';
  $('.search-form').addEventListener('submit',e=>{e.preventDefault();clearTimeout(timer);run();});queryInput.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(run,140);});run();
}
const highlighted=new URLSearchParams(location.search).get('highlight');
if(highlighted){
  const terms=queryTerms(highlighted);const walker=document.createTreeWalker($('.article')||document.createElement('div'),NodeFilter.SHOW_TEXT);const nodes=[];let node;
  while(node=walker.nextNode())if(node.parentElement&&!['SCRIPT','STYLE','MARK'].includes(node.parentElement.tagName)&&node.textContent.trim())nodes.push(node);
  for(const n of nodes){const value=n.textContent;const html=marked(value,terms);if(html.includes('<mark>')){const span=document.createElement('span');span.innerHTML=html;n.replaceWith(...span.childNodes);}}
}
const sections=$$('.rule-section');
if(sections.length){
  const observer=new IntersectionObserver(entries=>{const visible=entries.filter(e=>e.isIntersecting);if(!visible.length)return;const id=visible[0].target.id;$$('.local-toc a').forEach(a=>{const active=a.hash==='#'+id;a.classList.toggle('active',active);if(active)a.setAttribute('aria-current','location');else a.removeAttribute('aria-current');});},{rootMargin:'-145px 0px -55% 0px'});sections.forEach(s=>observer.observe(s));
}
let registration,hadController=!!navigator.serviceWorker?.controller,reloading=false,refreshing=false;
const watchedRegistrations=new WeakSet();
function offlineText(text){$$('[data-offline]').forEach(el=>el.textContent=text);}
function offlineFeedback(text){$$('[data-offline-feedback]').forEach(el=>el.textContent=text);}
function offlineBusy(busy){$$('[data-refresh-offline], [data-update]').forEach(b=>{b.disabled=busy;b.setAttribute('aria-busy',String(busy));});}
function showProgress(data){offlineFeedback(offlineProgressText(data,!!navigator.serviceWorker.controller));}
function failure(){offlineText('Офлайн-версия пока не сохранена');$$('[data-retry]').forEach(b=>b.hidden=false);}
async function setupOffline(){
  if(!('serviceWorker'in navigator)){offlineText('Для чтения без сети скачайте PDF');$$('[data-refresh-offline]').forEach(b=>{b.disabled=true;b.title='Офлайн-режим недоступен в этом браузере';});return;}
  // A saved release is available even while the browser waits for an update network request.
  navigator.serviceWorker.controller?.postMessage({type:'STATUS'});
  try{
    registration=await navigator.serviceWorker.register('sw.js',{updateViaCache:'none'});
    if(!refreshing)offlineBusy(false);
    function waiting(){if(registration.waiting&&navigator.serviceWorker.controller)$('.update-banner').hidden=false;}
    waiting();
    if(!watchedRegistrations.has(registration)){
      watchedRegistrations.add(registration);
      function watchInstall(){const worker=registration.installing;if(!worker)return;worker.postMessage({type:'STATUS'});worker.addEventListener('statechange',()=>{if(worker.state==='installed'){waiting();if(!navigator.serviceWorker.controller)navigator.serviceWorker.ready.then(r=>r.active?.postMessage({type:'STATUS'}));}if(worker.state==='redundant'){if(!navigator.serviceWorker.controller)failure();if(!refreshing)showProgress({phase:'failed'});}});}
      registration.addEventListener('updatefound',watchInstall);watchInstall();
    }
    navigator.serviceWorker.ready.then(ready=>ready.active?.postMessage({type:'STATUS'}));
    // register() already checks the worker. Do not launch a duplicate update.
    return registration;
  }catch{if(!navigator.serviceWorker.controller)failure();if(!refreshing)offlineBusy(false);}
}
navigator.serviceWorker?.addEventListener('message',e=>{
  if(e.source===navigator.serviceWorker.controller&&e.data?.type==='OFFLINE_STATUS'&&e.data.ready){offlineText('Доступно без интернета · '+e.data.version);$$('[data-retry]').forEach(b=>b.hidden=true);}
  if(!refreshing&&e.data?.type==='OFFLINE_PROGRESS'&&[registration?.installing,registration?.waiting].includes(e.source))showProgress(e.data);
});
navigator.serviceWorker?.addEventListener('controllerchange',()=>{if(hadController&&!reloading){reloading=true;location.reload();}else{hadController=true;navigator.serviceWorker.controller?.postMessage({type:'STATUS'});}});
$$('[data-retry]').forEach(b=>b.addEventListener('click',()=>{offlineText('Сохранение для чтения без интернета…');b.hidden=true;setupOffline();}));
async function refreshOffline(){
  if(refreshing)return;
  refreshing=true;offlineBusy(true);offlineFeedback('Проверяем и загружаем обновления…');
  try{
    const current=(registration&&(registration.active||registration.waiting||registration.installing)?registration:null)||await setupOffline();
    if(!current)throw new Error('Offline registration unavailable');
    const next=await checkOfflineUpdate(current,{onProgress:showProgress});
    if(next){
      offlineFeedback('Обновление загружено. Переключаемся…');
      await activateOfflineUpdate(next,navigator.serviceWorker);
    }else{
      navigator.serviceWorker.controller?.postMessage({type:'STATUS'});
      offlineFeedback('Установлена актуальная версия.');
    }
  }catch(error){
    offlineFeedback(error.code==='storage'?offlineProgressText({phase:'failed',reason:'storage'},!!navigator.serviceWorker.controller):registration?.installing?'Загрузка ещё идёт. Можно продолжать пользоваться сайтом.':navigator.serviceWorker.controller?'Не удалось обновить. Сохранённая копия доступна. Нажмите, чтобы повторить.':'Не удалось сохранить. Проверьте соединение и повторите.');
  }finally{refreshing=false;offlineBusy(false);}
}
$$('[data-refresh-offline], [data-update]').forEach(b=>b.addEventListener('click',refreshOffline));
$('[data-dismiss]')?.addEventListener('click',()=>$('.update-banner').hidden=true);
window.addEventListener('online',()=>{if(registration&&!registration.installing&&!registration.waiting)registration.update().catch(()=>{});});
setupOffline();
// Account for wrapped feedback and the device safe area above the fixed mobile bar.
const mobileBar=$('.mobile-bar');
if(mobileBar&&'ResizeObserver'in window)new ResizeObserver(()=>{
  document.documentElement.style.setProperty('--mobile-bar-height',Math.ceil(mobileBar.getBoundingClientRect().height)+'px');
}).observe(mobileBar);
