// Same-origin bridge: reuse an article and its production outputs across the workspace.
(() => {
  let deskArticleId = null;
  const status = document.createElement('p');
  status.style.cssText = 'padding:12px 18px;background:#eaf0e8;color:#18302e;font:13px system-ui';
  status.textContent = 'archiveKD 연결: 원문을 불러오거나 채널 변환을 시작하면 데스크와 자동 제작 대기열에 이어집니다.';
  document.body.prepend(status);
  const send = data => parent.postMessage(data, location.origin);
  const originalFetch = window.fetch.bind(window);
  window.fetch = async (...args) => {
    const response = await originalFetch(...args);
    const input = typeof args[0] === 'string' ? args[0] : args[0]?.url;
    if (input && new URL(input, location.href).pathname === '/api/movist/fetch' && response.ok) {
      const data = await response.clone().json();
      if (data.archiveKR?.articleId) { deskArticleId = data.archiveKR.articleId; status.textContent = '원문을 편집 데스크에 등록했습니다. 카드·SNS 자동 제작은 별도 지시 없이 이어집니다.'; send({ type:'archivekr:studio-registered',articleId:deskArticleId }); }
    }
    return response;
  };
  window.addEventListener('message', async e => {
    if (e.origin !== location.origin || e.source !== parent || e.data?.type !== 'archivekr:studio') return;
    const article = e.data.article;
    if (!article || typeof article.title !== 'string' || typeof article.body !== 'string') return;
    deskArticleId = article.id;
    pool.length = 0;
    const files = [];
    for (const path of (article.sourceImages || []).slice(0,10)) {
      if (!/^\/api\/movist\/img\/[0-9a-f]{12}\/[a-z0-9._-]+$/i.test(path)) continue;
      try { const r = await originalFetch(path); if(r.ok)files.push(new File([await r.blob()], 'source-photo.jpg', {type:'image/jpeg'})); } catch {}
    }
    if(files.length)await addFiles(files);
    for (const [id,value] of Object.entries({ title:article.title,body:article.body,url:article.sourceUrl||'',author:article.sourceCredit||'',credit:article.sourceCredit||'','offline-headline':article.title })) { const input=document.getElementById(id); if(input)input.value=value; }
    const parts=article.body.split(/\n+/).map(v=>v.trim()).filter(Boolean).slice(0,4);
    result = {
      instagram:{cards:[{no:1,headline:article.title,body:'',photo_hint:'',photo:files.length?0:null},...parts.map((body,i)=>({no:i+2,headline:`원문 핵심 ${i+1}`,body:body.slice(0,260),photo_hint:'',photo:files.length?Math.min(i,files.length-1):null}))],caption:e.data.artifacts?.instagram||article.title,hashtags:['#archiveKD','#콘텐츠뉴스']},
      threads:{text:e.data.artifacts?.threads||article.title},
      kakao:{text:e.data.artifacts?.kakao||article.title,question:''},
    };
    lastArticle={title:article.title,body:article.body,url:article.sourceUrl||'',author:article.sourceCredit||'',credit:article.sourceCredit||''};
    current='instagram';render();drawAll();
    status.textContent='데스크 원문과 자동 제작 문안을 불러왔습니다. 아래 카드 편집기에서 이어서 편집하세요. 원문 발췌이며 새로운 취재 결과는 아닙니다.';
    send({type:'archivekr:studio-loaded',articleId:deskArticleId});
  });
  document.getElementById('run')?.addEventListener('click', async () => {
    const title=document.getElementById('title').value.trim(),body=document.getElementById('body').value.trim();
    if(!title || !body)return;
    try {
      const sourceUrl=document.getElementById('url').value.trim();
      if(!deskArticleId){const r=await originalFetch('/api/desk/articles');const data=await r.json();const existing=data.items?.find(a=>sourceUrl?a.sourceUrl===sourceUrl:a.title===title);deskArticleId=existing?.id||null;}
      const r=await originalFetch('/api/desk/articles'+(deskArticleId?'/'+deskArticleId:''),{method:deskArticleId?'PATCH':'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title,body,sourceUrl,organization:'콘텐츠'})});
      const data=await r.json();if(!r.ok)throw new Error();deskArticleId=data.item.id;
      status.textContent='이 원고를 편집 데스크와 자동 제작에 등록했습니다. AI 편집 기능의 실행 결과와 자동 제작 상태는 별도로 확인할 수 있습니다.';
      send({type:'archivekr:studio-registered',articleId:deskArticleId});
    } catch {status.textContent='데스크 인계에 실패했습니다. 기존 원고가 발행 상태인지 확인하세요. 입력한 본문은 유지됩니다.';}
  },true);
  send({type:'archivekr:studio-ready'});
})();
