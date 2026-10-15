"""Offline PNG renderer following the uploaded MOVIST design workbook."""
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageOps
BASE=Path(__file__).resolve().parent

def render_card(data, background=None):
    if not isinstance(data,dict):raise ValueError('JSON 객체가 필요합니다')
    title=str(data.get('headline','영화의 다음 장면'))[:200]
    body=str(data.get('body',''))[:1200]
    cover=data.get('cover',True)
    im=Image.new('RGB',(1080,1440),'#20252e')
    if background is not None:
        im=ImageOps.fit(background.convert('RGB'),(1080,1440),method=Image.Resampling.LANCZOS)
        # Keep the photo visible above, and ensure white headlines remain legible below.
        shade=Image.new('RGBA',im.size,(0,0,0,0))
        gradient=ImageDraw.Draw(shade)
        for row in range(im.height):
            alpha=int(55+175*(row/(im.height-1))**1.5)
            gradient.line((0,row,im.width,row),fill=(0,0,0,alpha))
        im=Image.alpha_composite(im.convert('RGBA'),shade).convert('RGB')
    d=ImageDraw.Draw(im)
    def font(size):return ImageFont.truetype(str(BASE/'fonts/body.ttf'),size)
    label=str(data.get('label','MOVIST'))[:50]
    d.text((540,60),label,font=font(26),fill='#dddddd',anchor='mt')
    headline=font(84 if cover else 68);lines=[]
    for paragraph in title.splitlines():
        line=''
        for ch in paragraph:
            if line and d.textlength(line+ch,font=headline)>960:lines.append(line);line=''
            line+=ch
        if line:lines.append(line)
    lines=lines[:4]
    y=1200-len(lines)*110
    if cover:
        tag=str(data.get('tag','인터뷰 | 영화'))[:40];w=d.textlength(tag,font=font(24))+40
        d.rounded_rectangle((60,y-96,60+w,y-40),radius=28,outline='white',width=2)
        d.text((80,y-86),tag,font=font(24),fill='white')
    for line in lines:d.text((60,y),line,font=headline,fill='white');y+=int(headline.size*1.3)
    if not cover and body:d.text((60,min(y+24,1280)),body[:70],font=font(36),fill='white')
    return im
