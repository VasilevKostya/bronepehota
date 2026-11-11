import {stem} from './search.js';

const aliases = {ремонт:'рм',ремонтник:'рм',прыжок:'пр',прыжки:'пр',прыжковый:'пр',
  хантер:'hunter',хеликс:'helix',эрасер:'eraser',вайпер:'viper',раптор:'raptor',
  спайдер:'spider',локуст:'locust',саламандра:'salamander'};
export function normalize(value){
  return String(value).toLocaleLowerCase('ru').normalize('NFKC').replaceAll('ё','е')
    .replace(/d(?=\d)/g,'д').replace(/[^\p{L}\p{N}]+/gu,' ').trim();
}
export function readFilters(params){
  const number = name => {const value=params.get(name);return value!==null&&value.trim()!==''&&Number.isFinite(Number(value))&&Number(value)>=0?String(Number(value)):'';};
  return {q:params.get('q')||'',faction:params.get('faction')||'',type:params.get('type')||'',min:number('min'),max:number('max'),rank:number('rank'),test:params.get('test')==='1'};
}
export function filterParams(filters){
  const params=new URLSearchParams();
  for(const key of ['q','faction','type','min','max','rank'])if(filters[key]!==''&&filters[key]!=null)params.set(key,String(filters[key]));
  if(filters.test)params.set('test','1');return params;
}
export function prepareCatalog(units){
  return units.map(unit=>({...unit,haystack:normalize(unit.search_text+' '+unit.name+' '+unit.aliases.join(' '))}));
}
export function filterCatalog(units,filters){
  const words=normalize(filters.q).split(' ').filter(Boolean).map(word=>aliases[word]||word);
  return units.filter(unit=>{
    if(filters.faction&&unit.faction!==filters.faction)return false;
    if(filters.type&&unit.type!==filters.type)return false;
    if(filters.min!==''&&unit.cost<Number(filters.min))return false;
    if(filters.max!==''&&unit.cost>Number(filters.max))return false;
    if(filters.rank!==''&&!unit.ranks.includes(Number(filters.rank)))return false;
    if(filters.test&&!unit.test)return false;
    const tokens=unit.haystack.split(' ');
    return words.every(word=>{
      if(word==='рм')return tokens.includes('рм');
      if(word==='пр')return tokens.some(token=>/^пр\d*$/.test(token));
      if(/^\d*д\d+$/.test(word))return tokens.some(token=>token===word||(/^д/.test(word)&&new RegExp('^\\d*'+word+'$').test(token)));
      return unit.haystack.includes(word)||(!/\d/.test(word)&&word.length>=5&&tokens.some(candidate=>stem(candidate)===stem(word)));
    });
  });
}
