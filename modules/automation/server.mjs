import { randomUUID, createHash } from 'node:crypto';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const hash=value=>createHash('sha256').update(typeof value==='string'||Buffer.isBuffer(value)?value:JSON.stringify(value)).digest('hex');
const sourceHash=article=>hash(['movist-upload-final-2026-10-17',article?.title,article?.body,article?.sourceUrl,article?.sourceCredit,article?.sourceImages]);
const now = () => new Date().toISOString();
const defaults = { enabled: true, pollingEnabled: true, sourceUrl: 'https://www.movist.com/', pollSeconds: 300, pollingFirstRunBaseline: true, channels: { instagram: true, threads: true } };
const json = (body, status=200) => Response.json(body, {status});
export function movistUrl(value) {
  try { const u=new URL(value); if(u.protocol!=='https:' || !['movist.com','www.movist.com','m.movist.com'].includes(u.hostname) || u.port || u.username || u.password || value.length>2048) return null;u.hash='';u.searchParams.sort();return u.href; } catch {return null;}
}
function initialize(state) { state.automation ||= {settings:structuredClone(defaults),jobs:[],lastPollAt:null,lastPollError:null};state.automation.messages ||= [];state.automation.knownArticleUrls ||= [];state.automation.baselineAt ||= null;return state.automation; }
function publicJob(job) { return {...job,card:job.card?`/api/automation/jobs/${job.id}/card`:null,cards:(job.card&&job.revision?job.cardFiles||[]:[]).map((card,index)=>({index,url:`/api/automation/jobs/${job.id}/cards/${index}?revision=${job.revision}`,sourceImage:card.sourceImage||null,credit:card.credit||''}))}; }
const orchestration={controller:'archivekr',label:'archiveKR',method:'rules',permissions:{archivekr:['assign','coordinate','hold','request_human_approval'],automation:['collect','produce','publish_approved_revision'],desk:['edit','request_production'],studio:['render','request_photo_verification'],user:['confirm_photo_rights','approve','reject','request_changes']},finalPublicationAuthority:'user',policy:'하위 에이전트는 archiveKR의 제작 지시를 따르며 사진 사용 확인과 최종 게시 승인은 사용자만 결정합니다.'};
function excerpts(body) { return String(body||'').split(/(?<=[.!?다])\s+|\n+/).map(s=>s.trim()).filter(Boolean).slice(0,4).join('\n\n').slice(0,1800); }

export function createAutomation(context, options={}) {
  const env=options.env||process.env;
  const artifactDir=resolve(options.artifactDir||'.local/automation');
  const update=fn=>context.update(state=>fn(initialize(state),state));
  const read=()=>initialize(context.read());
  let running=false,stopped=false;
  const stopWaiters=[];
  const controller=new AbortController();
  const stop=()=>{stopped=true;controller.abort();return running?new Promise(resolve=>stopWaiters.push(resolve)):Promise.resolve();};
  const ensureActive=()=>{if(stopped)throw new Error('자동화 서버가 종료 중입니다.');};
  const signal=()=>AbortSignal.any([controller.signal,AbortSignal.timeout(20000)]);
  const pause=options.pause||((ms)=>new Promise((resolve,reject)=>{const abort=()=>{clearTimeout(timer);reject(new Error('stopped'));};const timer=setTimeout(()=>{controller.signal.removeEventListener('abort',abort);resolve();},ms);controller.signal.addEventListener('abort',abort,{once:true});if(stopped)abort();}));
  // A process that died during an external request cannot know whether it posted.
  update(a=>{for(const job of a.jobs){if(job.status==='processing')job.status='queued';for(const p of Object.values(job.publications||{}))if(p.status==='posting'){p.status='ambiguous';p.error='서버 재시작 중 게시 결과 불명확. 게시 계정에서 직접 확인하세요.';}}});
  const targets=()=>({...Object.fromEntries(['instagram','threads'].map(c=>[c,env[c==='threads'?'THREADS_USER_ID':'INSTAGRAM_USER_ID']||null])),mediaBaseUrl:env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL||null});
  function message(a,job,from,to,type,text,replyTo) {
    const revision=job.revision||job.sourceHash;
    const previous=a.messages.find(m=>m.jobId===job.id&&m.type===type&&m.from===from&&m.to===to&&m.revision===revision&&m.text===text);
    if(previous)return previous;
    const item={id:randomUUID(),jobId:job.id,from,to,type,text,revision,createdAt:now(),...(replyTo?{replyTo}: {})};a.messages.push(item);return item;
  }
  function invalidate(a,job,reason) {
    job.photoReview={required:!!job.photoReview?.required,status:job.photoReview?.required?'pending':'not_required',revision:null};
    if(job.approval?.status==='approved')job.approval={...job.approval,status:'invalidated',reason};
    if(job.judgments)job.judgments.automation={role:'automation',method:'rules',outcome:'awaiting_human',warnings:[reason],at:now()};
    message(a,job,'archivekr','user','approval_invalidated',reason);
  }
  function archivePublications(job) {
    if(Object.keys(job.publications||{}).length){job.publicationHistory||=[];job.publicationHistory.push({revision:job.revision||null,sourceHash:job.sourceHash||null,publications:structuredClone(job.publications),archivedAt:now()});job.publications={};}
  }
  function cardsIntact(j) {
    const files=j.cardFiles?.length?j.cardFiles:[{file:j.cardFile,hash:j.cardHash}];
    return files.every(c=>hash(readFileSync(resolve(artifactDir,c.file)))===c.hash)&&hash(files.map(c=>c.hash))===(j.cardSetHash||hash([j.cardHash]))&&(files.length===1?files[0].hash:hash(files.map(c=>c.hash)))===j.cardHash;
  }
  function synchronize() {
    update((a,state)=>{for(const job of a.jobs){
      const article=state.articles.find(x=>x.id===job.articleId), digest=sourceHash(article);
      if(job.status==='published'&&!job.sourceHash){job.sourceHash=digest;continue;}
      if(job.sourceHash!==digest){
        archivePublications(job);
        invalidate(a,job,'원문이 변경되어 다시 제작하고 승인받아야 합니다.');job.sourceHash=digest;job.card=false;job.revision=null;job.status='queued';}
      if(job.approval?.status==='approved'&&(job.approval.channels.some(c=>job.approval.targets[c]!==targets()[c])||(job.approval.channels.includes('instagram')&&job.approval.targets.mediaBaseUrl!==targets().mediaBaseUrl)))invalidate(a,job,'게시 계정이 변경되어 최종 승인이 필요합니다.');
      if(job.approval?.status==='approved'){let damaged=false;try{damaged=!cardsIntact(job)||hash([job.sourceHash,job.artifacts,job.cardHash])!==job.revision;}catch{damaged=true;}if(damaged){archivePublications(job);invalidate(a,job,'제작물이 변경되었거나 카드 파일을 확인할 수 없어 다시 제작하고 승인받아야 합니다.');job.status='queued';job.card=false;job.revision=null;}}
      if(job.status!=='published'&&job.card&&job.revision&&!job.approval)job.approval={status:'pending',revision:job.revision};
    }});
  }
  function validApproval(id, expected) {
    const state=context.read(), a=initialize(state), j=a.jobs.find(x=>x.id===id), approval=j?.approval;
    if(expected&&(j?.revision!==expected.revision||hash(approval)!==expected.approvalHash||!approval?.channels?.includes(expected.channel)))return false;
    if(!j||approval?.status!=='approved'||approval.revision!==j.revision||sourceHash(state.articles.find(x=>x.id===j.articleId))!==j.sourceHash)return false;
    if(approval.channels.some(c=>approval.targets[c]!==targets()[c])||(approval.channels.includes('instagram')&&approval.targets.mediaBaseUrl!==targets().mediaBaseUrl))return false;
    if(j.photoReview?.required&&(!approval.photoRightsConfirmed||j.photoReview.revision!==j.revision||j.photoReview.status!=='confirmed'))return false;
    try{return cardsIntact(j)&&hash([j.sourceHash,j.artifacts,j.cardHash])===j.revision;}catch{return false;}
  }
  function enqueueArticle(articleId) {
    ensureActive();
    synchronize();
    return update((a,state)=>{const article=state.articles.find(x=>x.id===articleId);if(!article)return null;
      const sourceUrl=article.sourceUrl?movistUrl(article.sourceUrl):null;
      const old=a.jobs.find(x=>x.articleId===articleId || (sourceUrl && x.sourceUrl===sourceUrl));if(old){if(['awaiting_content','ready','failed'].includes(old.status) && article.body?.trim() && old.sourceHash!==sourceHash(article)){invalidate(a,old,'원문 변경으로 승인이 만료되었습니다.');old.status='queued';old.sourceRevision=article.updatedAt;old.sourceHash=sourceHash(article);old.revision=null;old.card=false;}return old;}
      const job={id:randomUUID(),articleId,sourceUrl,status:'queued',createdAt:now(),updatedAt:now(),attempts:0,sourceRevision:article.updatedAt,sourceHash:sourceHash(article),steps:{desk:'pending',social:'pending',card:'pending'},publications:{}};a.jobs.push(job);const assignment=message(a,job,'archivekr','automation','assignment','새 기사 수집과 데스크·제작실 연결을 지시합니다. 최종 게시 결정은 사용자에게 요청하세요.');message(a,job,'automation','desk','article_received','새 기사를 가져왔습니다. 기사 기획과 카드 제작을 요청합니다.',assignment.id);return job;});
  }
  async function ingest(inputUrl) {
    ensureActive();
    const sourceUrl=movistUrl(inputUrl);if(!sourceUrl)throw new Error('MOVIST 공식 HTTPS 기사 주소가 필요합니다.');
    const existing=read().jobs.find(j=>j.sourceUrl===sourceUrl);if(existing)return existing;
    if(!options.fetchArticle)throw new Error('영화 기사 수집기가 연결되지 않았습니다.');
    const fetched=await options.fetchArticle(sourceUrl,{signal:controller.signal});
    return ingestFetched(sourceUrl,fetched);
  }
  function ingestFetched(inputUrl,fetched) {
    ensureActive();
    const sourceUrl=movistUrl(inputUrl);if(!sourceUrl)throw new Error('MOVIST 공식 HTTPS 기사 주소가 필요합니다.');
    if(typeof fetched?.title!=='string' || !fetched.title.trim() || typeof fetched?.body!=='string' || !fetched.body.trim())throw new Error('기사 제목과 본문을 확인할 수 없습니다.');
    // Recheck after network I/O: simultaneous ingestion must not duplicate articles.
    const articleId=update((a,state)=>{const old=a.jobs.find(j=>j.sourceUrl===sourceUrl);if(old)return old.articleId;const article={id:randomUUID(),title:fetched.title.slice(0,300),body:fetched.body.slice(0,100000),sourceUrl,organization:'MOVIST',origin:'movist',status:'draft',questions:[],createdAt:now(),updatedAt:now(),sourceCredit:String(fetched.credit||fetched.author||'').slice(0,1000),sourcePublishedAt:typeof fetched.publishedAt==='string'?fetched.publishedAt.slice(0,100):'',sourceImages:(Array.isArray(fetched.images)?fetched.images:[]).filter(path=>typeof path==='string' && /^\/api\/movist\/img\/[0-9a-f]{12}\/[a-z0-9._-]+$/i.test(path)).slice(0,20),automationGenerated:false};state.articles.push(article);return article.id;});
    return enqueueArticle(articleId);
  }
  function patchJob(id,fn){return update(a=>{const job=a.jobs.find(j=>j.id===id);if(!job)throw new Error('작업이 없습니다.');fn(job);job.updatedAt=now();return job;});}
  async function publish(job,channel) {
    if(stopped || !read().settings.enabled || !validApproval(job.id))return;
    job=read().jobs.find(j=>j.id===job.id);if(!job.approval.channels.includes(channel))return;
    const approvedSnapshot={revision:job.revision,approvalHash:hash(job.approval),channel};
    const attemptId=randomUUID();
    const recordPublication=change=>patchJob(job.id,j=>{
      let publications=j.publications;
      if(publications[channel]?.attemptId!==attemptId||j.revision!==approvedSnapshot.revision||hash(j.approval)!==approvedSnapshot.approvalHash){
        const displaced=publications[channel]?.attemptId===attemptId?publications[channel]:null;
        if(displaced)delete publications[channel];
        j.publicationHistory||=[];let historical=j.publicationHistory.find(h=>h.publications?.[channel]?.attemptId===attemptId);
        if(!historical){historical={revision:approvedSnapshot.revision,approvalId:job.approval.id,archivedAt:now(),publications:displaced?{[channel]:displaced}:{}};j.publicationHistory.push(historical);}
        publications=historical.publications;
      }
      const previous=publications[channel]||{attemptId,revision:approvedSnapshot.revision,approvalId:job.approval.id};publications[channel]=change(previous);
    });
    const current=job.publications[channel];if(current?.retryAfter && Date.parse(current.retryAfter)>Date.now())return;if(['published','ambiguous','posting'].includes(current?.status))return;
    const settings=read().settings;
    const required=channel==='threads'?['THREADS_USER_ID','THREADS_ACCESS_TOKEN']:['INSTAGRAM_USER_ID','INSTAGRAM_ACCESS_TOKEN','ARCHIVEKR_PUBLIC_MEDIA_BASE_URL'];
    const missing=required.filter(key=>!env[key]);
    if(!settings.channels[channel] || missing.length){patchJob(job.id,j=>{j.publications[channel]={status:'blocked',error:!settings.channels[channel]?'자동 배포 채널이 연결되지 않았습니다.':`환경 설정 필요: ${missing.join(', ')}`};});return;}
    if(channel==='instagram') {
      try {const media=new URL(env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL);if(media.protocol!=='https:' || /^(localhost|127\.|10\.|192\.168\.|169\.254\.|\[)/.test(media.hostname))throw new Error();}catch{patchJob(job.id,j=>{j.publications[channel]={status:'blocked',error:'Instagram에는 공개 HTTPS 카드 이미지 주소가 필요합니다.'};});return;}
    }
    // Persist the intent before crossing the remote boundary. Never auto-retry uncertain writes.
    patchJob(job.id,j=>{j.publications[channel]={status:'posting',startedAt:now(),attemptId,revision:approvedSnapshot.revision,approvalId:job.approval.id};});
    const graph=channel==='threads'?'https://graph.threads.net/v1.0/':'https://graph.facebook.com/v23.0/';
    const account=env[channel==='threads'?'THREADS_USER_ID':'INSTAGRAM_USER_ID'];
    const token=env[channel==='threads'?'THREADS_ACCESS_TOKEN':'INSTAGRAM_ACCESS_TOKEN'];
    try {
      if(!/^\d+$/.test(account)){const error=new Error('게시 계정 ID 설정을 확인하세요.');error.definitive=true;throw error;}
      const remote=async(path,init)=>{
        ensureActive();
        if(!read().settings.enabled||!read().settings.channels[channel]||!validApproval(job.id,approvedSnapshot)){const error=new Error('승인 내용이 변경되어 게시를 중단했습니다.');error.approvalInvalid=true;throw error;}
        const response=await (options.publishFetch||fetch)(graph+path,{...init,headers:{authorization:`Bearer ${token}`,...init.headers},signal:signal(),redirect:'error'});
        if([400,401,403,429].includes(response.status)){const error=new Error('게시 API가 요청을 거부했습니다. 계정 권한과 채널 설정을 확인하세요.');error.definitive=true;throw error;}
        if(!response.ok)throw new Error('remote-unknown');
        return response.json();
      };
      const post=async(path,params)=>{const data=await remote(path,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams(params)});if(!data.id)throw new Error('remote-post-failed');return data.id;};
      const waitForInstagram=async container=>{
        for(let attempt=0;attempt<30;attempt++){
          const status=await remote(`${container}?fields=status_code`,{method:'GET'});
          if(status.status_code==='FINISHED')return;
          if(['ERROR','EXPIRED'].includes(status.status_code)){const error=new Error('Instagram 이미지 처리가 실패했습니다. 공개 카드 주소를 확인하세요.');error.definitive=true;throw error;}
          await pause(1000);
        }
        const error=new Error('Instagram 이미지 준비가 지연되어 게시하지 않았습니다.');error.definitive=true;throw error;
      };
      const base=env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL?.replace(/\/$/,'');
      let params;
      if(channel==='threads')params={media_type:'TEXT',text:job.artifacts.threads};
      else if(job.cardFiles?.length>1){
        const children=[];
        for(let index=0;index<job.cardFiles.length;index++){
          const child=await post(`${account}/media`,{image_url:`${base}/api/automation/jobs/${job.id}/cards/${index}?revision=${job.revision}`,is_carousel_item:'true'});
          await waitForInstagram(child);children.push(child);
        }
        params={media_type:'CAROUSEL',children:children.join(','),caption:job.artifacts.instagram};
      }else params={image_url:`${base}/api/automation/jobs/${job.id}/card?revision=${job.revision}`,caption:job.artifacts.instagram};
      const container=await post(`${account}/${channel==='threads'?'threads':'media'}`,params);
      if(!validApproval(job.id,approvedSnapshot)){const error=new Error('승인이 만료되었습니다.');error.approvalInvalid=true;throw error;}
      recordPublication(p=>({...p,containerId:container}));
      if(channel==='instagram')await waitForInstagram(container);
      const id=await post(`${account}/${channel==='threads'?'threads_publish':'media_publish'}`,{creation_id:container});
      recordPublication(p=>({...p,status:'published',id,publishedAt:now()}));
    }catch(error){if(error.approvalInvalid){recordPublication(p=>({...p,status:'blocked',error:error.message}));synchronize();return;}if(error.definitive){recordPublication(p=>({...p,status:'blocked',error:error.message,retryAfter:new Date(Date.now()+60000).toISOString()}));return;}recordPublication(p=>({...p,status:'ambiguous',error:'외부 게시 결과를 확인할 수 없습니다. 자동 재시도하지 않습니다. 해당 계정에서 확인하세요.'}));}
  }
  async function processJob(job) {
    if(stopped || !read().settings.enabled)return;
    patchJob(job.id,j=>{j.status='processing';j.attempts++;j.error=null;});
    try {
      const article=context.read().articles.find(x=>x.id===job.articleId);if(!article?.body?.trim()){patchJob(job.id,j=>{j.status='awaiting_content';j.error='본문 등록을 기다리는 중입니다.';});return;}
      const capturedHash=sourceHash(article);
      const summary=excerpts(article.body);
      patchJob(job.id,j=>{j.judgments={desk:{role:'desk',method:'rules',outcome:article.sourceUrl?'review_required':'source_required',warnings:article.sourceUrl?['원문 발췌의 사실과 문맥을 사람이 확인해야 합니다.']:['원문 출처를 확인하세요.'],at:now()},studio:{role:'studio',method:'rules',outcome:article.sourceImages?.length?'photo_available':'text_card',warnings:article.sourceImages?.length?['사진 사용 권한을 확인하세요.']:['원문 사진이 없어 텍스트 카드를 제작합니다.'],at:now()},automation:{role:'automation',method:'rules',outcome:job.approval?.status==='approved'?'approved':'awaiting_human',warnings:['최종 승인된 제작 버전·채널·계정만 게시'],at:now()}};});
      update(a=>{const j=a.jobs.find(x=>x.id===job.id);const m=message(a,j,'desk','studio','production_request',`원고를 정리했습니다. 사진 ${article.sourceImages?.length||0}장으로 카드뉴스 제작이 가능한가요?`,a.messages.findLast(m=>m.jobId===j.id&&m.type==='article_received')?.id);message(a,j,'studio','desk','production_response',article.sourceImages?.length?'가능합니다. 다만 사진 출처와 사용 권한 확인이 필요합니다.':'원문 사진이 없어 사진 카드 제작은 어렵습니다. 텍스트 카드 초안은 제작 가능합니다.',m.id);});
      const artifacts={kakao:`${article.title}\n\n${summary.slice(0,900)}\n\n기사 보기: ${article.sourceUrl||'편집 데스크 원고'}`,label:'원문 발췌 기반 자동 제작 · 사실 확인 및 문맥 검토 필요',outline:`${article.title}\n\n원문 핵심 발췌\n${summary}`,instagram:`${article.title}\n\n${summary.slice(0,1400)}\n\n출처: ${article.sourceUrl||'편집 데스크 원고'}\n#archiveKR #영화뉴스`.slice(0,2200),threads:`${article.title}\n\n${summary.slice(0,300)}\n\n${article.sourceUrl||''}`.slice(0,500)};
      patchJob(job.id,j=>{j.artifacts=artifacts;j.steps.desk='complete';j.steps.social='complete';});
      update((a,state)=>{const item=state.articles.find(x=>x.id===job.articleId);item.automationJobId=job.id;item.production={method:'extractive',label:artifacts.label,outline:artifacts.outline};});
      if(!job.card){
        if(!options.renderCards&&!options.renderCard)throw new Error('카드 제작 서버가 연결되지 않았습니다.');
        const payload={headline:article.title,body:summary,label:'archiveKR',sourceImages:article.sourceImages||[],sourceCredit:article.sourceCredit||'',sourceImage:article.sourceImages?.[0],tag:'영화 뉴스',cover:true};
        const rendered=options.renderCards?await options.renderCards(payload,{signal:controller.signal}):[await options.renderCard(payload,{signal:controller.signal})];
        const buffers=rendered.map(bytes=>Buffer.from(bytes));if(!buffers.length||buffers.length>10||buffers.some(bytes=>bytes.length<8||bytes.subarray(0,8).toString('hex')!=='89504e470d0a1a0a'))throw new Error('카드 이미지 생성에 실패했습니다.');
        mkdirSync(artifactDir,{recursive:true,mode:0o700});
        const cardHashes=buffers.map(hash),cardSetHash=hash(cardHashes),cardHash=buffers.length===1?cardHashes[0]:cardSetHash,revision=hash([capturedHash,artifacts,cardHash]);
        const cardFiles=buffers.map((bytes,index)=>{const file=index===0?`${job.id}-${revision}.png`:`${job.id}-${revision}-${index}.png`;writeFileSync(resolve(artifactDir,file),bytes,{mode:0o600});return {file,hash:cardHashes[index],sourceImage:article.sourceImages?.[index],credit:article.sourceCredit||''};});
        if(sourceHash(context.read().articles.find(x=>x.id===job.articleId))!==capturedHash){synchronize();return;}
        patchJob(job.id,j=>{j.card=true;j.cardHash=cardHash;j.cardSetHash=cardSetHash;j.cardFile=cardFiles[0].file;j.cardFiles=cardFiles;j.revision=revision;j.sourceHash=capturedHash;j.steps.card='complete';j.photoReview={required:!!article.sourceImages?.length,status:article.sourceImages?.length?'pending':'not_required',revision};j.orchestration={controller:'archivekr',phase:'awaiting_user',revision};j.approval={status:'pending',revision};});
        update(a=>{const j=a.jobs.find(x=>x.id===job.id);const completed=message(a,j,'studio','archivekr','production_complete','카드와 Instagram·Threads·카카오용 문안을 제작했습니다. 사진 사용 확인과 최종 승인을 요청해 주세요.',a.messages.findLast(m=>m.jobId===j.id&&m.type==='production_response')?.id);message(a,j,'archivekr','user','approval_requested','제작 초안이 준비됐습니다. 사진 사용 확인과 최종 게시를 결정해 주세요.',completed.id);});
      }
      for(const channel of ['instagram','threads'])await publish(read().jobs.find(j=>j.id===job.id),channel);
      patchJob(job.id,j=>{j.status=j.approval?.status==='approved'&&j.approval.channels.every(c=>j.publications[c]?.status==='published')?'published':'ready';});
    }catch(error){patchJob(job.id,j=>{j.status=stopped?'queued':'failed';j.error=stopped?'서버 종료로 제작이 중단되었습니다.':error.message;});update(a=>{const j=a.jobs.find(x=>x.id===job.id);message(a,j,'studio','desk','production_failed',j.error);});}
  }
  async function tick() {
    if(running || stopped)return;running=true;
    try {synchronize();let a=read();if(!a.settings.enabled)return;
      for(const job of read().jobs.filter(j=>j.status==='queued').slice(0,10))await processJob(job);
      // Credentials can be connected after artifact creation. Resume only blocked channels.
      for(const job of read().jobs.filter(j=>j.status==='ready' && j.card).slice(0,100)){for(const channel of ['instagram','threads'])if(!job.publications[channel] || job.publications[channel]?.status==='blocked')await publish(read().jobs.find(j=>j.id===job.id),channel);patchJob(job.id,j=>{if(j.approval?.status==='approved' && j.approval.channels.every(c=>j.publications[c]?.status==='published'))j.status='published';});}
      a=read();
      if(stopped)return;
      if(a.settings.pollingEnabled && options.discoverArticles && (!a.lastPollAt || Date.now()-Date.parse(a.lastPollAt)>=a.settings.pollSeconds*1000)){
        update(a=>{a.lastPollAt=now();});
        try{
          const urls=[...new Set((await options.discoverArticles(a.settings.sourceUrl,{signal:controller.signal})).map(movistUrl).filter(Boolean))].slice(0,20);
          if(stopped)return;
          if(!read().baselineAt && a.settings.pollingFirstRunBaseline!==false){
            update(a=>{a.knownArticleUrls=[...new Set([...a.knownArticleUrls,...urls])];a.baselineAt=now();a.lastPollError=null;});
          }else{
            let failures=0;
            for(const url of urls){
              if(stopped || !read().settings.enabled)break;
              // An editor may register a new article while source requests are in flight.
              for(const job of read().jobs.filter(j=>j.status==='queued').slice(0,10))await processJob(job);
              if(read().knownArticleUrls.includes(url))continue;
              try{await ingest(url);if(stopped)return;update(a=>{if(!a.knownArticleUrls.includes(url))a.knownArticleUrls.push(url);});}catch{failures++;}
              for(const job of read().jobs.filter(j=>j.status==='queued').slice(0,10))await processJob(job);
            }
            update(a=>{a.lastPollError=failures?`${failures}개 기사 수집 실패. 다음 탐색에서 다시 확인합니다.`:null;});
          }
        }catch{update(a=>{a.lastPollError='MOVIST 신규 기사 탐색에 실패했습니다. 출처 연결을 확인하세요.';});}
      }
      for(const job of read().jobs.filter(j=>j.status==='queued').slice(0,10))await processJob(job);
    }finally{running=false;for(const resolve of stopWaiters.splice(0))resolve();}
  }
  async function handle(request) {
    synchronize();
    const path=new URL(request.url).pathname.replace(/^\/api\/automation/,'');
    if(request.method==='GET' && ['/status','/jobs','/settings','/messages','/approvals'].includes(path)) {const a=read();return json({ok:true,...(path==='/messages'?{items:a.messages}:path==='/approvals'?{items:a.jobs.filter(j=>j.approval).map(publicJob)}:path==='/settings'?{settings:a.settings}:path==='/jobs'?{items:a.jobs.map(publicJob)}:{orchestrator:orchestration,settings:a.settings,jobs:a.jobs.map(publicJob),messages:a.messages,targets:targets(),lastPollAt:a.lastPollAt,lastPollError:a.lastPollError,baseline:{initialized:!!a.baselineAt,initializedAt:a.baselineAt,knownUrlCount:a.knownArticleUrls.length},connections:Object.fromEntries(['THREADS_USER_ID','THREADS_ACCESS_TOKEN','INSTAGRAM_USER_ID','INSTAGRAM_ACCESS_TOKEN','ARCHIVEKR_PUBLIC_MEDIA_BASE_URL'].map(k=>[k,!!env[k]]))})});}
    const cardPart=path.match(/^\/jobs\/([\w-]+)\/cards\/(\d+)$/);if(request.method==='GET'&&cardPart){const job=read().jobs.find(j=>j.id===cardPart[1]),revision=new URL(request.url).searchParams.get('revision')||job?.revision,index=Number(cardPart[2]);if(!job||!revision||!/^[a-f0-9]{64}$/.test(revision)||index>20)return json({ok:false,error:'카드 버전을 확인하세요.'},404);try{return new Response(readFileSync(resolve(artifactDir,index===0?`${job.id}-${revision}.png`:`${job.id}-${revision}-${index}.png`)),{headers:{'content-type':'image/png'}});}catch{return json({ok:false,error:'카드가 없습니다.'},404);}}
    const card=path.match(/^\/jobs\/([\w-]+)\/card$/);if(request.method==='GET' && card){const job=read().jobs.find(j=>j.id===card[1]);const requestedRevision=new URL(request.url).searchParams.get('revision');if(!job||(!requestedRevision&&!job.card))return json({ok:false,error:'카드가 아직 없습니다.'},404);if(requestedRevision&&!/^[a-f0-9]{64}$/.test(requestedRevision))return json({ok:false,error:'제작 버전을 확인하세요.'},400);try{return new Response(readFileSync(resolve(artifactDir, new URL(request.url).searchParams.has('revision')?`${job.id}-${new URL(request.url).searchParams.get('revision')}.png`:(job.cardFile||`${job.id}.png`))),{headers:{'content-type':'image/png'}});}catch{return json({ok:false,error:'카드 파일이 없습니다. 다시 제작하세요.'},404);}}
    let body;try{body=await request.json();if(!body || Array.isArray(body)||typeof body!=='object')throw new Error();}catch{return json({ok:false,error:'JSON 객체가 필요합니다.'},400);}
    const decision=path.match(/^\/jobs\/([\w-]+)\/decision$/);
    if(request.method==='POST'&&decision){
      const job=read().jobs.find(j=>j.id===decision[1]);if(!job)return json({ok:false,error:'작업이 없습니다.'},404);
      if(!['approve','reject','request_changes'].includes(body.decision)||typeof body.revision!=='string'||(body.note!==undefined&&typeof body.note!=='string'))return json({ok:false,error:'결정과 제작 버전을 확인하세요.'},400);
      if(!job.revision||body.revision!==job.revision||job.status!=='ready'||!['pending','invalidated'].includes(job.approval?.status))return json({ok:false,error:'제작물이 변경되었습니다. 최신 버전을 확인하세요.'},409);
      if(body.decision==='approve'&&job.photoReview?.required&&body.photoRightsConfirmed!==true)return json({ok:false,error:'사진 출처와 사용 권한을 확인한 후 승인하세요.'},400);
      if(body.decision==='approve'&&(!Array.isArray(body.channels)||!body.channels.length||new Set(body.channels).size!==body.channels.length||body.channels.some(c=>!['instagram','threads'].includes(c))))return json({ok:false,error:'게시 채널을 선택하세요.'},400);
      if(body.decision==='approve'&&(body.channels.some(c=>!body.targets||body.targets[c]!==targets()[c])||(body.channels.includes('instagram')&&body.targets?.mediaBaseUrl!==targets().mediaBaseUrl)))return json({ok:false,error:'게시 계정이 변경되었습니다. 새 계정을 확인하세요.'},409);
      const item=update(a=>{const j=a.jobs.find(j=>j.id===job.id);j.approval={id:randomUUID(),status:{approve:'approved',reject:'rejected',request_changes:'changes_requested'}[body.decision],revision:j.revision,channels:body.decision==='approve'?body.channels:[],targets:targets(),photoRightsConfirmed:body.decision==='approve'&&body.photoRightsConfirmed===true,actor:'user',decidedAt:now(),note:(body.note||'').slice(0,4000)};if(j.photoReview)j.photoReview.status=body.decision==='approve'?(j.photoReview.required?'confirmed':'not_required'):'pending';j.orchestration={controller:'archivekr',phase:body.decision==='approve'?'approved_for_delivery':'awaiting_revision',revision:j.revision};j.judgments||={};j.judgments.automation={role:'automation',method:'rules',outcome:{approve:'approved',reject:'human_rejected',request_changes:'revision_required'}[body.decision],warnings:[body.decision==='approve'?'승인된 제작 버전·채널·계정만 게시합니다.':body.note||'사용자 결정을 반영했습니다.'],at:now()};const m=message(a,j,'user','archivekr','human_decision',`${j.approval.status}: ${j.approval.note}`);message(a,j,'archivekr','automation',body.decision==='approve'?'delivery_authorized':'delivery_held',body.decision==='approve'?`사용자 승인 버전 ${j.revision}의 ${j.approval.channels.join(', ')} 게시만 허용합니다.`:'사용자 결정에 따라 외부 게시를 보류합니다.',m.id);if(body.decision==='request_changes'){message(a,j,'archivekr','desk','changes_requested',j.approval.note||'사용자가 수정을 요청했습니다.',m.id);message(a,j,'archivekr','studio','changes_requested',j.approval.note||'사용자가 수정을 요청했습니다.',m.id);}return j;});return json({ok:true,item:publicJob(item)});
    }
    if(request.method==='PATCH' && path==='/settings'){
      for(const key of ['enabled','pollingEnabled'])if(key in body && typeof body[key]!=='boolean')return json({ok:false,error:'활성화 값은 참/거짓이어야 합니다.'},400);
      if('sourceUrl' in body && !movistUrl(body.sourceUrl))return json({ok:false,error:'MOVIST 공식 HTTPS 주소만 사용할 수 있습니다.'},400);
      if('pollSeconds' in body && (!Number.isInteger(body.pollSeconds)||body.pollSeconds<60||body.pollSeconds>86400))return json({ok:false,error:'탐색 주기는 60~86400초입니다.'},400);
      if('channels' in body && (!body.channels || typeof body.channels!=='object' || Array.isArray(body.channels)||Object.entries(body.channels).some(([k,v])=>!['instagram','threads'].includes(k)||typeof v!=='boolean')))return json({ok:false,error:'채널 설정을 확인하세요.'},400);
      const settings=update(a=>{if(body.sourceUrl && body.sourceUrl!==a.settings.sourceUrl){a.knownArticleUrls=[];a.baselineAt=null;a.lastPollAt=null;}for(const key of ['enabled','pollingEnabled','sourceUrl','pollSeconds'])if(key in body)a.settings[key]=body[key];Object.assign(a.settings.channels,body.channels||{});return a.settings;});return json({ok:true,settings});
    }
    if(request.method==='POST' && path==='/ingest'){try{return json({ok:true,item:publicJob(await ingest(body.url))},201);}catch(error){return json({ok:false,error:error.message},400);}}
    const retry=path.match(/^\/jobs\/([\w-]+)\/retry$/);if(request.method==='POST' && retry){const job=read().jobs.find(j=>j.id===retry[1]);if(!job)return json({ok:false,error:'작업이 없습니다.'},404);if(Object.values(job.publications||{}).some(p=>p.status==='ambiguous'))return json({ok:false,error:'외부 게시 결과가 불명확하여 재시도할 수 없습니다. 해당 계정에서 게시 여부를 확인하세요.'},409);if(['rejected','changes_requested'].includes(job.approval?.status))return json({ok:false,error:'원고를 수정한 후 다시 제작하세요.'},409);if(job.status==='processing')return json({ok:false,error:'작업이 진행 중입니다.'},409);patchJob(job.id,j=>{j.status='queued';for(const p of Object.values(j.publications||{}))if(p.status==='blocked')delete p.retryAfter;});return json({ok:true});}
    return json({ok:false,error:'자동화 경로가 없습니다.'},404);
  }
  return {enqueueArticle,ingest,ingestFetched,tick,handle,stop};
}
