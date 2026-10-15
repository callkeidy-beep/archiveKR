import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

test('desk queues production, persists after restart and preserves suspended modules', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'archivekr-integration-'));
  const port = '3199';
  let child;
  const base = `http://127.0.0.1:${port}`;
  async function start() {
    child = spawn(process.execPath, ['scripts/server.mjs'], { cwd: new URL('../', import.meta.url), env: { ...process.env, PORT: port, ARCHIVEKR_DATA_FILE: join(folder, 'data.json'), ARCHIVEKR_AUTOMATION_BACKGROUND: '0' }, stdio: 'ignore' });
    for (let n=0; n<50; n++) { if (child.exitCode !== null) throw new Error('Test server exited'); try { const r=await fetch(base+'/api/health'); if(r.ok)return; }catch{} await delay(50); }
    throw new Error('Test server did not become ready');
  }
  async function stop() { if (child && child.exitCode === null) { const exited = new Promise(r=>child.once('exit',r)); child.kill('SIGTERM'); await exited; } }
  async function request(path, method='GET', input) { const r=await fetch(base+path,{method,...(input?{headers:{'content-type':'application/json'},body:JSON.stringify(input)}:{})}); return { status:r.status, data:await r.json() }; }
  try {
    await start();
    const page=await fetch(base+'/radar');assert.equal(page.status,410);assert.equal((await request('/api/news/articles')).status,410);const health=await request('/api/health');assert.deepEqual(health.data.modules,['desk','movist','automation']);assert.deepEqual(health.data.suspendedModules,['radar','news']);
    const cross=await fetch(base+'/api/desk/articles',{method:'POST',headers:{origin:'https://untrusted.example','content-type':'application/json'},body:JSON.stringify({title:'blocked'})});assert.equal(cross.status,403);
    const created=await request('/api/desk/articles','POST',{title:'인계 검증',origin:'opportunity',organization:'검증 기관',region:'강원',questions:['원문 확인']});assert.equal(created.status,201);const id=created.data.item.id;
    assert.equal((await request('/api/automation/jobs')).data.items[0].articleId,id);
    await request('/api/desk/articles/'+id,'PATCH',{body:'확인된 기사 본문',sourceUrl:'https://example.com/original'});
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'review'})).status,200);
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'published'})).status,200);
    assert.equal((await request('/api/desk/articles')).data.items[0].status,'published');
    await stop();await start();assert.equal((await request('/api/desk/articles')).data.items[0].id,id);assert.equal((await request('/api/automation/jobs')).data.items.length,1);
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'draft'})).status,200);
    assert.equal((await request('/api/automation/jobs')).data.items[0].articleId,id);
  } finally { await stop(); rmSync(folder,{recursive:true,force:true}); }
});

test('saving a desk article automatically produces outputs and studio fetch joins the same queue',async()=>{
  const {createServer}=await import('node:http');
  const folder=mkdtempSync(join(tmpdir(),'archivekr-auto-http-'));
  let renderCalls=0;
  const movie=createServer((req,res)=>{
    res.setHeader('content-type','application/json');
    if(req.url.startsWith('/api/movist/latest'))return res.end(JSON.stringify({items:[]}));
    if(req.url.startsWith('/api/movist/fetch'))return res.end(JSON.stringify({title:'MOVIST 연결 검증',body:'가져온 원문입니다. 외부 게시하지 않는 테스트입니다.',images:[]}));
    if(req.url==='/api/movist/cards'){let body='';req.on('data',chunk=>body+=chunk);req.on('end',()=>{const data=JSON.parse(body);if('sourceImage' in data && !/^\/api\/movist\/img\/[0-9a-f]{12}\/[a-z0-9._-]+$/i.test(data.sourceImage)){res.writeHead(400);return res.end(JSON.stringify({error:'invalid source image'}));}renderCalls++;res.setHeader('content-type','image/png');res.end(Buffer.from('89504e470d0a1a0a0000','hex'));});return;}
    res.writeHead(404);res.end('{}');
  });
  await new Promise(r=>movie.listen(0,'127.0.0.1',r));
  const base='http://127.0.0.1:3197';
  const child=spawn(process.execPath,['scripts/server.mjs'],{cwd:new URL('../',import.meta.url),env:{...process.env,PORT:'3197',ARCHIVEKR_DATA_FILE:join(folder,'data.json'),ARCHIVEKR_MOVIST_PORT:String(movie.address().port),ARCHIVEKR_AUTOMATION_BACKGROUND:'1',THREADS_USER_ID:'',THREADS_ACCESS_TOKEN:'',INSTAGRAM_USER_ID:'',INSTAGRAM_ACCESS_TOKEN:'',ARCHIVEKR_PUBLIC_MEDIA_BASE_URL:''},stdio:'ignore'});
  async function jobs(){return (await(await fetch(base+'/api/automation/jobs')).json()).items;}
  async function waitReady(count){for(let n=0;n<100;n++){const items=await jobs();if(items.length===count && items.every(j=>j.status==='ready'))return items;await delay(50);}throw new Error('Automatic generation did not finish');}
  try{
    for(let n=0;n<50;n++){if(child.exitCode!==null)throw new Error('Test server exited');try{if((await fetch(base+'/api/health')).ok)break;}catch{}await delay(50);}
    const created=await fetch(base+'/api/desk/articles',{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify({title:'자동 제작 검증',body:'등록과 동시에 처리할 테스트 원고입니다.'})});assert.equal(created.status,201);
    const first=(await waitReady(1))[0];assert.equal(first.approval.status,'pending');assert.equal(first.publications.threads,undefined);assert.match(first.artifacts.instagram,/등록과 동시에/);assert.equal(first.steps.card,'complete');
    const inbox=await(await fetch(base+'/api/automation/approvals')).json();assert.equal(inbox.items.length,1);
    const messages=await(await fetch(base+'/api/automation/messages')).json();assert.ok(messages.items.some(m=>m.from==='desk'&&m.to==='studio'));assert.ok(messages.items.some(m=>m.type==='approval_requested'));
    const status=await(await fetch(base+'/api/automation/status')).json();
    const payload={decision:'approve',revision:first.revision,channels:['threads'],targets:status.targets};
    const denied=await fetch(base+`/api/automation/jobs/${first.id}/decision`,{method:'POST',headers:{'content-type':'application/json'},body:JSON.stringify(payload)});assert.equal(denied.status,403);
    const allowed=await fetch(base+`/api/automation/jobs/${first.id}/decision`,{method:'POST',headers:{'content-type':'application/json',origin:base},body:JSON.stringify(payload)});assert.equal(allowed.status,200);
    await fetch(base+`/api/desk/articles/${first.articleId}`,{method:'PATCH',headers:{'content-type':'application/json'},body:JSON.stringify({body:'승인 이후 수정된 새로운 원고입니다.'})});
    let revised;for(let n=0;n<100;n++){revised=(await jobs())[0];if(revised.status==='ready'&&revised.approval.status==='pending')break;await delay(50);}assert.notEqual(revised.revision,first.revision);assert.equal(revised.approval.status,'pending');
    const stale=await fetch(base+`/api/automation/jobs/${first.id}/decision`,{method:'POST',headers:{'content-type':'application/json',origin:base},body:JSON.stringify(payload)});assert.equal(stale.status,409);
    const changes=await fetch(base+`/api/automation/jobs/${first.id}/decision`,{method:'POST',headers:{'content-type':'application/json',origin:base},body:JSON.stringify({decision:'request_changes',revision:revised.revision,note:'제목을 다듬어 주세요.'})});assert.equal(changes.status,200);
    const revisions=await(await fetch(base+'/api/automation/messages')).json();assert.ok(revisions.items.some(m=>m.to==='studio'&&m.type==='changes_requested'));

    const input='/api/movist/fetch?url='+encodeURIComponent('https://www.movist.com/movist3d/view.asp?type=13&id=atc000000012345');
    const fetched=await(await fetch(base+input)).json();assert.ok(fetched.archiveKR.articleId);
    const fetchedAgain=await(await fetch(base+input)).json();assert.equal(fetchedAgain.archiveKR.jobId,fetched.archiveKR.jobId);
    const items=await waitReady(2);assert.equal(items.filter(j=>j.articleId===fetched.archiveKR.articleId).length,1);assert.equal(renderCalls,3);
  }finally{
    if(child.exitCode===null){const done=new Promise(r=>child.once('exit',r));child.kill('SIGTERM');await done;}
    await new Promise(r=>movie.close(r));rmSync(folder,{recursive:true,force:true});
  }
});
