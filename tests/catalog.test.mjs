import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import {readFilters,filterParams,prepareCatalog,filterCatalog} from '../assets/catalog-search.js';
const units=prepareCatalog(JSON.parse(fs.readFileSync(new URL('../dist/assets/catalog-index.json',import.meta.url),'utf8')));
const query=(q,extra={})=>filterCatalog(units,{...readFilters(new URLSearchParams()),q,...extra});

test('catalogue contains exactly the approved 105 source sheets and keeps variants distinct',()=>{
  assert.equal(units.length,105);assert.equal(new Set(units.map(u=>u.id)).size,105);
  assert.equal(units.filter(u=>u.type==='infantry').length,70);
  assert.equal(units.filter(u=>u.type==='hero').length,2);
  assert.equal(units.filter(u=>['vehicle','cavalry'].includes(u.type)).length,33);
  assert.equal(units.some(u=>u.aliases.includes('IMP-23')),false);
  assert.equal(query('Хирдманы').length,2);
});
test('Russian names, ё/е, Latin names, aliases and weapons are searchable',()=>{
  assert.ok(query('ХИРДМАНЫ').length);
  assert.deepEqual(query('наёмники'),query('наемники'));
  assert.equal(query('HUNTER')[0].name,'HUNTER');assert.equal(query('хантер')[0].name,'HUNTER');
  assert.ok(query('SW-01').some(u=>u.name==='Хирдманы'));
  assert.ok(query('Вулкан').some(u=>u.name==='Гарм'));
});
test('dice and property abbreviations do not accidentally match parts of unrelated words',()=>{
  assert.deepEqual(query('2D12'),query('2Д12'));assert.ok(query('Д12').length>0);
  assert.equal(query('Д120').length,0);
  const repair=query('ремонт');assert.ok(repair.length>0);assert.ok(repair.every(u=>u.haystack.split(' ').includes('рм')));
  assert.ok(query('прыжки').every(u=>u.haystack.split(' ').some(t=>/^пр\d*$/.test(t))));
});
test('combined filters, numeric boundaries, test marker and reset are consistent',()=>{
  const results=query('',{faction:'Империя',type:'vehicle',min:'190',max:'200',rank:'2',test:true});
  assert.ok(results.length>0);assert.ok(results.every(u=>u.faction==='Империя'&&u.type==='vehicle'&&u.cost>=190&&u.cost<=200&&u.ranks.includes(2)&&u.test));
  assert.equal(query('',{max:'0'}).length,0);assert.equal(query('',{min:'200',max:'10'}).length,0);
  assert.equal(query('несуществующийотряд').length,0);assert.equal(query('').length,105);
});
test('shareable filter state round-trips Unicode and zero without accepting invalid numbers',()=>{
  const original=readFilters(new URLSearchParams('q=Хирдманы&faction=Снежные+волки&min=0&max=100&rank=3&test=1'));
  assert.deepEqual(readFilters(filterParams(original)),original);
  assert.equal(readFilters(new URLSearchParams('min=NaN&max=-2&rank=Infinity')).min,'');
  assert.equal(readFilters(new URLSearchParams('min=NaN&max=-2&rank=Infinity')).max,'');
});
