from pathlib import Path
from html import escape
from PIL import Image as PILImage
from reportlab.platypus import BaseDocTemplate,PageTemplate,Frame,Paragraph,Spacer,PageBreak,Image,Table,TableStyle,KeepTogether
from reportlab.platypus.tableofcontents import TableOfContents
from reportlab.lib.styles import getSampleStyleSheet,ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfgen.canvas import Canvas
from functools import partial
ROOT=Path(__file__).resolve().parents[1]
GREEN=colors.HexColor('#30483b');INK=colors.HexColor('#252c27');LINE=colors.HexColor('#b8bca9')
def make_pdf(chapters,release,path):
    for name,file in [('PT','PT_Sans-Web-Regular.ttf'),('PTBold','PT_Sans-Web-Bold.ttf'),('PTItalic','PT_Sans-Web-Italic.ttf'),('PTNarrow','PT_Sans-Narrow-Web-Bold.ttf')]:pdfmetrics.registerFont(TTFont(name,str(ROOT/'assets/fonts'/file)))
    pdfmetrics.registerFontFamily('PT',normal='PT',bold='PTBold',italic='PTItalic',boldItalic='PTBold')
    styles=getSampleStyleSheet()
    for s in styles.byName.values():s.fontName='PT';s.textColor=INK
    styles.add(ParagraphStyle('RuleBody',fontName='PT',fontSize=10.5,leading=15,spaceAfter=8))
    styles.add(ParagraphStyle('RuleBullet',parent=styles['RuleBody'],leftIndent=13,firstLineIndent=-9,spaceAfter=5))
    styles.add(ParagraphStyle('RuleH1',fontName='PTBold',fontSize=25,leading=30,spaceAfter=18,keepWithNext=True,textColor=GREEN))
    styles.add(ParagraphStyle('RuleH2',fontName='PTBold',fontSize=16,leading=20,spaceBefore=17,spaceAfter=9,keepWithNext=True,textColor=GREEN))
    styles.add(ParagraphStyle('RuleH3',fontName='PTBold',fontSize=12.5,leading=17,spaceBefore=12,spaceAfter=7,keepWithNext=True,textColor=GREEN))
    styles.add(ParagraphStyle('Cell',fontName='PT',fontSize=8.5,leading=11))
    styles.add(ParagraphStyle('CellHead',parent=styles['Cell'],fontName='PTBold'))
    styles.add(ParagraphStyle('Caption',fontName='PT',fontSize=8.5,leading=11,textColor=colors.HexColor('#596052'),spaceAfter=12))
    styles.add(ParagraphStyle('Note',fontName='PT',fontSize=9,leading=12,textColor=colors.HexColor('#5c4014')))
    def p(t,style='RuleBody'):return Paragraph(escape(t),styles[style])
    class Book(BaseDocTemplate):
        def afterFlowable(self,flowable):
            if isinstance(flowable,Paragraph) and hasattr(flowable,'bookmark'):
                key=flowable.bookmark;self.canv.bookmarkPage(key)
                level=getattr(flowable,'toc_level',0)
                self.canv.addOutlineEntry(flowable.getPlainText(),key,level=level,closed=level>0)
                self.notify('TOCEntry',(level,flowable.getPlainText(),self.page,key))
    doc=Book(str(path),pagesize=A4,rightMargin=20*mm,leftMargin=20*mm,topMargin=21*mm,bottomMargin=20*mm,title='Бронепехота — '+release['edition']+' '+release['version'],author='Уральская версия',pageCompression=1)
    edition=release['edition']+' '+release['version']
    def decorate(canvas,doc):
        if doc.page==1:return
        canvas.saveState();canvas.setFillColor(GREEN);canvas.setFont('PTBold',9);canvas.drawString(20*mm,285*mm,'БРОНЕПЕХОТА');canvas.setFont('PT',8.5);canvas.drawRightString(190*mm,285*mm,edition)
        canvas.setStrokeColor(LINE);canvas.setLineWidth(.4);canvas.line(20*mm,281*mm,190*mm,281*mm)
        canvas.setFillColor(colors.HexColor('#596052'));canvas.setFont('PT',8);canvas.drawString(20*mm,12*mm,release['date']);canvas.drawRightString(190*mm,12*mm,str(doc.page));canvas.restoreState()
    doc.addPageTemplates(PageTemplate(id='book',frames=Frame(doc.leftMargin,doc.bottomMargin,doc.width,doc.height,leftPadding=0,bottomPadding=0,rightPadding=0,topPadding=0),onPage=decorate))
    story=[Spacer(1,36*mm),Paragraph('БРОНЕПЕХОТА',ParagraphStyle('Cover',fontName='PTNarrow',fontSize=46,leading=50,textColor=GREEN)),Spacer(1,10*mm),Paragraph('Правила игры',ParagraphStyle('CoverSub',fontName='PT',fontSize=26,leading=32,textColor=INK)),Spacer(1,12*mm),p(edition),p('Выпуск от '+release['date']),Spacer(1,55*mm),p('Полевой справочник'),p('Десять глав правил, таблицы и иллюстрации. Для последовательного изучения и быстрого обращения во время партии.'),Spacer(1,8*mm),p('Уральская версия включает согласованные изменения правил. Примечания «Требует уточнения» обозначают нерешённые вопросы исходной редакции.'),PageBreak(),p('Оглавление','RuleH1')]
    toc=TableOfContents();toc.levelStyles=[ParagraphStyle('Toc0',fontName='PTBold',fontSize=11,leading=15,spaceBefore=5),ParagraphStyle('Toc1',fontName='PT',fontSize=9,leading=11,leftIndent=14,spaceBefore=0)]
    story.extend([toc,PageBreak()])
    for ci,c in enumerate(chapters):
        if ci:story.append(PageBreak())
        h=p(f'{c["number"]:02}. {c["title"]}','RuleH1');h.bookmark=c['id'];h.toc_level=0;story.append(h)
        for s in c['sections']:
            if not s.get('intro'):
                h=p(s['title'],'RuleH2' if s['level']==2 else 'RuleH3');h.bookmark=c['id']+'-'+s['id'];h.toc_level=1;story.append(h)
            for b in s['blocks']:
                t=b['type']
                if t in ('p','bullet'):story.append(p(('• ' if t=='bullet' else '')+b['text'],'RuleBullet' if t=='bullet' else 'RuleBody'))
                elif t=='note':
                    text=Paragraph('<b>Требует уточнения</b><br/>'+escape(b['text']),styles['Note']);tbl=Table([[text]],colWidths=[doc.width]);tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,-1),colors.HexColor('#f9eed4')),('BOX',(0,0),(-1,-1),.6,colors.HexColor('#b08025')),('LEFTPADDING',(0,0),(-1,-1),12),('RIGHTPADDING',(0,0),(-1,-1),12),('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10)]));story.extend([Spacer(1,5),tbl,Spacer(1,12)])
                elif t=='table':
                    story.append(p(b['title'],'RuleH3'))
                    rows=[[p(v,'CellHead') for v in b['headers']]]+[[p(v,'Cell') for v in row] for row in b['rows']]
                    n=len(b['headers']);widths=[doc.width/n]*n
                    if n==2:widths=[doc.width*.34,doc.width*.66]
                    if n==3:widths=[doc.width*.4,doc.width*.3,doc.width*.3]
                    tbl=Table(rows,colWidths=widths,repeatRows=1,hAlign='LEFT')
                    tbl.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),colors.HexColor('#d9ddc9')),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.HexColor('#faf9f3'),colors.HexColor('#f0f0e7')]),('GRID',(0,0),(-1,-1),.4,LINE),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),7),('RIGHTPADDING',(0,0),(-1,-1),7),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6)]));story.extend([tbl,Spacer(1,12)])
                elif t=='figure':
                    image_path=ROOT/'assets/rules'/b['file'];w,h=PILImage.open(image_path).size;scale=min(doc.width/w,110*mm/h,.95)
                    im=Image(str(image_path),width=w*scale,height=h*scale);im.hAlign='CENTER'
                    story.append(KeepTogether([Spacer(1,8),im,Spacer(1,6),p(b['caption'],'Caption')]))
    doc.multiBuild(story,canvasmaker=partial(Canvas,invariant=True))
    print('PDF:',path.name)
