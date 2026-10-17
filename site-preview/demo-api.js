/* Public preview: browser-only storage. No server or external publishing. */
(() => {
 'use strict';
 const fontStyle=document.createElement('style');fontStyle.textContent="@font-face{font-family:ArchiveHead;src:url(./fonts/head.ttf)}@font-face{font-family:ArchiveBody;src:url(./fonts/body.ttf)}";document.head.append(fontStyle);
 const KEY='archivekr-public-preview-v2', now=()=>new Date().toISOString();
 const targets={instagram:'체험용 계정 · 실제 연결 없음',threads:'체험용 계정 · 실제 연결 없음',mediaBaseUrl:''};
 let state;
 try {state=JSON.parse(localStorage.getItem(KEY));} catch {}
 if(!state||state.schema!==2)state={schema:2,counter:0,articles:[],jobs:[],messages:[],settings:{enabled:true,pollingEnabled:false,pollSeconds:60,channels:{instagram:true,threads:true}}};
 const save=()=>localStorage.setItem(KEY,JSON.stringify(state));
 const id=prefix=>prefix+'-'+(++state.counter)+'-'+Date.now().toString(36);
 const escape=v=>String(v).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));
 function card(article) {const c=document.createElement('canvas');window.archiveKDDrawCard(c,article.title);return c.toDataURL('image/png')+'#';}
 function message(job,from,to,text){state.messages.push({id:id('message'),jobId:job.id,from,to,text,revision:job.revision,createdAt:now()});}
 function produce(article) {
  let job=state.jobs.find(j=>j.articleId===article.id);if(!job){job={id:id('job'),articleId:article.id,createdAt:now(),attempts:0,history:[]};state.jobs.push(job);}
  if(job.approval)job.history.push(structuredClone({revision:job.revision,artifacts:job.artifacts,approval:job.approval,card:job.card}));
  job.revision=id('revision');job.attempts++;job.status=article.body.trim()?'ready':'awaiting_content';job.steps={desk:'complete',social:article.body.trim()?'complete':'pending',card:article.body.trim()?'complete':'pending'};
  job.judgments={desk:{outcome:article.sourceUrl?'review_required':'source_required',warnings:['체험용 규칙 판단입니다. 사실 확인과 사진 사용 권한은 사용자가 확인해야 합니다.']},studio:{outcome:'text_card',warnings:['사진을 수집하지 않고 텍스트 카드만 만듭니다.']},automation:{outcome:'awaiting_human',warnings:['승인해도 공개 체험에서는 SNS 게시하지 않습니다.']}};
  job.controller={id:'archivekr',role:'main',requiresFinalApproval:true};job.photoReview={required:Array.isArray(article.sourceImages)&&article.sourceImages.length>0,status:'pending',reason:'사진 출처와 사용 권한을 사용자에게 확인합니다. 체험용 카드는 사진을 포함하지 않습니다.'};
  job.artifacts={label:'브라우저에서 원문을 발췌한 체험 결과 · AI 작성/외부 수집 없음',outline:article.title+'\n\n'+article.body,instagram:article.title+'\n\n'+article.body.slice(0,800)+'\n\n#archiveKD #체험원고',threads:article.title+'\n\n'+article.body.slice(0,350) ,kakao:article.title+'\n\n'+article.body.slice(0,500)+'\n\n원문: '+(article.sourceUrl||'체험용 원고')};job.card=card(article);job.cards=[{index:0,url:job.card,sourceImage:null,credit:'체험용 · 사진 없음'}];
  job.approval={status:job.history.length?'invalidated':'pending',revision:job.revision,reason:job.history.length?'원고가 바뀌어 이전 결정이 만료됐습니다. 새 제작물을 확인해 주세요.':''};
  job.publications={instagram:{status:'blocked',error:'체험용 · 실제 SNS 게시 연결 없음'},threads:{status:'blocked',error:'체험용 · 실제 SNS 게시 연결 없음'}};
  const photoCount=Array.isArray(article.sourceImages)?article.sourceImages.length:0;
  message(job,'automation','desk','새 기사를 가져왔습니다. 기사 기획과 카드 제작을 요청합니다.');message(job,'desk','studio',photoCount?'원고를 정리했습니다. 사진 '+photoCount+'장으로 카드뉴스 제작이 가능한가요?':'원고를 정리했습니다. 등록된 사진은 0장입니다. 텍스트 시안 제작이 가능한가요?');message(job,'studio','desk',photoCount?'가능합니다. 다만 사진 출처 확인이 필요합니다.':'텍스트 시안 제작은 가능합니다. 사진 카드 완성에는 사진 등록과 출처 확인이 필요합니다.');message(job,'archivekr','user','제작 초안이 준비됐습니다. 사진 사용 확인과 최종 게시를 결정해 주세요.');

 }
 if(!state.articles.length){const a={id:id('article'),title:'[체험원고] 콘텐츠와 독자를 잇는 새로운 이야기',body:'이 글은 archiveKD 화면과 승인 흐름을 확인하기 위한 가상 체험 원고입니다. 실제 콘텐츠 기사나 실제 취재 결과가 아닙니다.\n원고를 수정하면 카드와 SNS 문안이 다시 만들어지고 이전 승인은 만료됩니다.',organization:'체험용 자료',region:'',sourceUrl:'',origin:'manual',status:'draft',createdAt:now(),updatedAt:now()};state.articles.push(a);produce(a);save();}
 const fontsReady=Promise.allSettled([document.fonts.load('bold 84px ArchiveHead'),document.fonts.load('26px ArchiveBody')]).then(()=>{for(const j of state.jobs){if(!['pending','invalidated'].includes(j.approval?.status))continue;const a=state.articles.find(a=>a.id===j.articleId);if(a){j.card=card(a);j.cards=[{index:0,url:j.card,sourceImage:null,credit:'체험용 · 사진 없음'}];}}save();});
 if(state.brand!=='archiveKD'){
  for(const article of state.articles){
   if(article.title==='[체험원고] 영화와 관객을 잇는 새로운 이야기'){
    article.title='[체험원고] 콘텐츠와 독자를 잇는 새로운 이야기';
    article.body=article.body.replaceAll('archiveKR','archiveKD').replaceAll('MOVIST','콘텐츠');
   }
   produce(article);
  }
  state.brand='archiveKD';save();
 }
 const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
 const fail=(error,status=400)=>response({ok:false,error},status);
 window.fetch=async(input,options={})=>{
  await fontsReady;
  const u=new URL(typeof input==='string'?input:input.url,location.href),p=u.pathname,method=(options.method||'GET').toUpperCase();let body={};try{body=JSON.parse(options.body||'{}');}catch{return fail('잘못된 요청입니다.');}
  if(!p.startsWith('/api/'))return fail('공개 체험에서는 외부 네트워크 요청을 실행하지 않습니다.',403);
  try {
   if(p==='/api/desk/articles'&&method==='GET')return response({items:state.articles});
   if(p==='/api/desk/articles'&&method==='POST'){if(!body.title?.trim())return fail('제목을 입력해 주세요.');const a={...body,id:id('article'),body:body.body||'',status:'draft',origin:'manual',createdAt:now(),updatedAt:now()};state.articles.push(a);produce(a);save();return response({item:a},201);}
   const articleMatch=p.match(/^\/api\/desk\/articles\/([^/]+)(\/transition)?$/);
   if(articleMatch){const a=state.articles.find(a=>a.id===articleMatch[1]);if(!a)return fail('원고가 없습니다.',404);if(articleMatch[2]&&method==='POST'){if(!['draft','review','published'].includes(body.status))return fail('잘못된 상태입니다.');a.status=body.status;a.updatedAt=now();save();return response({item:a});}if(method==='PATCH'){if(a.status==='published')return fail('발행 상태를 초안으로 변경한 뒤 수정하세요.');if(!body.title?.trim())return fail('제목을 입력하세요.');const old=JSON.stringify([a.title,a.body,a.sourceUrl]);for(const k of ['title','body','organization','region','sourceUrl','deadline','questions'])if(k in body)a[k]=body[k];a.updatedAt=now();if(old!==JSON.stringify([a.title,a.body,a.sourceUrl]))produce(a);save();return response({item:a});}}
   if(p==='/api/automation/status')return response({...state,controller:{id:'archivekr',role:'main',requiresFinalApproval:true},targets,connections:{},baseline:{initialized:false,knownUrlCount:0},lastPollAt:null,lastPollError:'공개 체험: 실시간 콘텐츠 수집·SNS 게시는 연결하지 않습니다. 데이터는 이 브라우저에만 저장됩니다.'});
   if(p==='/api/automation/settings'&&method==='PATCH'){state.settings={...state.settings,...body,channels:{...state.settings.channels,...body.channels},pollingEnabled:false};save();return response({ok:true,settings:state.settings});}
   if(p==='/api/automation/ingest')return fail('공개 체험에서는 콘텐츠 기사를 실제 수집할 수 없습니다. 데스크에서 직접 체험 원고를 등록해 주세요.');
   if(p==='/api/automation/messages')return response({items:state.messages});
   if(p==='/api/automation/approvals')return response({items:state.jobs.map(j=>j.approval)});
   if(p==='/api/automation/jobs')return response({items:state.jobs});
   const jm=p.match(/^\/api\/automation\/jobs\/([^/]+)\/(decision|retry)$/);
   if(jm&&method==='POST'){const j=state.jobs.find(j=>j.id===jm[1]);if(!j)return fail('작업을 찾을 수 없습니다.',404);if(jm[2]==='retry'){save();return response({ok:true,job:j});}if(body.revision!==j.revision||j.approval.revision!==j.revision)return fail('제작 버전이 바뀌었습니다. 화면을 새로고침하고 다시 확인하세요.',409);if(!['pending','invalidated'].includes(j.approval.status))return fail('이미 결정한 버전입니다.',409);if(!['approve','reject','request_changes'].includes(body.decision))return fail('잘못된 결정입니다.');if(body.decision==='request_changes'&&!body.note?.trim())return fail('수정 요청 내용을 입력하세요.');if(body.decision==='approve'&&j.photoReview.required&&!body.photoRightsConfirmed)return fail('사진 사용 여부와 출처를 확인한 뒤 승인해 주세요.');if(body.decision==='approve'&&(!body.channels?.length||body.channels.some(c=>!['instagram','threads'].includes(c))))return fail('승인할 채널을 선택하세요.');if(body.decision==='approve'&&JSON.stringify(body.targets)!==JSON.stringify(targets))return fail('게시 대상이 변경됐습니다.',409);j.approval={status:{approve:'approved',reject:'rejected',request_changes:'changes_requested'}[body.decision],revision:j.revision,note:body.note||'',channels:body.channels||[],decidedAt:now(),origin:'local_manual',photoRightsConfirmed:body.photoRightsConfirmed===true,targets:structuredClone(targets)};j.judgments.automation.outcome={approve:'approved',reject:'human_rejected',request_changes:'revision_required'}[body.decision];message(j,'user',body.decision==='request_changes'?'desk':'automation',`${{approve:'사용자가 이 제작 버전을 승인했습니다. 체험용이므로 실제 게시하지 않습니다.',reject:'사용자가 게시를 거절했습니다.',request_changes:'사용자가 수정을 요청했습니다.'}[body.decision]} ${body.note||''}`);save();return response({ok:true,job:j});}
   return fail('공개 체험에서 지원하지 않는 요청입니다.',404);
  }catch(e){return fail('브라우저 저장 공간을 확인하세요. '+e.message,500);}
 };
 addEventListener('DOMContentLoaded',()=>{const b=document.createElement('aside');b.style.cssText='padding:14px 24px;background:#fff4ce;color:#3d310d;font:14px system-ui;position:relative;z-index:20';b.append(document.createTextNode('공개 체험용 · 이 브라우저에만 저장 · 실제 기사 수집/AI 생성/SNS 게시 없음. 승인 흐름과 원고 편집을 체험하세요. '));const reset=document.createElement('button');reset.textContent='체험 데이터 초기화';reset.onclick=()=>{if(confirm('이 브라우저의 체험 원고와 결정 기록을 초기화할까요?')){localStorage.removeItem(KEY);location.reload();}};b.append(reset);document.body.prepend(b);});
})();
