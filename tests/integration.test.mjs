import test from 'node:test';
import assert from 'node:assert/strict';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { setTimeout as delay } from 'node:timers/promises';

test('integrated desk hands off, publishes, persists after restart and unpublishes', async () => {
  const folder = mkdtempSync(join(tmpdir(), 'archivekr-integration-'));
  const port = '3199';
  let child;
  const base = `http://127.0.0.1:${port}`;
  async function start() {
    child = spawn(process.execPath, ['scripts/server.mjs'], { cwd: new URL('../', import.meta.url), env: { ...process.env, PORT: port, ARCHIVEKR_DATA_FILE: join(folder, 'data.json') }, stdio: 'ignore' });
    for (let n=0; n<50; n++) { if (child.exitCode !== null) throw new Error('Test server exited'); try { const r=await fetch(base+'/api/health'); if(r.ok)return; }catch{} await delay(50); }
    throw new Error('Test server did not become ready');
  }
  async function stop() { if (child && child.exitCode === null) { const exited = new Promise(r=>child.once('exit',r)); child.kill('SIGTERM'); await exited; } }
  async function request(path, method='GET', input) { const r=await fetch(base+path,{method,...(input?{headers:{'content-type':'application/json'},body:JSON.stringify(input)}:{})}); return { status:r.status, data:await r.json() }; }
  try {
    await start();
    const page=await fetch(base+'/radar');assert.equal(page.status,200);assert.match(await page.text(),/radar-bridge.js/);
    const cross=await fetch(base+'/api/desk/articles',{method:'POST',headers:{origin:'https://untrusted.example','content-type':'application/json'},body:JSON.stringify({title:'blocked'})});assert.equal(cross.status,403);
    const created=await request('/api/desk/articles','POST',{title:'인계 검증',origin:'opportunity',organization:'검증 기관',region:'강원',questions:['원문 확인']});assert.equal(created.status,201);const id=created.data.item.id;
    assert.equal((await request('/api/news/articles')).data.items.length,0);
    await request('/api/desk/articles/'+id,'PATCH',{body:'확인된 기사 본문',sourceUrl:'https://example.com/original'});
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'review'})).status,200);
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'published'})).status,200);
    const publicData=(await request('/api/news/articles')).data.items[0];assert.equal(publicData.id,id);assert.equal('questions' in publicData,false);
    await stop();await start();assert.equal((await request('/api/news/articles')).data.items[0].id,id);
    assert.equal((await request('/api/desk/articles/'+id+'/transition','POST',{status:'draft'})).status,200);
    assert.equal((await request('/api/news/articles')).data.items.length,0);
  } finally { await stop(); rmSync(folder,{recursive:true,force:true}); }
});
