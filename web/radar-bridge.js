/* Add archiveKR handoff without replacing the original radar UI. */
const archiveKROpenDetail = openDetail;
openDetail = function(id) {
  archiveKROpenDetail(id);
  const item = opportunities.find(o => o.id === id);
  const actions = document.querySelector('.drawer-actions');
  if (!item || !actions) return;
  const button = document.createElement('button');
  button.className = 'btn';
  button.textContent = '기사 기획으로 보내기';
  button.onclick = async () => {
    button.disabled = true;
    try {
      const r = await fetch('/api/desk/articles', { method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:item.title,body:'',organization:item.org||'',sourceUrl:item.link||'',deadline:item.deadline||'',region:/강원|춘천|원주|강릉/.test([item.title,item.description].join(' '))?'강원':'',origin:'opportunity',questions:[item.demo?'시연 공고입니다. 실제 공고 존재 여부부터 확인하세요.':'원문과 접수기간을 확인하세요.','지원 자격과 지역 관련성을 확인하세요.','담당 기관 인터뷰와 사업 규모 확인이 필요합니다.']}) });
      const data=await r.json();
      if(!r.ok)throw new Error(data.error||'인계에 실패했습니다.');
      const article=data.item||data.article;
      parent.postMessage({type:'archivekr:article-created',id:article.id},location.origin);
      button.textContent='기사 기획 인계 완료';
    } catch(e) { button.textContent=e.message;button.disabled=false; }
  };
  actions.append(button);
};
document.title='archiveKR · 기회탐색';
