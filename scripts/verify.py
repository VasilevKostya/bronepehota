"""Validate links, search coverage, offline integrity, and the shared PDF content."""
import json, re, hashlib
from pathlib import Path
from urllib.parse import urlsplit,unquote
from lxml import html
from pypdf import PdfReader
ROOT=Path(__file__).resolve().parents[1];dist=ROOT/'dist'
chapters=[json.loads(p.read_text(encoding='utf-8')) for p in sorted((ROOT/'content/rules').glob('*.json'))]
release=json.loads((ROOT/'content/release.json').read_text(encoding='utf-8'))
docs={p.name:html.fromstring(p.read_text(encoding='utf-8')) for p in dist.glob('*.html')}
errors=[]
for name,doc in docs.items():
    ids=doc.xpath('//@id')
    if len(ids)!=len(set(ids)):errors.append(f'Duplicate anchors: {name}')
    for attr in doc.xpath('//@href|//@src'):
        u=urlsplit(attr)
        if u.scheme or u.netloc:continue
        path=unquote(u.path) or name
        if not (dist/path).exists():errors.append(f'Missing link: {name} -> {attr}')
        if u.fragment and path in docs and u.fragment not in docs[path].xpath('//@id'):errors.append(f'Missing anchor: {name} -> {attr}')
    for img in doc.xpath('//img'):
        if not img.get('alt'):errors.append(f'Missing alternative text: {name}')
manifest=json.loads((dist/'precache.json').read_text(encoding='utf-8'))
for path in manifest['files']:
    if hashlib.sha256((dist/path).read_bytes()).hexdigest()!=manifest['hashes'][path]:errors.append(f'Hash mismatch: {path}')
index=json.loads((dist/'assets/search-index.json').read_text(encoding='utf-8'))
assert len(index)==sum(len(c['sections']) for c in chapters)
pdf=PdfReader(dist/f"bronepehota-ural-{release['version']}.pdf")
normalize=lambda s:re.sub(r'\s+','',s)
pdfparts=[]
for page in pdf.pages:
    # Exclude repeating running heads/folios that interrupt sentences at page breaks.
    lines=page.extract_text().splitlines()
    lines=[line for line in lines if line.strip() not in ('БРОНЕПЕХОТА',release['edition']+' '+release['version'],release['date']) and not re.fullmatch(r'\d+',line.strip())]
    pdfparts.extend(lines)
pdftext=normalize(''.join(pdfparts))
count=0
for c in chapters:
    webtext=normalize(docs['pravila-'+c['id']+'.html'].text_content())
    for s in c['sections']:
        indexed=normalize(next(d['text'] for d in index if d['id']==c['id']+'/'+s['id']))
        for b in s['blocks']:
            texts=[b.get('text',b.get('caption',''))] if b['type']!='table' else [b['title']]+b['headers']+[v for row in b['rows'] for v in row]
            for text in texts:
                target=normalize(text)
                for surface,actual in [('web',webtext),('PDF',pdftext),('search',indexed)]:
                    if target not in actual:errors.append(f'{surface} content mismatch: {c["id"]}/{s["id"]}: {text[:70]}')
                count+=1
assert pdf.outline,'PDF bookmarks missing'
assert not errors,'\n'.join(errors)
print(f'PASS: {len(docs)} pages, {len(index)} search sections, {len(manifest["files"])} hashed assets, {len(pdf.pages)} PDF pages, {count} shared content fragments.')
