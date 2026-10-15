import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createStore} from '../../scripts/store.mjs';
import {createAutomation,movistUrl} from './server.mjs';
const png=Buffer.from('89504e470d0a1a0a0000','hex');
function setup(t,opts={}){const dir=mkdtempSync(join(tmpdir(),'archivekr-auto-'));t.after(()=>rmSync(dir,{recursive:true,force:true}));const store=createStore(join(dir,'store.json'));const options={artifactDir:join(dir,'cards'),env:{},fetchArticle:async()=>({title:'영화 소식',body:'공식 영화 소식입니다. 새로운 일정이 공개됐습니다.'}),renderCard:async()=>png,...opts};return {store,options,engine:createAutomation(store,options)};}
async function approve(engine,store,channels=['threads']){const job=store.read().automation.jobs[0];const response=await engine.handle(new Request(`http://local/api/automation/jobs/${job.id}/decision`,{method:'POST',body:JSON.stringify({decision:'approve',revision:job.revision,channels,targets:(await (await engine.handle(new Request('http://local/api/automation/status'))).json()).targets})}));assert.equal(response.status,200);}
test('only official HTTPS MOVIST URLs are accepted',()=>{for(const u of ['http://www.movist.com/a','https://evil.movist.com/a','https://www.movist.com.evil/a','https://u:p@www.movist.com/a','https://127.0.0.1/a'])assert.equal(movistUrl(u),null);assert.equal(movistUrl('https://www.movist.com/a#frag'),'https://www.movist.com/a');});
test('concurrent source ingestion deduplicates article and persists artifacts across restart',async t=>{const {store,engine,options}=setup(t);const [a,b]=await Promise.all([engine.ingest('https://www.movist.com/a'),engine.ingest('https://www.movist.com/a')]);assert.equal(a.id,b.id);assert.equal(store.read().articles.length,1);await engine.tick();let job=store.read().automation.jobs[0];assert.equal(job.status,'ready');assert.equal(job.steps.card,'complete');assert.equal(job.approval.status,'pending');assert.match(job.artifacts.threads,/공식 영화 소식/);const restarted=createAutomation(store,options);await restarted.tick();assert.equal(store.read().automation.jobs[0].attempts,1);const response=await restarted.handle(new Request(`http://local/api/automation/jobs/${job.id}/card`));assert.equal(response.headers.get('content-type'),'image/png');});
test('empty desk article waits and resumes once body arrives without overwriting original',async t=>{const {store,engine}=setup(t);store.update(s=>s.articles.push({id:'manual',title:'제목',body:'',updatedAt:'a'}));engine.enqueueArticle('manual');await engine.tick();assert.equal(store.read().automation.jobs[0].status,'awaiting_content');store.update(s=>{s.articles[0].body='기자가 직접 작성한 원고입니다.';s.articles[0].updatedAt='b';});engine.enqueueArticle('manual');await engine.tick();assert.equal(store.read().articles[0].body,'기자가 직접 작성한 원고입니다.');assert.equal(store.read().automation.jobs[0].status,'ready');});
test('failed local rendering can be retried after restart',async t=>{let fail=true;const {store,engine,options}=setup(t,{renderCard:async()=>{if(fail)throw new Error('renderer offline');return png;}});await engine.ingest('https://www.movist.com/retry');await engine.tick();assert.equal(store.read().automation.jobs[0].status,'failed');fail=false;const restarted=createAutomation(store,options),id=store.read().automation.jobs[0].id;await restarted.handle(new Request(`http://local/api/automation/jobs/${id}/retry`,{method:'POST',body:'{}'}));await restarted.tick();assert.equal(store.read().automation.jobs[0].steps.card,'complete');});
test('uncertain remote publish is never repeated by retry or restart',async t=>{let calls=0;const {store,engine,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'test'},publishFetch:async()=>{calls++;throw new Error('timeout');}});store.update(s=>{s.automation.settings.channels.threads=true;});await engine.ingest('https://www.movist.com/uncertain');await engine.tick();await approve(engine,store);await engine.tick();const id=store.read().automation.jobs[0].id;assert.equal(store.read().automation.jobs[0].publications.threads.status,'ambiguous');const restarted=createAutomation(store,options);const retry=await restarted.handle(new Request(`http://local/api/automation/jobs/${id}/retry`,{method:'POST',body:'{}'}));assert.equal(retry.status,409);await restarted.tick();assert.equal(calls,1);});
test('settings reject arbitrary feed destinations and invalid controls',async t=>{const {engine}=setup(t);const response=await engine.handle(new Request('http://local/api/automation/settings',{method:'PATCH',body:JSON.stringify({sourceUrl:'https://169.254.169.254/latest'})}));assert.equal(response.status,400);});
test('connected credentials automatically resume blocked delivery and never repost success',async t=>{
  let calls=0;const env={};const {store,engine}=setup(t,{env,publishFetch:async()=>Response.json({id:String(++calls)})});
  await engine.ingest('https://www.movist.com/resume');await engine.tick();assert.equal(calls,0);
  env.THREADS_USER_ID='123';env.THREADS_ACCESS_TOKEN='token';
  await approve(engine,store);await engine.tick();assert.equal(calls,2);assert.equal(store.read().automation.jobs[0].publications.threads.status,'published');
  await engine.tick();assert.equal(calls,2);
});
test('disabled automation holds queued articles until enabled',async t=>{
  const {store,engine}=setup(t);store.update(s=>{s.automation.settings.enabled=false;});await engine.ingest('https://www.movist.com/paused');await engine.tick();assert.equal(store.read().automation.jobs[0].status,'queued');
  store.update(s=>{s.automation.settings.enabled=true;});await engine.tick();assert.equal(store.read().automation.jobs[0].status,'ready');
});
test('pending article production happens before slow discovery',async t=>{
  const order=[];const {engine}=setup(t,{renderCard:async()=>{order.push('card');return png;},discoverArticles:async()=>{order.push('discovery');return [];}});await engine.ingest('https://www.movist.com/order');await engine.tick();assert.deepEqual(order,['card','discovery']);
});
test('first discovery establishes baseline, only new articles are ingested after restart',async t=>{
  let urls=['https://www.movist.com/old'];const {engine,store,options}=setup(t,{discoverArticles:async()=>urls});await engine.tick();assert.equal(store.read().articles.length,0);assert.equal(store.read().automation.knownArticleUrls.length,1);
  urls=[...urls,'https://www.movist.com/new'];store.update(s=>{s.automation.lastPollAt=null;});await engine.tick();assert.equal(store.read().articles.length,1);assert.equal(store.read().articles[0].sourceUrl,urls[1]);
  const restarted=createAutomation(store,options);store.update(s=>{s.automation.lastPollAt=null;});await restarted.tick();assert.equal(store.read().articles.length,1);
});
test('failed fresh source is retried and editor article interrupts remaining source collection',async t=>{
  const order=[];let engine,store,fail=true;
  const fixture=setup(t,{discoverArticles:async()=>['https://www.movist.com/a','https://www.movist.com/b'],fetchArticle:async url=>{
    order.push(url.endsWith('/a')?'fetch-a':'fetch-b');
    if(url.endsWith('/a') && fail){store.update(s=>s.articles.push({id:'editor',title:'수동 편집',body:'편집 원고',updatedAt:'1'}));engine.enqueueArticle('editor');throw new Error('source timeout');}
    return {title:'수집 기사',body:'수집 원문'};
  },renderCard:async data=>{order.push(data.headline==='수동 편집'?'editor-card':'source-card');return png;}});({engine,store}=fixture);
  store.update(s=>{s.automation.baselineAt=new Date().toISOString();});await engine.tick();assert.ok(order.indexOf('editor-card')<order.indexOf('fetch-b'));assert.equal(store.read().automation.knownArticleUrls.includes('https://www.movist.com/a'),false);
  fail=false;store.update(s=>{s.automation.lastPollAt=null;});await engine.tick();assert.equal(store.read().automation.knownArticleUrls.includes('https://www.movist.com/a'),true);
});
test('movie editor fetched article joins desk queue without refetch or duplicate URL variants',async t=>{
  let fetches=0;const {engine,store}=setup(t,{fetchArticle:async()=>{fetches++;return {title:'제목',body:'본문'};}});
  const source='https://www.movist.com/movist3d/read.asp?b=2&a=1#top';
  const first=engine.ingestFetched(source,{title:'에디터 영화 기사',body:'원문 본문'});
  const second=engine.ingestFetched(source,{title:'에디터 영화 기사',body:'원문 본문'});
  const third=await engine.ingest('https://www.movist.com/movist3d/read.asp?a=1&b=2');
  assert.equal(first.id,second.id);assert.equal(first.id,third.id);assert.equal(store.read().articles.length,1);assert.equal(fetches,0);assert.equal(store.read().articles[0].id,first.articleId);
});
test('definitive API refusal backs off and manual retry clears backoff',async t=>{
  let calls=0;const {engine,store}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async()=>{calls++;return Response.json({error:'do not expose'}, {status:401});}});
  await engine.ingest('https://www.movist.com/auth');await engine.tick();await approve(engine,store);await engine.tick();const job=store.read().automation.jobs[0];assert.equal(job.publications.threads.status,'blocked');assert.ok(Date.parse(job.publications.threads.retryAfter)>Date.now());assert.equal(calls,1);await engine.tick();assert.equal(calls,1);
  await engine.handle(new Request(`http://local/api/automation/jobs/${job.id}/retry`,{method:'POST',body:'{}'}));await engine.tick();assert.equal(calls,2);
});
test('Instagram waits for processed media before publishing and carries source photo into card',async t=>{
  const calls=[];let cardInput;const {engine,store}=setup(t,{env:{INSTAGRAM_USER_ID:'123',INSTAGRAM_ACCESS_TOKEN:'token',ARCHIVEKR_PUBLIC_MEDIA_BASE_URL:'https://archive.example'},pause:async()=>{},renderCard:async input=>{cardInput=input;return png;},publishFetch:async(url,init)=>{
    calls.push(init.method);if(init.method==='GET')return Response.json({status_code:calls.length===2?'IN_PROGRESS':'FINISHED'});return Response.json({id:calls.length===1?'container':'published'});
  }});
  engine.ingestFetched('https://www.movist.com/photo',{title:'영화',body:'기사 본문',images:['/api/movist/img/123456abcdef/photo.jpg','https://evil.test/photo.jpg','/etc/passwd']});await engine.tick();await approve(engine,store,['instagram']);await engine.tick();assert.deepEqual(calls,['POST','GET','GET','POST']);assert.equal(cardInput.label,'archiveKR');assert.equal(cardInput.sourceImage,'/api/movist/img/123456abcdef/photo.jpg');assert.equal(store.read().articles[0].sourceImages.length,1);assert.equal(store.read().automation.jobs[0].publications.instagram.status,'published');
});
test('stop aborts collection and prevents subsequent ingestion or queue processing',async t=>{
  let entered;const started=new Promise(resolve=>{entered=resolve;});const {engine,store}=setup(t,{fetchArticle:async(url,{signal})=>{entered();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));}});
  const pending=engine.ingest('https://www.movist.com/stop');await started;await engine.stop();await assert.rejects(pending);assert.equal(store.read().articles.length,0);assert.throws(()=>engine.ingestFetched('https://www.movist.com/later',{title:'제목',body:'본문'}));await engine.tick();assert.equal(store.read().articles.length,0);
});
test('stop during external request preserves ambiguous publication and waits for worker shutdown',async t=>{
  let entered;const started=new Promise(resolve=>{entered=resolve;});const {engine,store}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async(url,{signal})=>{entered();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));}});await engine.ingest('https://www.movist.com/post-stop');await engine.tick();await approve(engine,store);const work=engine.tick();await started;await engine.stop();await work;assert.equal(store.read().automation.jobs[0].publications.threads.status,'ambiguous');
});
test('credentials alone never authorize writes; approvals, messages and rule judgments persist',async t=>{
 let calls=0;const {engine,store,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async()=>Response.json({id:String(++calls)})});
 await engine.ingest('https://www.movist.com/gate');await engine.tick();await engine.tick();assert.equal(calls,0);
 let j=store.read().automation.jobs[0];assert.equal(j.approval.status,'pending');assert.equal(j.judgments.desk.method,'rules');const count=store.read().automation.messages.length;
 const restarted=createAutomation(store,options);await restarted.tick();assert.equal(store.read().automation.messages.length,count);
 await approve(restarted,store);await restarted.tick();assert.equal(calls,2);await restarted.tick();assert.equal(calls,2);
});
test('rejected and changes requested decisions survive retries and restart; changed content needs fresh approval',async t=>{
 const {engine,store,options}=setup(t);await engine.ingest('https://www.movist.com/reject');await engine.tick();let j=store.read().automation.jobs[0];
 const decide=async decision=>engine.handle(new Request(`http://local/api/automation/jobs/${j.id}/decision`,{method:'POST',body:JSON.stringify({decision,revision:j.revision,note:'출처와 문안을 수정해 주세요.'})}));
 assert.equal((await decide('reject')).status,200);const restarted=createAutomation(store,options);await restarted.tick();assert.equal(store.read().automation.jobs[0].approval.status,'rejected');
 assert.equal((await restarted.handle(new Request(`http://local/api/automation/jobs/${j.id}/retry`,{method:'POST',body:'{}'}))).status,409);
 const oldRevision=j.revision;store.update(s=>{s.articles[0].body='수정된 기사 본문';});await restarted.tick();j=store.read().automation.jobs[0];assert.notEqual(j.revision,oldRevision);assert.equal(j.approval.status,'pending');
 assert.equal((await restarted.handle(new Request(`http://local/api/automation/jobs/${j.id}/decision`,{method:'POST',body:JSON.stringify({decision:'approve',revision:oldRevision,channels:['threads'],targets:{threads:null}})}))).status,409);
 assert.equal((await restarted.handle(new Request(`http://local/api/automation/jobs/${j.id}/decision`,{method:'POST',body:JSON.stringify({decision:'request_changes',revision:j.revision,note:'이미지 변경'})}))).status,200);
 assert.equal(store.read().automation.messages.filter(m=>m.type==='changes_requested').length,2);
});
test('source edit during rendering discards stale output and never grants pending approval for it',async t=>{
 let begin,finish;const entered=new Promise(r=>begin=r),wait=new Promise(r=>finish=r);const {engine,store}=setup(t,{renderCard:async()=>{begin();await wait;return png;}});
 await engine.ingest('https://www.movist.com/render-race');const work=engine.tick();await entered;store.update(s=>{s.articles[0].body='수정 원고';});finish();await work;
 const j=store.read().automation.jobs[0];assert.equal(j.approval?.status,'pending');assert.match(j.artifacts.threads,/수정 원고/);
});
test('source edit during remote container creation prevents final publish; account changes require new approval',async t=>{
 let begin,finish,calls=0;const entered=new Promise(r=>begin=r),wait=new Promise(r=>finish=r);const env={THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'};
 const {engine,store}=setup(t,{env,publishFetch:async()=>{calls++;begin();await wait;return Response.json({id:'container'});}});
 await engine.ingest('https://www.movist.com/publish-race');await engine.tick();await approve(engine,store);const work=engine.tick();await entered;store.update(s=>{s.articles[0].body='교체 원고';});finish();await work;assert.equal(calls,1);assert.notEqual(store.read().automation.jobs[0].approval.status,'approved');
 await approve(engine,store);env.THREADS_USER_ID='456';await engine.tick();assert.equal(calls,1);assert.equal(store.read().automation.jobs[0].approval.status,'invalidated');
});
test('legacy ready jobs are not grandfathered and artifact edits invalidate exact approval',async t=>{
 let calls=0;const {engine,store,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async()=>{calls++;return Response.json({id:'x'});}});
 await engine.ingest('https://www.movist.com/legacy');await engine.tick();store.update(s=>{delete s.automation.jobs[0].approval;});const restarted=createAutomation(store,options);await restarted.tick();assert.equal(calls,0);assert.equal(store.read().automation.jobs[0].approval.status,'pending');await approve(restarted,store);
 const oldRevision=store.read().automation.jobs[0].revision;store.update(s=>{s.automation.jobs[0].artifacts.threads='승인되지 않은 문안';});
 const stale=await restarted.handle(new Request(`http://local/api/automation/jobs/${store.read().automation.jobs[0].id}/decision`,{method:'POST',body:JSON.stringify({decision:'approve',revision:oldRevision,channels:['threads'],targets:{threads:'123'}})}));assert.equal(stale.status,409);assert.equal(store.read().automation.jobs[0].status,'queued');
 await restarted.tick();assert.equal(calls,0);assert.equal(store.read().automation.jobs[0].approval.status,'pending');assert.notEqual(store.read().automation.jobs[0].artifacts.threads,'승인되지 않은 문안');await approve(restarted,store);
});
test('restart recovery visits every job even after a rejected job',async t=>{
 const {engine,store,options}=setup(t);await engine.ingest('https://www.movist.com/rejected-first');await engine.ingest('https://www.movist.com/posting-second');await engine.tick();
 store.update(s=>{s.automation.jobs[0].approval.status='rejected';s.automation.jobs[1].publications.threads={status:'posting'};s.automation.jobs[1].status='processing';});createAutomation(store,options);
 const jobs=store.read().automation.jobs;assert.equal(jobs[0].approval.status,'rejected');assert.equal(jobs[1].status,'queued');assert.equal(jobs[1].publications.threads.status,'ambiguous');
});
test('an old container cannot publish after a newer content revision is produced and approved',async t=>{
 let begin,finish;const entered=new Promise(r=>begin=r),wait=new Promise(r=>finish=r),requests=[];
 const {engine,store,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async(url,init)=>{requests.push({url,body:String(init.body)});begin();await wait;return Response.json({id:'old-container'});}});
 await engine.ingest('https://www.movist.com/new-approval-race');await engine.tick();await approve(engine,store);const oldRevision=store.read().automation.jobs[0].revision;const oldWork=engine.tick();await entered;
 store.update(s=>{s.articles[0].body='새 버전의 승인할 기사 본문';});
 // Simulate another worker producing the new revision while the old HTTP request is suspended.
 const second=createAutomation(store,options);await second.tick();assert.notEqual(store.read().automation.jobs[0].revision,oldRevision);await approve(second,store);finish();await oldWork;
 assert.equal(requests.length,1);assert.ok(!requests.some(r=>r.url.endsWith('threads_publish')));assert.equal(store.read().automation.jobs[0].approval.status,'approved');
});
test('a replacement decision for the same revision and account cannot authorize an older request',async t=>{
 let begin,finish;const entered=new Promise(r=>begin=r),wait=new Promise(r=>finish=r),requests=[];const env={THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'};
 const {engine,store}=setup(t,{env,publishFetch:async url=>{requests.push(url);begin();await wait;return Response.json({id:'old-container'});}});await engine.ingest('https://www.movist.com/decision-identity');await engine.tick();await approve(engine,store);const oldId=store.read().automation.jobs[0].approval.id,work=engine.tick();await entered;
 env.THREADS_USER_ID='456';await engine.handle(new Request('http://local/api/automation/status'));env.THREADS_USER_ID='123';await approve(engine,store);assert.notEqual(store.read().automation.jobs[0].approval.id,oldId);finish();await work;assert.equal(requests.length,1);
});

test('versioned immutable card stays available during source regeneration',async t=>{
 const {engine,store}=setup(t);await engine.ingest('https://www.movist.com/frozen-card');await engine.tick();const j=store.read().automation.jobs[0],oldRevision=j.revision;store.update(s=>{s.articles[0].body='수정된 기사';});
 const old=await engine.handle(new Request(`http://local/api/automation/jobs/${j.id}/card?revision=${oldRevision}`));assert.equal(old.status,200);assert.deepEqual(Buffer.from(await old.arrayBuffer()),png);assert.equal(store.read().automation.jobs[0].card,false);
 const latest=await engine.handle(new Request(`http://local/api/automation/jobs/${j.id}/card`));assert.equal(latest.status,404);
});
test('editing a published article creates a new approval and preserves publication history without automatic reposts',async t=>{
 let calls=0;const {engine,store,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async()=>Response.json({id:String(++calls)})});
 await engine.ingest('https://www.movist.com/published-edit');await engine.tick();await approve(engine,store);await engine.tick();const first=store.read().automation.jobs[0];assert.equal(first.status,'published');assert.equal(calls,2);
 store.update(s=>{s.articles[0].body='편집자가 수정한 두 번째 영화 기사 버전입니다.';});engine.enqueueArticle(first.articleId);await engine.tick();let next=store.read().automation.jobs[0];assert.equal(calls,2);assert.equal(next.approval.status,'pending');assert.notEqual(next.revision,first.revision);assert.equal(next.publicationHistory[0].revision,first.revision);assert.equal(next.publicationHistory[0].publications.threads.id,first.publications.threads.id);assert.deepEqual(next.publications,{});
 await engine.tick();assert.equal(calls,2);await approve(engine,store);await engine.tick();next=store.read().automation.jobs[0];assert.equal(calls,4);assert.equal(next.status,'published');assert.equal(next.publicationHistory.length,1);
 const restarted=createAutomation(store,options);await restarted.tick();assert.equal(calls,4);assert.equal(store.read().automation.jobs[0].publicationHistory.length,1);
});
test('legacy published jobs receive only a source baseline and never regenerate or republish on restart',async t=>{
 let calls=0;const {engine,store,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async()=>Response.json({id:String(++calls)})});await engine.ingest('https://www.movist.com/legacy-published');await engine.tick();await approve(engine,store);await engine.tick();store.update(s=>{const j=s.automation.jobs[0];delete j.sourceHash;delete j.approval;});const before=store.read().automation.jobs[0].attempts,restarted=createAutomation(store,options);await restarted.tick();const job=store.read().automation.jobs[0];assert.equal(job.status,'published');assert.equal(job.attempts,before);assert.equal(calls,2);assert.ok(job.sourceHash);assert.equal(job.publicationHistory,undefined);
});
test('Instagram media host belongs to approval snapshot while Threads-only ignores media host changes',async t=>{
 const env={INSTAGRAM_USER_ID:'123',INSTAGRAM_ACCESS_TOKEN:'token',ARCHIVEKR_PUBLIC_MEDIA_BASE_URL:'https://before.example',THREADS_USER_ID:'456',THREADS_ACCESS_TOKEN:'token'};let calls=0;const {engine,store}=setup(t,{env,publishFetch:async()=>{calls++;return Response.json({id:'x'});}});
 await engine.ingest('https://www.movist.com/media-binding');await engine.tick();await approve(engine,store,['instagram']);env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL='https://after.example';await engine.handle(new Request('http://local/api/automation/status'));assert.equal(store.read().automation.jobs[0].approval.status,'invalidated');assert.equal(calls,0);
 await approve(engine,store,['threads']);env.ARCHIVEKR_PUBLIC_MEDIA_BASE_URL='https://unrelated.example';await engine.handle(new Request('http://local/api/automation/status'));assert.equal(store.read().automation.jobs[0].approval.status,'approved');await engine.tick();assert.equal(calls,2);
});

test('changed published artifacts preserve history and require a fresh human decision',async t=>{
  let calls=0;const {engine,store}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'test'},publishFetch:async()=>Response.json({id:String(++calls)})});
  await engine.ingest('https://www.movist.com/artifact-history');await engine.tick();await approve(engine,store);assert.equal(store.read().automation.jobs[0].judgments.automation.outcome,'approved');await engine.tick();const published=store.read().automation.jobs[0];assert.equal(published.status,'published');
  store.update(s=>{s.automation.jobs[0].artifacts.threads+=' changed';});await engine.tick();let job=store.read().automation.jobs[0];assert.equal(calls,2);assert.equal(job.approval.status,'pending');assert.equal(job.publicationHistory[0].publications.threads.id,published.publications.threads.id);assert.equal(job.publications.threads,undefined);
  const rejection=await engine.handle(new Request(`http://local/api/automation/jobs/${job.id}/decision`,{method:'POST',body:JSON.stringify({decision:'reject',revision:job.revision,note:'다시 게시하지 않습니다.'})}));assert.equal(rejection.status,200);assert.equal(store.read().automation.jobs[0].judgments.automation.outcome,'human_rejected');await engine.tick();assert.equal(calls,2);
});
test('late successful final receipt belongs to old revision history and never marks changed content published',async t=>{
 let begin,finish,calls=0;const entered=new Promise(r=>begin=r),wait=new Promise(r=>finish=r);const {engine,store}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async url=>{calls++;if(calls===2){begin();await wait;}return Response.json({id:`remote-${calls}`});}});
 await engine.ingest('https://www.movist.com/late-receipt');await engine.tick();await approve(engine,store);const firstRevision=store.read().automation.jobs[0].revision,work=engine.tick();await entered;
 store.update(s=>{s.articles[0].body='두 번째 버전의 본문으로 수정합니다.';});engine.enqueueArticle(store.read().articles[0].id);finish();await work;let job=store.read().automation.jobs[0];assert.equal(job.approval.status,'pending');assert.deepEqual(job.publications,{});assert.equal(job.publicationHistory.find(h=>h.revision===firstRevision).publications.threads.id,'remote-2');assert.equal(job.publicationHistory.find(h=>h.revision===firstRevision).publications.threads.status,'published');
 await approve(engine,store);await engine.tick();job=store.read().automation.jobs[0];assert.equal(calls,4);assert.equal(job.publications.threads.id,'remote-4');assert.equal(job.status,'published');
});
