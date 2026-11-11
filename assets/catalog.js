import {readFilters,filterParams,prepareCatalog,filterCatalog} from './catalog-search.js';

const $=selector=>document.querySelector(selector);
const storageKey='bp-catalog-return';
function savedState(){try{return JSON.parse(sessionStorage.getItem(storageKey)||'null');}catch{return null;}}
function saveState(state){try{sessionStorage.setItem(storageKey,JSON.stringify(state));}catch{/* Private browsing may disable storage. URLs still preserve filters. */}}
const form=$('#catalog-form');
if(form){
  const info=$('#catalog-results-info'),retry=$('#catalog-retry'),list=$('#catalog-list');
  const rows=new Map([...list.children].map(row=>[row.dataset.unit,row]));
  let units=[],loading=false,timer;
  const getFilters=()=>readFilters(new URLSearchParams(new FormData(form)));
  function setFilters(filters){for(const [key,value] of Object.entries(filters)){const input=form.elements.namedItem(key);if(!input)continue;if(input.type==='checkbox')input.checked=value;else input.value=value;}}
  function render(updateURL=true){
    const filters=getFilters(),matches=filterCatalog(units,filters),visible=new Set(matches.map(unit=>unit.id));
    for(const [id,row] of rows)row.hidden=!visible.has(id);
    info.textContent=`Показано ${matches.length} из ${units.length}`;
    $('#catalog-empty').hidden=matches.length>0;
    if(updateURL){const query=filterParams(filters).toString();history.replaceState(history.state,'','catalog.html'+(query?'?'+query:''));}
  }
  async function load(){
    if(loading)return;loading=true;retry.hidden=true;info.textContent='Загружаем поиск…';
    try{
      const response=await fetch('assets/catalog-index.json');if(!response.ok)throw new Error('index unavailable');
      units=prepareCatalog(await response.json());
      for(const control of form.querySelectorAll('[disabled]'))control.disabled=false;
      setFilters(readFilters(new URLSearchParams(location.search)));render(false);
      if(form.elements.rank.value||form.elements.test.checked)$('.catalog-more').open=true;
      const state=savedState(),navigation=performance.getEntriesByType('navigation')[0];
      if(state?.url===location.pathname+location.search&&(navigation?.type==='back_forward'||new URLSearchParams(location.search).has('return'))){requestAnimationFrame(()=>scrollTo(0,state.scroll));}
    }catch{
      info.textContent='Поиск пока недоступен. Карточки можно открыть из списка; попробуйте загрузить поиск снова.';retry.hidden=false;
    }finally{loading=false;}
  }
  form.addEventListener('submit',event=>{event.preventDefault();clearTimeout(timer);if(units.length)render();});
  form.addEventListener('input',()=>{clearTimeout(timer);timer=setTimeout(()=>render(),120);});
  form.addEventListener('change',()=>{clearTimeout(timer);render();});
  form.addEventListener('reset',()=>{setTimeout(()=>render(),0);});
  $('[data-clear-catalog]')?.addEventListener('click',()=>{form.reset();$('#catalog-query').focus();});
  retry.addEventListener('click',load);
  function remember(){saveState({url:location.pathname+location.search,scroll:scrollY});}
  list.addEventListener('click',event=>{if(event.target.closest('a'))remember();});
  addEventListener('pagehide',remember);
  addEventListener('popstate',()=>{if(units.length){setFilters(readFilters(new URLSearchParams(location.search)));render(false);}});
  // Mobile filters start compact; values from a shared link remain immediately visible.
  if(matchMedia('(max-width:900px)').matches&&!['faction','type','min','max','rank','test'].some(key=>new URLSearchParams(location.search).has(key)))$('.catalog-filters').open=false;
  load();
}

const back=$('[data-catalog-back]'),state=savedState();
if(back&&state?.url){
  const target=new URL(state.url,location.href);
  if(target.origin===location.origin&&target.pathname===new URL('catalog.html',location.href).pathname){
    target.searchParams.set('return','1');back.href=target.pathname+target.search;
  }
}
// The return marker restores scroll once and is removed from the shareable URL.
if(form&&new URLSearchParams(location.search).has('return')){
  const saved=savedState();
  const restore=()=>{if(saved){scrollTo(0,saved.scroll);const url=new URL(location.href);url.searchParams.delete('return');history.replaceState(history.state,'',url.pathname+url.search);}};
  // Wait for filtering, which changes document height.
  new MutationObserver((_,observer)=>{if(!$('#catalog-query').disabled){observer.disconnect();requestAnimationFrame(restore);}}).observe($('#catalog-query'),{attributes:true,attributeFilter:['disabled']});
}
for(const link of document.querySelectorAll('[data-term]'))link.addEventListener('click',()=>{
  const glossary=$('#glossary');if(glossary)glossary.open=true;
});
const share=$('[data-share-unit]');
share?.addEventListener('click',async event=>{
  event.preventDefault();const url=new URL(share.getAttribute('href'),location.href).href;
  try{await navigator.clipboard.writeText(url);$('[data-copy-status]').textContent='Ссылка скопирована';share.lastChild.textContent='Скопировано';}
  catch{const fallback=$('.copy-link-fallback');fallback.hidden=false;const input=fallback.querySelector('input');input.value=url;input.focus();input.select();$('[data-copy-status]').textContent='Выделите и скопируйте ссылку.';}
});
const table=$('[data-scroll-table]');
if(table){const hint=$('[data-scroll-hint]'),update=()=>{hint.hidden=table.scrollWidth<=table.clientWidth+1;};new ResizeObserver(update).observe(table);update();}
// Keep the native cutout on small screens; request x4 only when visible on desktop.
if(matchMedia('(min-width:901px)').matches){
  const observer=new IntersectionObserver(entries=>{for(const entry of entries)if(entry.isIntersecting){const img=entry.target,small=img.src;observer.unobserve(img);img.addEventListener('error',()=>{img.src=small;},{once:true});img.src=img.dataset.large;}},{rootMargin:'160px'});
  for(const img of document.querySelectorAll('img[data-large]'))observer.observe(img);
}
