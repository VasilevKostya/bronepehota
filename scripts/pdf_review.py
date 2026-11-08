from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader
root=Path(__file__).resolve().parents[1]
pdf=PdfReader(root/'dist/bronepehota-ural-0.1.pdf')
files=sorted((root/'tmp').glob('pdf-page-*.jpg'))
out=root/'tmp/pdf-review';out.mkdir(exist_ok=True)
for k in range(0,len(files),12):
    sheet=Image.new('RGB',(1200,1120),'#deded6');draw=ImageDraw.Draw(sheet)
    for j,f in enumerate(files[k:k+12]):
        im=Image.open(f);im.thumbnail((280,335))
        x=(j%4)*300+10;y=(j//4)*370+25
        sheet.paste(im,(x,y));draw.text((x,y-18),f.stem,fill='black')
    sheet.save(out/f'contact-{k//12+1}.jpg')
print('PDF pages:',len(pdf.pages),'Contact sheets:',len(list(out.glob('*.jpg'))))
(out/'text.txt').write_text('\n'.join(p.extract_text() for p in pdf.pages),encoding='utf-8')
