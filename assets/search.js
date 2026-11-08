/* Russian Snowball/Porter stemming, Unicode normalization and bounded typo matching.
   Algorithm reference: https://snowballstem.org/algorithms/russian/stemmer.html */
export function normalize(value){return value.normalize('NFKC').toLowerCase().replace(/ё/g,'е').replace(/\bd\s*(6|12|20)\b/g,'д$1').replace(/д\s+(6|12|20)\b/g,'д$1');}
export function stem(input){
  const word=normalize(input);if(!/^[а-я]+$/.test(word))return word;
  const match=word.match(/^(.*?[аеиоуыэюя])(.*)$/);if(!match)return word;
  const prefix=match[1];let rv=match[2];
  const r2match=word.match(/[аеиоуыэюя][^аеиоуыэюя].*?[аеиоуыэюя][^аеиоуыэюя]/);
  const r2=r2match?r2match.index+r2match[0].length:word.length;
  let next=rv.replace(/(?:ив|ивши|ившись|ыв|ывши|ывшись)$/,'');
  if(next===rv)next=rv.replace(/([ая])(?:в|вши|вшись)$/,'$1');
  if(next!==rv)rv=next;
  else{
    rv=rv.replace(/(?:ся|сь)$/,'');
    next=rv.replace(/(?:ее|ие|ые|ое|ими|ыми|ей|ий|ый|ой|ем|им|ым|ом|его|ого|ему|ому|их|ых|ую|юю|ая|яя|ою|ею)$/,'');
    if(next!==rv){rv=next.replace(/(?:ивш|ывш|ующ)$/,'').replace(/([ая])(?:ем|нн|вш|ющ|щ)$/,'$1');}
    else{
      next=rv.replace(/(?:ила|ыла|ена|ейте|уйте|ите|или|ыли|ей|уй|ил|ыл|им|ым|ен|ило|ыло|ено|ят|ует|уют|ит|ыт|ены|ить|ыть|ишь|ую|ю)$/,'');
      if(next===rv)next=rv.replace(/([ая])(?:ла|на|ете|йте|ли|й|л|ем|н|ло|но|ет|ны|ть|ешь|нно)$/,'$1');
      rv=next!==rv?next:rv.replace(/(?:иями|ями|ами|ией|иям|ием|иях|ев|ов|ие|ье|еи|ии|ей|ой|ий|ям|ем|ам|ом|ах|ях|ию|ью|ия|ья|а|е|и|й|о|у|ы|ь|ю|я)$/,'');
    }
  }
  rv=rv.replace(/и$/,'');
  const candidate=prefix+rv;const deriv=candidate.match(/ость?$/);
  if(deriv&&deriv.index>=r2)rv=rv.replace(/ость?$/,'');
  if(rv.endsWith('ь'))rv=rv.slice(0,-1);else rv=rv.replace(/ейше?$/,'').replace(/нн$/,'н');
  // Domain nouns with a fleeting vowel are not conflated by the generic stemmer.
  return (prefix+rv).replace(/^пехотинец$/,'пехотинц').replace(/^боец$/,'бойц');
}
const stop=new Set(['и','в','на','по','с','со','к','ко','от','до','для','а','из','или','что','как','при','во','за','не','это','то']);
const aliases={'бб':'ближний бой','рб':'ближний бой','бр':'броня','ск':'скорость','рм':'ремонт','пр':'прыжок','а':'армейский ранг','дальн':'дальность','мощн':'мощность','бк':'боезапас'};
export function tokenize(text){return normalize(text).match(/[а-яa-z0-9]+/g)||[];}
export function queryTerms(query){return [...new Set(tokenize(query).flatMap(t=>tokenize(aliases[t]||t)).filter(t=>!stop.has(t)).map(stem))];}
export function distance(a,b,limit=2){
  if(Math.abs(a.length-b.length)>limit)return limit+1;
  let prev=Array.from({length:b.length+1},(_,i)=>i),before=null;
  for(let i=1;i<=a.length;i++){
    const row=[i];for(let j=1;j<=b.length;j++){
      row[j]=Math.min(row[j-1]+1,prev[j]+1,prev[j-1]+(a[i-1]===b[j-1]?0:1));
      if(before&&i>1&&j>1&&a[i-1]===b[j-2]&&a[i-2]===b[j-1])row[j]=Math.min(row[j],before[j-2]+1);
    }
    if(Math.min(...row)>limit)return limit+1;before=prev;prev=row;
  }
  return prev[b.length];
}
export function prepareIndex(docs){
  return docs.map(doc=>({...doc,words:new Set(tokenize(doc.title+' '+doc.text).map(stem)),titleWords:new Set(tokenize(doc.title).map(stem))}));
}
export function search(docs,query){
  const terms=queryTerms(query);if(!terms.length)return [];
  const phrase=normalize(query).trim(),results=[];
  for(const doc of docs){let score=0,all=true,fuzzy=false;
    for(const t of terms){
      if(doc.titleWords.has(t)){score+=18;continue;}
      if(doc.words.has(t)){score+=7;continue;}
      let best=0;for(const w of doc.words){
        if(t.length>=3&&w.startsWith(t)){best=Math.max(best,3);continue;}
        if(t.length>=4&&distance(w,t,t.length>=8?2:1)<=(t.length>=8?2:1))best=Math.max(best,1);
      }
      if(!best){all=false;break;}if(best===1)fuzzy=true;
      if(t.length>=4&&[...doc.titleWords].some(w=>distance(w,t,t.length>=8?2:1)<=(t.length>=8?2:1)))best+=9;
      score+=best;
    }
    if(all){if(normalize(doc.title).includes(phrase))score+=32;if(normalize(doc.text).includes(phrase))score+=12;results.push({...doc,score,fuzzy});}
  }
  return results.sort((a,b)=>b.score-a.score||a.number-b.number);
}
export function hit(word,terms){const s=stem(word);return terms.some(t=>s===t||(t.length>=3&&s.startsWith(t))||(t.length>=4&&distance(s,t,t.length>=8?2:1)<=(t.length>=8?2:1)));}
export function excerpt(text,terms,size=240){
  const matches=[...text.matchAll(/[А-Яа-яЁёA-Za-z0-9]+/g)];const first=matches.find(m=>hit(m[0],terms));
  let start=Math.max(0,(first?.index||0)-65);if(start>0){const space=text.indexOf(' ',start);if(space>=0)start=space+1;}
  let end=Math.min(text.length,start+size);if(end<text.length){const space=text.lastIndexOf(' ',end);if(space>start)end=space;}
  return (start?'…':'')+text.slice(start,end)+(end<text.length?'…':'');
}
