import { randomUUID } from 'node:crypto';
import { mkdirSync, writeFileSync, readFileSync } from 'node:fs';
import { resolve } from 'node:path';

const now = () => new Date().toISOString();
const defaults = { enabled: true, pollingEnabled: true, sourceUrl: 'https://www.movist.com/', pollSeconds: 300, pollingFirstRunBaseline: true, channels: { instagram: true, threads: true } };
const json = (body, status=200) => Response.json(body, {status});
export function movistUrl(value) {
  try { const u=new URL(value); if(u.protocol!=='https:' || !['movist.com','www.movist.com','m.movist.com'].includes(u.hostname) || u.port || u.username || u.password || value.length>2048) return null;u.hash='';u.searchParams.sort();return u.href; } catch {return null;}
}
function initialize(state) { state.automation ||= {settings:structuredClone(defaults),jobs:[],lastPollAt:null,lastPollError:null};state.automation.knownArticleUrls ||= [];state.automation.baselineAt ||= null;return state.automation; }
function publicJob(job) { return {...job,card:job.card?`/api/automation/jobs/${job.id}/card`:null}; }
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
  function enqueueArticle(articleId) {
    ensureActive();
    return update((a,state)=>{const article=state.articles.find(x=>x.id===articleId);if(!article)return null;
      const sourceUrl=article.sourceUrl?movistUrl(article.sourceUrl):null;
      const old=a.jobs.find(x=>x.articleId===articleId || (sourceUrl && x.sourceUrl===sourceUrl));if(old){if(['awaiting_content','ready','failed'].includes(old.status) && article.body?.trim() && old.sourceRevision!==article.updatedAt){old.status='queued';old.sourceRevision=article.updatedAt;old.card=false;}return old;}
      const job={id:randomUUID(),articleId,sourceUrl,status:'queued',createdAt:now(),updatedAt:now(),attempts:0,sourceRevision:article.updatedAt,steps:{desk:'pending',social:'pending',card:'pending'},publications:{}};a.jobs.push(job);return job;});
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
    if(stopped || !read().settings.enabled)return;
    const current=job.publications[channel];if(current?.retryAfter && Date.parse(current.retryAfter)>Date.now())return;if(['published','ambiguous','posting'].includes(current?.status))return;
    const settings=read().settings;
    const required=channel==='threads'?['THREADS_USER_ID','THREADS_ACCESS_TOKEN']:['INSTAGRAM_USER_ID','INSTAGRAM_ACCESS_TOKEN','ARCHIVEKR_PUBLIC_MEDIA_BASE_URL'];
    const missing=required.filter(key=>!env[key]);
    if(!settings.channels[channel] || missing.length){patchJob(job.id,j=>{j.publications[channel]={status:'blocked',error:!settings.channels[channel]?'자동 배포 채널이 연결되지 않았습니다.':`환경 설정 필요: ${missing.join(', ')}`};});return;}
    if(channel==='instagram') {
      try {const media=new URL(env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL);if(media.protocol!=='https:' || /^(localhost|127\.|10\.|192\.168\.|169\.254\.|\[)/.test(media.hostname))throw new Error();}catch{patchJob(job.id,j=>{j.publications[channel]={status:'blocked',error:'Instagram에는 공개 HTTPS 카드 이미지 주소가 필요합니다.'};});return;}
    }
    // Persist the intent before crossing the remote boundary. Never auto-retry uncertain writes.
    patchJob(job.id,j=>{j.publications[channel]={status:'posting',startedAt:now()};});
    const graph=channel==='threads'?'https://graph.threads.net/v1.0/':'https://graph.facebook.com/v23.0/';
    const account=env[channel==='threads'?'THREADS_USER_ID':'INSTAGRAM_USER_ID'];
    const token=env[channel==='threads'?'THREADS_ACCESS_TOKEN':'INSTAGRAM_ACCESS_TOKEN'];
    try {
      if(!/^\d+$/.test(account)){const error=new Error('게시 계정 ID 설정을 확인하세요.');error.definitive=true;throw error;}
      const remote=async(path,init)=>{
        ensureActive();
        const response=await (options.publishFetch||fetch)(graph+path,{...init,headers:{authorization:`Bearer ${token}`,...init.headers},signal:signal(),redirect:'error'});
        if([400,401,403,429].includes(response.status)){const error=new Error('게시 API가 요청을 거부했습니다. 계정 권한과 채널 설정을 확인하세요.');error.definitive=true;throw error;}
        if(!response.ok)throw new Error('remote-unknown');
        return response.json();
      };
      const post=async(path,params)=>{const data=await remote(path,{method:'POST',headers:{'content-type':'application/x-www-form-urlencoded'},body:new URLSearchParams(params)});if(!data.id)throw new Error('remote-post-failed');return data.id;};
      const params=channel==='threads'?{media_type:'TEXT',text:job.artifacts.threads}:{image_url:`${env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL.replace(/\/$/,'')}/api/automation/jobs/${job.id}/card`,caption:job.artifacts.instagram};
      const container=await post(`${account}/${channel==='threads'?'threads':'media'}`,params);
      patchJob(job.id,j=>{j.publications[channel].containerId=container;});
      if(channel==='instagram'){
        let finished=false;
        for(let attempt=0;attempt<30;attempt++){
          const status=await remote(`${container}?fields=status_code`,{method:'GET'});
          if(status.status_code==='FINISHED'){finished=true;break;}
          if(['ERROR','EXPIRED'].includes(status.status_code)){const error=new Error('Instagram 이미지 처리가 실패했습니다. 공개 카드 주소를 확인하세요.');error.definitive=true;throw error;}
          await pause(1000);
        }
        if(!finished){const error=new Error('Instagram 이미지 준비가 지연되어 게시하지 않았습니다.');error.definitive=true;throw error;}
      }
      const id=await post(`${account}/${channel==='threads'?'threads_publish':'media_publish'}`,{creation_id:container});
      patchJob(job.id,j=>{j.publications[channel]={status:'published',id,publishedAt:now()};});
    }catch(error){if(error.definitive){patchJob(job.id,j=>{j.publications[channel].status='blocked';j.publications[channel].error=error.message;j.publications[channel].retryAfter=new Date(Date.now()+60000).toISOString();});return;}patchJob(job.id,j=>{j.publications[channel].status='ambiguous';j.publications[channel].error='외부 게시 결과를 확인할 수 없습니다. 자동 재시도하지 않습니다. 해당 계정에서 확인하세요.';});}
  }
  async function processJob(job) {
    if(stopped || !read().settings.enabled)return;
    patchJob(job.id,j=>{j.status='processing';j.attempts++;j.error=null;});
    try {
      const article=context.read().articles.find(x=>x.id===job.articleId);if(!article?.body?.trim()){patchJob(job.id,j=>{j.status='awaiting_content';j.error='본문 등록을 기다리는 중입니다.';});return;}
      const summary=excerpts(article.body);
      const artifacts={label:'원문 발췌 기반 자동 제작 · 사실 확인 및 문맥 검토 필요',outline:`${article.title}\n\n원문 핵심 발췌\n${summary}`,instagram:`${article.title}\n\n${summary.slice(0,1400)}\n\n출처: ${article.sourceUrl||'편집 데스크 원고'}\n#archiveKR #영화뉴스`.slice(0,2200),threads:`${article.title}\n\n${summary.slice(0,300)}\n\n${article.sourceUrl||''}`.slice(0,500)};
      patchJob(job.id,j=>{j.artifacts=artifacts;j.steps.desk='complete';j.steps.social='complete';});
      update((a,state)=>{const item=state.articles.find(x=>x.id===job.articleId);item.automationJobId=job.id;item.production={method:'extractive',label:artifacts.label,outline:artifacts.outline};});
      if(!job.card){if(!options.renderCard)throw new Error('카드 제작 서버가 연결되지 않았습니다.');const bytes=Buffer.from(await options.renderCard({headline:article.title,body:summary,label:'archiveKR',sourceImage:article.sourceImages?.[0]||'',tag:'영화 뉴스',cover:true},{signal:controller.signal}));ensureActive();if(bytes.length<8 || bytes.subarray(0,8).toString('hex')!=='89504e470d0a1a0a')throw new Error('카드 이미지 생성에 실패했습니다.');mkdirSync(artifactDir,{recursive:true,mode:0o700});writeFileSync(resolve(artifactDir,`${job.id}.png`),bytes,{mode:0o600});patchJob(job.id,j=>{j.card=true;j.steps.card='complete';});}
      for(const channel of ['instagram','threads'])await publish(read().jobs.find(j=>j.id===job.id),channel);
      patchJob(job.id,j=>{j.status=Object.values(j.publications).every(p=>p.status==='published')?'published':'ready';});
    }catch(error){patchJob(job.id,j=>{j.status=stopped?'queued':'failed';j.error=stopped?'서버 종료로 제작이 중단되었습니다.':error.message;});}
  }
  async function tick() {
    if(running || stopped)return;running=true;
    try {let a=read();if(!a.settings.enabled)return;
      for(const job of read().jobs.filter(j=>j.status==='queued').slice(0,10))await processJob(job);
      // Credentials can be connected after artifact creation. Resume only blocked channels.
      for(const job of read().jobs.filter(j=>j.status==='ready' && j.card).slice(0,100)){for(const channel of ['instagram','threads'])if(job.publications[channel]?.status==='blocked')await publish(read().jobs.find(j=>j.id===job.id),channel);patchJob(job.id,j=>{if(Object.values(j.publications).every(p=>p.status==='published'))j.status='published';});}
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
    const path=new URL(request.url).pathname.replace(/^\/api\/automation/,'');
    if(request.method==='GET' && ['/status','/jobs','/settings'].includes(path)) {const a=read();return json({ok:true,...(path==='/settings'?{settings:a.settings}:path==='/jobs'?{items:a.jobs.map(publicJob)}:{settings:a.settings,jobs:a.jobs.map(publicJob),lastPollAt:a.lastPollAt,lastPollError:a.lastPollError,baseline:{initialized:!!a.baselineAt,initializedAt:a.baselineAt,knownUrlCount:a.knownArticleUrls.length},connections:Object.fromEntries(['THREADS_USER_ID','THREADS_ACCESS_TOKEN','INSTAGRAM_USER_ID','INSTAGRAM_ACCESS_TOKEN','ARCHIVEKR_PUBLIC_MEDIA_BASE_URL'].map(k=>[k,!!env[k]]))})});}
    const card=path.match(/^\/jobs\/([\w-]+)\/card$/);if(request.method==='GET' && card){const job=read().jobs.find(j=>j.id===card[1]);if(!job?.card)return json({ok:false,error:'카드가 아직 없습니다.'},404);try{return new Response(readFileSync(resolve(artifactDir,`${job.id}.png`)),{headers:{'content-type':'image/png'}});}catch{return json({ok:false,error:'카드 파일이 없습니다. 다시 제작하세요.'},404);}}
    let body;try{body=await request.json();if(!body || Array.isArray(body)||typeof body!=='object')throw new Error();}catch{return json({ok:false,error:'JSON 객체가 필요합니다.'},400);}
    if(request.method==='PATCH' && path==='/settings'){
      for(const key of ['enabled','pollingEnabled'])if(key in body && typeof body[key]!=='boolean')return json({ok:false,error:'활성화 값은 참/거짓이어야 합니다.'},400);
      if('sourceUrl' in body && !movistUrl(body.sourceUrl))return json({ok:false,error:'MOVIST 공식 HTTPS 주소만 사용할 수 있습니다.'},400);
      if('pollSeconds' in body && (!Number.isInteger(body.pollSeconds)||body.pollSeconds<60||body.pollSeconds>86400))return json({ok:false,error:'탐색 주기는 60~86400초입니다.'},400);
      if('channels' in body && (!body.channels || typeof body.channels!=='object' || Array.isArray(body.channels)||Object.entries(body.channels).some(([k,v])=>!['instagram','threads'].includes(k)||typeof v!=='boolean')))return json({ok:false,error:'채널 설정을 확인하세요.'},400);
      const settings=update(a=>{if(body.sourceUrl && body.sourceUrl!==a.settings.sourceUrl){a.knownArticleUrls=[];a.baselineAt=null;a.lastPollAt=null;}for(const key of ['enabled','pollingEnabled','sourceUrl','pollSeconds'])if(key in body)a.settings[key]=body[key];Object.assign(a.settings.channels,body.channels||{});return a.settings;});return json({ok:true,settings});
    }
    if(request.method==='POST' && path==='/ingest'){try{return json({ok:true,item:publicJob(await ingest(body.url))},201);}catch(error){return json({ok:false,error:error.message},400);}}
    const retry=path.match(/^\/jobs\/([\w-]+)\/retry$/);if(request.method==='POST' && retry){const job=read().jobs.find(j=>j.id===retry[1]);if(!job)return json({ok:false,error:'작업이 없습니다.'},404);if(Object.values(job.publications||{}).some(p=>p.status==='ambiguous'))return json({ok:false,error:'외부 게시 결과가 불명확하여 재시도할 수 없습니다. 해당 계정에서 게시 여부를 확인하세요.'},409);if(job.status==='processing')return json({ok:false,error:'작업이 진행 중입니다.'},409);patchJob(job.id,j=>{j.status='queued';for(const p of Object.values(j.publications||{}))if(p.status==='blocked')delete p.retryAfter;});return json({ok:true});}
    return json({ok:false,error:'자동화 경로가 없습니다.'},404);
  }
  return {enqueueArticle,ingest,ingestFetched,tick,handle,stop};
}
