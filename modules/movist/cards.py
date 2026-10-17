"""Offline renderer for the approved MOVIST workbook design (never calls a model)."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
BASE = Path(__file__).resolve().parent
TEMPLATE = {
    'id': 'movist-workbook-v1', 'ratios': {'34': [1080,1440], '45': [1080,1350], '916': [1080,1920]},
    'margin': 60, 'labelSize': 26, 'labelSpacing': 3, 'tagSize': 24,
    'coverHeadlineSize': 84, 'innerHeadlineSize': 68, 'bodySize': 36,
    'headlineLineHeight': 1.3, 'headlineSpacing': -0.02, 'coverSubtitle': False,
    'photoRights': 'pending', 'source': 'MOVIST_카드뉴스_디자인규격.xlsx',
}

def render_card(data, background=None):
    if not isinstance(data, dict): raise ValueError('JSON 객체가 필요합니다')
    ratio = str(data.get('ratio', '34'))
    if ratio not in TEMPLATE['ratios']: raise ValueError('invalid_ratio')
    width, height = TEMPLATE['ratios'][ratio]
    layout = data.get('layout', 'full')
    if layout not in ('full', 'split', 'text'): raise ValueError('invalid_layout')
    cover = data.get('cover', True)
    scale = {'small': .85, 'normal': 1, 'large': 1.15}.get(data.get('size', 'normal'))
    if scale is None: raise ValueError('invalid_size')
    im = Image.new('RGB', (width,height), '#14181f')
    photo_height = round(height*.58) if layout == 'split' else height
    if background is not None and layout != 'text':
        photo = ImageOps.fit(background.convert('RGB'), (width,photo_height), method=Image.Resampling.LANCZOS)
        im.paste(photo,(0,0))
        shade = Image.new('RGBA', im.size)
        grad = ImageDraw.Draw(shade)
        for row in range(photo_height):
            top = max(0, .45*(1-row/220))
            position = max(0,min(1,(row/height-.45)/.55))
            bottom = (position/.55*.62 if position <= .55 else .62+(position-.55)/.45*.30) if layout == 'full' else 0
            grad.line((0,row,width,row), fill=(0,0,0,round(255*max(top,bottom))))
        im = Image.alpha_composite(im.convert('RGBA'),shade).convert('RGB')
    d = ImageDraw.Draw(im)
    def font(size, head=False):
        # Bundled body font is the same local modern Gothic used by the studio.
        impact = data.get('font') == 'impact' and head
        result = ImageFont.truetype(str(BASE/'fonts'/('head.ttf' if impact else 'body.ttf')),round(size))
        if not impact:
            result.set_variation_by_axes([800 if head else 400])
        return result
    def extent(text, f, spacing=0): return sum(d.textlength(ch,font=f) for ch in text)+max(0,len(text)-1)*spacing
    def text(x,y,value,f,spacing=0,fill='white'):
        for ch in value:
            d.text((x,y),ch,font=f,fill=fill,anchor='lt');x+=d.textlength(ch,font=f)+spacing
    def wrap(value,f,spacing=0):
        lines=[]
        for paragraph in str(value).split('\n'):
            line=''
            for ch in paragraph:
                if line and extent(line+ch,f,spacing)>960: lines.append(line);line=''
                line+=ch
            if line: lines.append(line)
        return lines
    head_size = (72 if layout=='split' else 84) if cover else (76 if layout=='text' else 60 if layout=='split' else 68)
    head = font(head_size*scale,True); body = font((32 if cover else 38 if layout=='text' else 36)*scale)
    spacing = -head.size*.02
    headlines = wrap(str(data.get('headline','영화의 다음 장면'))[:200],head,spacing)
    if cover and (len(headlines) > 2 or any(len(line) > 13 for line in headlines)):
        raise ValueError('cover_headline_limit')
    bodylines = [] if cover and not data.get('showSubtitle',False) else wrap(str(data.get('body',''))[:1200],body)
    available = height-photo_height-120 if layout=='split' else height-250
    block = (84 if cover else 0)+len(headlines)*head.size*1.3+24+len(bodylines)*body.size*1.55
    # Reject overflowing copy rather than silently cutting an approved manuscript.
    if block > available: raise ValueError('card_text_overflow')
    y = photo_height+60 if layout=='split' else max(150,height-90-block)
    if layout=='text': y=(height-block)/2
    if cover:
        tag=str(data.get('tag','인터뷰 | 영화'))[:40];tf=font(24);tw=extent(tag,tf)+40
        d.rounded_rectangle((60,y,60+tw,y+56),radius=28,outline='white',width=2)
        text(80,y+14,tag,tf);y+=84
    for line in headlines: text(60,y,line,head,spacing);y+=head.size*1.3
    y+=24
    for line in bodylines: text(60,y,line,body);y+=body.size*1.55
    label=str(data.get('label','archiveKD'))[:50];lf=font(26)
    text((width-extent(label,lf,3))/2,60,label,lf,3,fill='#e0e0e0')
    credit=str(data.get('credit',''))[:100]
    if credit and background is not None:
        cf=font(20);value='사진 '+credit
        if extent(value,cf)>960:
            while value and extent(value+'…',cf)>960: value=value[:-1]
            value+='…'
        text(width-60-extent(value,cf),photo_height-36,value,cf,fill='#b0b0b0')
    index=max(0,int(data.get('index',0)));total=max(index+1,int(data.get('total',1)))
    if total>1:
        pf=font(24);page='넘겨보기 ›' if cover else f'{index+1} / {total}'
        text(width-60-extent(page,pf),106,page,pf)
    return im
