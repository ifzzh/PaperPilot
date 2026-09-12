"""Self-authored synthetic PDFs. Run with reportlab; never loads user files."""
from pathlib import Path
import hashlib
import json
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.pdfbase.cidfonts import UnicodeCIDFont
from reportlab.lib.pdfencrypt import StandardEncryption

root = Path(__file__).resolve().parent
font = Path('/usr/share/fonts/truetype/arphic-gbsn00lp/gbsn00lp.ttf')
pdfmetrics.registerFont(TTFont('FixtureChinese', str(font)))
pdfmetrics.registerFont(UnicodeCIDFont('STSong-Light'))
for filename, pages in [('original.pdf', 100), ('translated.pdf', 2), ('encrypted.pdf', 1)]:
    c = canvas.Canvas(str(root / filename), pagesize=(595,842), pageCompression=0, invariant=True,
                      encrypt=StandardEncryption('synthetic-password') if filename=='encrypted.pdf' else None)
    c.setTitle('iPaper synthetic reader fixture - not a research paper')
    for number in range(1,pages+1):
        c.setPageRotation(90 if number==2 else 0)
        top = 530 if number == 2 else 770
        spacing = 14 if number == 2 else 19
        c.setFont('Helvetica',18)
        c.drawString(45,top, f'Synthetic reader validation - page {number}')
        c.setFont('FixtureChinese',15)
        c.drawString(45,top-40,'中文文本选择与旋转验证' if filename!='translated.pdf' else '合成译文样例：不代表机器翻译结果')
        c.setFont('STSong-Light',12)
        c.drawString(45,top-70,'中文字符映射测试')
        c.setFont('Helvetica',11)
        for line in range(28):
            c.drawString(45,top-105-line*spacing,f'Page {number}, line {line+1}: Text selection, range loading and cleanup verification.')
        c.showPage()
    c.save()
(root/'SHA256.json').write_text(json.dumps({p.name:hashlib.sha256(p.read_bytes()).hexdigest() for p in root.glob('*.pdf')},indent=2)+'\n')
