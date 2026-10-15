import test from 'node:test';
import assert from 'node:assert/strict';
import {mkdtempSync,rmSync} from 'node:fs';
import {tmpdir} from 'node:os';
import {join} from 'node:path';
import {createStore} from '../../scripts/store.mjs';
import {createAutomation,movistUrl} from './server.mjs';
const png=Buffer.from('89504e470d0a1a0a0000','hex');
function setup(t,opts={}){const dir=mkdtempSync(join(tmpdir(),'archivekr-auto-'));t.after(()=>rmSync(dir,{recursive:true,force:true}));const store=createStore(join(dir,'store.json'));const options={artifactDir:join(dir,'cards'),env:{},fetchArticle:async()=>({title:'영화 소식',body:'공식 영화 소식입니다. 새로운 일정이 공개됐습니다.'}),renderCard:async()=>png,...opts};return {store,options,engine:createAutomation(store,options)};}
test('only official HTTPS MOVIST URLs are accepted',()=>{for(const u of ['http://www.movist.com/a','https://evil.movist.com/a','https://www.movist.com.evil/a','https://u:p@www.movist.com/a','https://127.0.0.1/a'])assert.equal(movistUrl(u),null);assert.equal(movistUrl('https://www.movist.com/a#frag'),'https://www.movist.com/a');});
test('concurrent source ingestion deduplicates article and persists artifacts across restart',async t=>{const {store,engine,options}=setup(t);const [a,b]=await Promise.all([engine.ingest('https://www.movist.com/a'),engine.ingest('https://www.movist.com/a')]);assert.equal(a.id,b.id);assert.equal(store.read().articles.length,1);await engine.tick();let job=store.read().automation.jobs[0];assert.equal(job.status,'ready');assert.equal(job.steps.card,'complete');assert.equal(job.publications.threads.status,'blocked');assert.match(job.artifacts.threads,/공식 영화 소식/);const restarted=createAutomation(store,options);await restarted.tick();assert.equal(store.read().automation.jobs[0].attempts,1);const response=await restarted.handle(new Request(`http://local/api/automation/jobs/${job.id}/card`));assert.equal(response.headers.get('content-type'),'image/png');});
test('empty desk article waits and resumes once body arrives without overwriting original',async t=>{const {store,engine}=setup(t);store.update(s=>s.articles.push({id:'manual',title:'제목',body:'',updatedAt:'a'}));engine.enqueueArticle('manual');await engine.tick();assert.equal(store.read().automation.jobs[0].status,'awaiting_content');store.update(s=>{s.articles[0].body='기자가 직접 작성한 원고입니다.';s.articles[0].updatedAt='b';});engine.enqueueArticle('manual');await engine.tick();assert.equal(store.read().articles[0].body,'기자가 직접 작성한 원고입니다.');assert.equal(store.read().automation.jobs[0].status,'ready');});
test('failed local rendering can be retried after restart',async t=>{let fail=true;const {store,engine,options}=setup(t,{renderCard:async()=>{if(fail)throw new Error('renderer offline');return png;}});await engine.ingest('https://www.movist.com/retry');await engine.tick();assert.equal(store.read().automation.jobs[0].status,'failed');fail=false;const restarted=createAutomation(store,options),id=store.read().automation.jobs[0].id;await restarted.handle(new Request(`http://local/api/automation/jobs/${id}/retry`,{method:'POST',body:'{}'}));await restarted.tick();assert.equal(store.read().automation.jobs[0].steps.card,'complete');});
test('uncertain remote publish is never repeated by retry or restart',async t=>{let calls=0;const {store,engine,options}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'test'},publishFetch:async()=>{calls++;throw new Error('timeout');}});store.update(s=>{s.automation.settings.channels.threads=true;});await engine.ingest('https://www.movist.com/uncertain');await engine.tick();const id=store.read().automation.jobs[0].id;assert.equal(store.read().automation.jobs[0].publications.threads.status,'ambiguous');const restarted=createAutomation(store,options);const retry=await restarted.handle(new Request(`http://local/api/automation/jobs/${id}/retry`,{method:'POST',body:'{}'}));assert.equal(retry.status,409);await restarted.tick();assert.equal(calls,1);});
test('settings reject arbitrary feed destinations and invalid controls',async t=>{const {engine}=setup(t);const response=await engine.handle(new Request('http://local/api/automation/settings',{method:'PATCH',body:JSON.stringify({sourceUrl:'https://169.254.169.254/latest'})}));assert.equal(response.status,400);});
test('connected credentials automatically resume blocked delivery and never repost success',async t=>{
  let calls=0;const env={};const {store,engine}=setup(t,{env,publishFetch:async()=>Response.json({id:String(++calls)})});
  await engine.ingest('https://www.movist.com/resume');await engine.tick();assert.equal(calls,0);
  env.THREADS_USER_ID='123';env.THREADS_ACCESS_TOKEN='token';
  await engine.tick();assert.equal(calls,2);assert.equal(store.read().automation.jobs[0].publications.threads.status,'published');
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
  await engine.ingest('https://www.movist.com/auth');await engine.tick();const job=store.read().automation.jobs[0];assert.equal(job.publications.threads.status,'blocked');assert.ok(Date.parse(job.publications.threads.retryAfter)>Date.now());assert.equal(calls,1);await engine.tick();assert.equal(calls,1);
  await engine.handle(new Request(`http://local/api/automation/jobs/${job.id}/retry`,{method:'POST',body:'{}'}));await engine.tick();assert.equal(calls,2);
});
test('Instagram waits for processed media before publishing and carries source photo into card',async t=>{
  const calls=[];let cardInput;const {engine,store}=setup(t,{env:{INSTAGRAM_USER_ID:'123',INSTAGRAM_ACCESS_TOKEN:'token',ARCHIVEKR_PUBLIC_MEDIA_BASE_URL:'https://archive.example'},pause:async()=>{},renderCard:async input=>{cardInput=input;return png;},publishFetch:async(url,init)=>{
    calls.push(init.method);if(init.method==='GET')return Response.json({status_code:calls.length===2?'IN_PROGRESS':'FINISHED'});return Response.json({id:calls.length===1?'container':'published'});
  }});
  engine.ingestFetched('https://www.movist.com/photo',{title:'영화',body:'기사 본문',images:['/api/movist/img/123456abcdef/photo.jpg','https://evil.test/photo.jpg','/etc/passwd']});await engine.tick();assert.deepEqual(calls,['POST','GET','GET','POST']);assert.equal(cardInput.label,'archiveKR');assert.equal(cardInput.sourceImage,'/api/movist/img/123456abcdef/photo.jpg');assert.equal(store.read().articles[0].sourceImages.length,1);assert.equal(store.read().automation.jobs[0].publications.instagram.status,'published');
});
test('stop aborts collection and prevents subsequent ingestion or queue processing',async t=>{
  let entered;const started=new Promise(resolve=>{entered=resolve;});const {engine,store}=setup(t,{fetchArticle:async(url,{signal})=>{entered();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));}});
  const pending=engine.ingest('https://www.movist.com/stop');await started;await engine.stop();await assert.rejects(pending);assert.equal(store.read().articles.length,0);assert.throws(()=>engine.ingestFetched('https://www.movist.com/later',{title:'제목',body:'본문'}));await engine.tick();assert.equal(store.read().articles.length,0);
});
test('stop during external request preserves ambiguous publication and waits for worker shutdown',async t=>{
  let entered;const started=new Promise(resolve=>{entered=resolve;});const {engine,store}=setup(t,{env:{THREADS_USER_ID:'123',THREADS_ACCESS_TOKEN:'token'},publishFetch:async(url,{signal})=>{entered();return new Promise((resolve,reject)=>signal.addEventListener('abort',()=>reject(new Error('aborted')),{once:true}));}});await engine.ingest('https://www.movist.com/post-stop');const work=engine.tick();await started;await engine.stop();await work;assert.equal(store.read().automation.jobs[0].publications.threads.status,'ambiguous');
});
