/* MOVIST final-spec browser specimen. No external photos or publishing. */
window.archiveKRDrawCard=(canvas,title,credit='체험용 · 사진 없음')=>{
 canvas.width=1080;canvas.height=1440;const x=canvas.getContext('2d');
 x.fillStyle='#52636b';x.fillRect(0,0,1080,1440);
 const g=x.createLinearGradient(0,648,0,1325);g.addColorStop(0,'rgba(0,0,0,0)');g.addColorStop(1,'rgba(0,0,0,.92)');x.fillStyle=g;x.fillRect(0,648,1080,792);
 x.fillStyle='#fff';x.textAlign='center';x.font='26px ArchiveBody, sans-serif';x.fillText('MOVIST',540,68);
 x.font='24px ArchiveBody, sans-serif';const tag='영화 뉴스';const tw=x.measureText(tag).width+40;x.strokeStyle='#fff';x.lineWidth=2;x.strokeRect(60,976,tw,56);x.textAlign='left';x.fillText(tag,80,1013);
 x.font='bold 84px ArchiveHead, sans-serif';const chars=Array.from(String(title));const lines=[];let line='';for(const ch of chars){if(Array.from(line).length>=13||x.measureText(line+ch).width>960){lines.push(line);line='';}line+=ch;}if(line)lines.push(line);if(lines.length>2){lines.length=2;lines[1]=Array.from(lines[1]).slice(0,11).join('')+'…';}lines.forEach((s,i)=>x.fillText(s,60,1150+i*104));
 x.textAlign='right';x.font='20px ArchiveBody, sans-serif';x.fillText(credit,1020,1390);return canvas;
};
