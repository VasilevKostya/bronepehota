import test from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import{stem,normalize,prepareIndex,search,queryTerms,distance,hit,excerpt}from'../assets/search.js';
const docs=prepareIndex(JSON.parse(fs.readFileSync(new URL('../dist/assets/search-index.json',import.meta.url),'utf8')));
test('Russian forms and ё/е are equivalent',()=>{
  assert.equal(stem('машины'),stem('машина'));assert.equal(stem('машиной'),stem('машина'));
  assert.equal(stem('пехотинцами'),stem('пехотинец'));assert.equal(normalize('ПОЛЁТ D12'),'полет д12');
});
test('exact rule title comes first',()=>assert.equal(search(docs,'Тест брони Д12')[0].url,'pravila-povrezhdeniya.html#test-broni-d12'));
test('small typo ranks the intended rule before incidental words',()=>assert.ok(search(docs,'броян')[0].title.includes('брони')));
test('abbreviations and dice notation are supported',()=>{
  assert.deepEqual(queryTerms('ББ'),queryTerms('ближний бой'));
  assert.deepEqual(queryTerms('Рм'),queryTerms('ремонт'));
  assert.deepEqual(search(docs,'D12').map(x=>x.id),search(docs,'Д12').map(x=>x.id));
});
test('image transcriptions are included in search',()=>{
  assert.ok(search(docs,'GRYPHON 305').some(x=>x.chapter==='Боевые единицы'));
  assert.ok(search(docs,'гранаты 1Д20').length);
  assert.ok(search(docs,'прыжка 5').some(x=>x.chapter==='Особые свойства'));
});
test('unknown and empty queries are empty',()=>{assert.equal(search(docs,'').length,0);assert.equal(search(docs,'ксюнгфртц').length,0);});
test('bounded Damerau distance handles transposition',()=>{assert.equal(distance('броня','броян'),1);assert.equal(distance('пилот','пилоты'),1);});
test('two-edit matches are highlighted and yield a relevant excerpt',()=>{
  const terms=queryTerms('транпортиовка');assert.ok(search(docs,'транпортиовка').length);assert.ok(hit('транспортировка',terms));
  assert.ok(excerpt('Вступление. '.repeat(45)+'Транспортировка техники описана здесь.',terms).includes('Транспортировка'));
});
