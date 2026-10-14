import test from 'node:test';
import assert from 'node:assert/strict';
import { handleRelay } from '../scripts/relay.mjs';

test('public relay strips user query and headers and records provenance including zero results', async () => {
  let observed;
  const fetcher=async (url,options)=>{observed={url,options};return Response.json({ok:true,count:0,items:[]});};
  const response=await handleRelay(new Request('http://localhost/api/kstartup?ServiceKey=never-forward',{headers:{authorization:'never-forward',cookie:'never-forward'}}),{},fetcher);
  assert.equal(observed.url,'https://opportunity-radar-vert-pi.vercel.app/api/kstartup');
  assert.deepEqual(observed.options.headers,{accept:'application/json'});
  const data=await response.json();assert.equal(data.count,0);assert.equal(data.relay.name,'기존 기회레이더 수집 서버');
});
test('relay respects local keys, explicit opt-out and never forwards custom-source writes',async()=>{
  const fetcher=()=>{throw new Error('should not fetch');};
  assert.equal(await handleRelay(new Request('http://localhost/api/kstartup'),{DATA_GO_KR_SERVICE_KEY:'present'},fetcher),null);
  assert.equal(await handleRelay(new Request('http://localhost/api/mcst-rss'),{ARCHIVEKR_USE_RELAY:'0'},fetcher),null);
  assert.equal(await handleRelay(new Request('http://localhost/api/custom-source',{method:'POST'}),{},fetcher),null);
});
test('relay rejects malformed or failed upstream results instead of claiming successful zero',async()=>{
  const request=new Request('http://localhost/api/mcst-rss');
  assert.equal((await handleRelay(request,{},async()=>Response.json({ok:true,count:99,items:[]}))).status,502);
  assert.equal((await handleRelay(request,{},async()=>new Response('denied',{status:403}))).status,502);
});
