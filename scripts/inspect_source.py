"""Read-only DOCX import inventory; extracts the supplied source, never executes it."""
import json, sys, hashlib
from pathlib import Path
from zipfile import ZipFile
from lxml import etree
from PIL import Image, ImageOps, ImageDraw

root = Path(__file__).resolve().parents[1]
out = root / 'tmp' / 'source'
out.mkdir(parents=True, exist_ok=True)
media = out / 'media'
media.mkdir(exist_ok=True)
ns = {'w':'http://schemas.openxmlformats.org/wordprocessingml/2006/main', 'a':'http://schemas.openxmlformats.org/drawingml/2006/main', 'r':'http://schemas.openxmlformats.org/officeDocument/2006/relationships', 'v':'urn:schemas-microsoft-com:vml', 'mc':'http://schemas.openxmlformats.org/markup-compatibility/2006'}
path = Path(sys.argv[1])
with ZipFile(path) as z:
    rels={x.get('Id'):x.get('Target') for x in etree.fromstring(z.read('word/_rels/document.xml.rels'))}
    doc=etree.fromstring(z.read('word/document.xml'))
    # DrawingML is authoritative where Word stores a legacy VML fallback.
    for fallback in doc.xpath('//mc:AlternateContent/mc:Fallback',namespaces=ns): fallback.getparent().remove(fallback)
    blocks=[]
    for idx,el in enumerate(doc.find('w:body',ns)):
        tag=etree.QName(el).localname
        if tag not in ('p','tbl'): continue
        text=''.join(el.xpath('.//w:t/text()',namespaces=ns)).strip()
        imgs=[]
        for img in el.xpath('.//a:blip | .//v:imagedata',namespaces=ns):
            rid=img.get('{'+ns['r']+'}embed') or img.get('{'+ns['r']+'}id')
            target=rels.get(rid,'')
            if target.startswith('media/') and target not in imgs:
                imgs.append(target)
                (media/Path(target).name).write_bytes(z.read('word/'+target))
        style=el.xpath('./w:pPr/w:pStyle/@w:val',namespaces=ns)
        block={'source':idx,'type':tag,'style':style[0] if style else '', 'text':text,'images':[Path(x).name for x in imgs]}
        if tag=='tbl': block['rows']=[[''.join(c.xpath('.//w:t/text()',namespaces=ns)) for c in row.findall('w:tc',ns)] for row in el.findall('w:tr',ns)]
        if text or imgs: blocks.append(block)
    (out/'blocks.json').write_text(json.dumps(blocks,ensure_ascii=False,indent=2),encoding='utf-8')
    (out/'text.txt').write_text('\n'.join(f"{b['source']:04d} [{b['style']}] {b['text']} {' IMAGES:'+','.join(b['images']) if b['images'] else ''}" for b in blocks),encoding='utf-8')
    print('source sha256',hashlib.sha256(path.read_bytes()).hexdigest(),'blocks',len(blocks),'media',len(list(media.iterdir())))
    pictures=[]
    for p in sorted(media.iterdir(),key=lambda p:int(''.join(filter(str.isdigit,p.stem)) or 0)):
        try:
            im=Image.open(p).convert('RGB')
            pictures.append((p.name,im.copy()))
        except Exception as e: print('NONRASTER',p.name,str(e)[:100])
    for batch in range(0,len(pictures),20):
        sheet=Image.new('RGB',(1200,5*230),'#e8e8e8'); draw=ImageDraw.Draw(sheet)
        for k,(name,im) in enumerate(pictures[batch:batch+20]):
            x=(k%4)*300;y=(k//4)*230
            draw.text((x+8,y+4),f'{name}  {im.width}x{im.height}',fill='black')
            im.thumbnail((284,202));sheet.paste(im,(x+8,y+24))
        sheet.save(out/f'contact-{batch//20+1}.jpg')
