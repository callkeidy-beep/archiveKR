/* Public preview: browser-only storage. No server or external publishing. */
(() => {
 'use strict';
 const KEY='archivekr-public-preview-v1', now=()=>new Date().toISOString();
 const targets={instagram:'체험용 계정 · 실제 연결 없음',threads:'체험용 계정 · 실제 연결 없음',mediaBaseUrl:''};
 let state;
 try {state=JSON.parse(localStorage.getItem(KEY));} catch {}
 if(!state||state.schema!==1)state={schema:1,counter:0,articles:[],jobs:[],messages:[],settings:{enabled:true,pollingEnabled:false,pollSeconds:60,channels:{instagram:true,threads:true}}};
 const save=()=>localStorage.setItem(KEY,JSON.stringify(state));
 const id=prefix=>prefix+'-'+(++state.counter)+'-'+Date.now().toString(36);
 const escape=v=>String(v).replace(/[<>&"']/g,c=>({'<':'&lt;','>':'&gt;','&':'&amp;','"':'&quot;',"'":'&apos;'}[c]));
 function card(article) {
  const c=document.createElement('canvas');c.width=1080;c.height=1080;const x=c.getContext('2d');x.fillStyle='#173d38';x.fillRect(0,0,1080,1080);x.fillStyle='#d5f482';x.font='bold 38px sans-serif';x.fillText('archiveKR · 체험용 카드',70,100);x.fillStyle='white';x.font='bold 56px sans-serif';
  let line='',y=240;for(const ch of article.title){if(x.measureText(line+ch).width>930){x.fillText(line,70,y);y+=78;line='';}line+=ch;}x.fillText(line,70,y);x.font='30px sans-serif';x.fillText('규칙 기반 발췌 · 실제 취재·AI 생성 아님',70,910);x.fillText('외부 SNS에 게시되지 않습니다',70,970);return c.toDataURL('image/png')+'#';
 }
 function message(job,from,to,text){state.messages.push({id:id('message'),jobId:job.id,from,to,text,revision:job.revision,createdAt:now()});}
 function produce(article) {
  let job=state.jobs.find(j=>j.articleId===article.id);if(!job){job={id:id('job'),articleId:article.id,createdAt:now(),attempts:0,history:[]};state.jobs.push(job);}
  if(job.approval)job.history.push(structuredClone({revision:job.revision,artifacts:job.artifacts,approval:job.approval,card:job.card}));
  job.revision=id('revision');job.attempts++;job.status=article.body.trim()?'ready':'awaiting_content';job.steps={desk:'complete',social:article.body.trim()?'complete':'pending',card:article.body.trim()?'complete':'pending'};
  job.judgments={desk:{outcome:article.sourceUrl?'review_required':'source_required',warnings:['체험용 규칙 판단입니다. 사실 확인과 사진 사용 권한은 사용자가 확인해야 합니다.']},studio:{outcome:'text_card',warnings:['사진을 수집하지 않고 텍스트 카드만 만듭니다.']},automation:{outcome:'awaiting_human',warnings:['승인해도 공개 체험에서는 SNS 게시하지 않습니다.']}};
  job.artifacts={label:'브라우저에서 원문을 발췌한 체험 결과 · AI 작성/외부 수집 없음',outline:article.title+'\n\n'+article.body,instagram:article.title+'\n\n'+article.body.slice(0,800)+'\n\n#archiveKR #체험원고',threads:article.title+'\n\n'+article.body.slice(0,350)};job.card=card(article);
  job.approval={status:job.history.length?'invalidated':'pending',revision:job.revision,reason:job.history.length?'원고가 바뀌어 이전 결정이 만료됐습니다. 새 제작물을 확인해 주세요.':''};
  job.publications={instagram:{status:'blocked',error:'체험용 · 실제 SNS 게시 연결 없음'},threads:{status:'blocked',error:'체험용 · 실제 SNS 게시 연결 없음'}};
  message(job,'automation','desk','브라우저에 원고가 등록됐습니다. 본문과 출처를 검토해 주세요.');message(job,'desk','studio',article.body.trim()?'본문이 있습니다. 텍스트 카드 제작이 가능한가요?':'본문이 없어 제작을 보류합니다.');message(job,'studio','automation',article.body.trim()?'규칙 기반 문안과 텍스트 카드 초안을 만들었습니다. 사용자 확인을 요청합니다.':'본문 입력을 기다립니다.');message(job,'automation','user','최종 결정은 사용자가 합니다. 공개 체험은 실제 게시를 실행하지 않습니다.');
 }
 if(!state.articles.length){const a={id:id('article'),title:'[체험원고] 영화와 관객을 잇는 새로운 이야기',body:'이 글은 archiveKR 화면과 승인 흐름을 확인하기 위한 가상 체험 원고입니다. 실제 MOVIST 기사나 실제 취재 결과가 아닙니다.\n원고를 수정하면 카드와 SNS 문안이 다시 만들어지고 이전 승인은 만료됩니다.',organization:'체험용 자료',region:'',sourceUrl:'',origin:'manual',status:'draft',createdAt:now(),updatedAt:now()};state.articles.push(a);produce(a);save();}
 const response=(data,status=200)=>new Response(JSON.stringify(data),{status,headers:{'content-type':'application/json'}});
 const fail=(error,status=400)=>response({ok:false,error},status);
 window.fetch=async(input,options={})=>{
  const u=new URL(typeof input==='string'?input:input.url,location.href),p=u.pathname,method=(options.method||'GET').toUpperCase();let body={};try{body=JSON.parse(options.body||'{}');}catch{return fail('잘못된 요청입니다.');}
  if(!p.startsWith('/api/'))return fail('공개 체험에서는 외부 네트워크 요청을 실행하지 않습니다.',403);
  try {
   if(p==='/api/desk/articles'&&method==='GET')return response({items:state.articles});
   if(p==='/api/desk/articles'&&method==='POST'){if(!body.title?.trim())return fail('제목을 입력해 주세요.');const a={...body,id:id('article'),body:body.body||'',status:'draft',origin:'manual',createdAt:now(),updatedAt:now()};state.articles.push(a);produce(a);save();return response({item:a},201);}
   const articleMatch=p.match(/^\/api\/desk\/articles\/([^/]+)(\/transition)?$/);
   if(articleMatch){const a=state.articles.find(a=>a.id===articleMatch[1]);if(!a)return fail('원고가 없습니다.',404);if(articleMatch[2]&&method==='POST'){if(!['draft','review','published'].includes(body.status))return fail('잘못된 상태입니다.');a.status=body.status;a.updatedAt=now();save();return response({item:a});}if(method==='PATCH'){if(a.status==='published')return fail('발행 상태를 초안으로 변경한 뒤 수정하세요.');if(!body.title?.trim())return fail('제목을 입력하세요.');const old=JSON.stringify([a.title,a.body,a.sourceUrl]);for(const k of ['title','body','organization','region','sourceUrl','deadline','questions'])if(k in body)a[k]=body[k];a.updatedAt=now();if(old!==JSON.stringify([a.title,a.body,a.sourceUrl]))produce(a);save();return response({item:a});}}
   if(p==='/api/automation/status')return response({...state,targets,connections:{},baseline:{initialized:false,knownUrlCount:0},lastPollAt:null,lastPollError:'공개 체험: 실시간 MOVIST 수집·SNS 게시는 연결하지 않습니다. 데이터는 이 브라우저에만 저장됩니다.'});
   if(p==='/api/automation/settings'&&method==='PATCH'){state.settings={...state.settings,...body,channels:{...state.settings.channels,...body.channels},pollingEnabled:false};save();return response({ok:true,settings:state.settings});}
   if(p==='/api/automation/ingest')return fail('공개 체험에서는 MOVIST 기사를 실제 수집할 수 없습니다. 데스크에서 직접 체험 원고를 등록해 주세요.');
   if(p==='/api/automation/messages')return response({items:state.messages});
   if(p==='/api/automation/approvals')return response({items:state.jobs.map(j=>j.approval)});
   if(p==='/api/automation/jobs')return response({items:state.jobs});
   const jm=p.match(/^\/api\/automation\/jobs\/([^/]+)\/(decision|retry)$/);
   if(jm&&method==='POST'){const j=state.jobs.find(j=>j.id===jm[1]);if(!j)return fail('작업을 찾을 수 없습니다.',404);if(jm[2]==='retry'){save();return response({ok:true,job:j});}if(body.revision!==j.revision||j.approval.revision!==j.revision)return fail('제작 버전이 바뀌었습니다. 화면을 새로고침하고 다시 확인하세요.',409);if(!['pending','invalidated'].includes(j.approval.status))return fail('이미 결정한 버전입니다.',409);if(!['approve','reject','request_changes'].includes(body.decision))return fail('잘못된 결정입니다.');if(body.decision==='request_changes'&&!body.note?.trim())return fail('수정 요청 내용을 입력하세요.');if(body.decision==='approve'&&(!body.channels?.length||body.channels.some(c=>!['instagram','threads'].includes(c))))return fail('승인할 채널을 선택하세요.');if(body.decision==='approve'&&JSON.stringify(body.targets)!==JSON.stringify(targets))return fail('게시 대상이 변경됐습니다.',409);j.approval={status:{approve:'approved',reject:'rejected',request_changes:'changes_requested'}[body.decision],revision:j.revision,note:body.note||'',channels:body.channels||[],decidedAt:now(),origin:'local_manual',targets:structuredClone(targets)};j.judgments.automation.outcome={approve:'approved',reject:'human_rejected',request_changes:'revision_required'}[body.decision];message(j,'user',body.decision==='request_changes'?'desk':'automation',`${{approve:'사용자가 이 제작 버전을 승인했습니다. 체험용이므로 실제 게시하지 않습니다.',reject:'사용자가 게시를 거절했습니다.',request_changes:'사용자가 수정을 요청했습니다.'}[body.decision]} ${body.note||''}`);save();return response({ok:true,job:j});}
   return fail('공개 체험에서 지원하지 않는 요청입니다.',404);
  }catch(e){return fail('브라우저 저장 공간을 확인하세요. '+e.message,500);}
 };
 addEventListener('DOMContentLoaded',()=>{const b=document.createElement('aside');b.style.cssText='padding:14px 24px;background:#fff4ce;color:#3d310d;font:14px system-ui;position:relative;z-index:20';b.append(document.createTextNode('공개 체험용 · 이 브라우저에만 저장 · 실제 기사 수집/AI 생성/SNS 게시 없음. 승인 흐름과 원고 편집을 체험하세요. '));const reset=document.createElement('button');reset.textContent='체험 데이터 초기화';reset.onclick=()=>{if(confirm('이 브라우저의 체험 원고와 결정 기록을 초기화할까요?')){localStorage.removeItem(KEY);location.reload();}};b.append(reset);document.body.prepend(b);});
})();
