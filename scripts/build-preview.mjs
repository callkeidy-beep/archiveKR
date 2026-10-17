import { mkdir, readFile, writeFile, copyFile, rm } from 'node:fs/promises';
import { fileURLToPath } from 'node:url';
import path from 'node:path';
import { createHash } from 'node:crypto';
const root=fileURLToPath(new URL('../',import.meta.url));
const out=path.join(root,'site-dist');
await rm(out,{recursive:true,force:true});
await mkdir(out,{recursive:true});
let html=await readFile(path.join(root,'web/index.html'),'utf8');
html=html.replace('href="/style.css"','href="./style.css"').replace('data-src="/movist/"','data-src="./studio.html"').replace('<script type="module" src="/app.js"></script>','<script src="./card-renderer.js"></script><script src="./demo-api.js"></script><script type="module" src="./app.js"></script>').replace('로컬 개발 · 직원용','공개 체험 · 실제 게시 없음');
await writeFile(path.join(out,'index.html'),html);
for(const file of ['app.js','style.css','studio-bridge.js'])await copyFile(path.join(root,'web',file),path.join(out,file));
for(const file of ['demo-api.js','card-renderer.js','studio.html','README.md'])await copyFile(path.join(root,'site-preview',file),path.join(out,file));
await writeFile(path.join(out,'.nojekyll'),'');
console.log('Public demo built in site-dist/ (no server data or credentials).');

await mkdir(path.join(out,'fonts'),{recursive:true});
for (const file of ['head.ttf','body.ttf']) await copyFile(path.join(root,'modules/movist/fonts',file),path.join(out,'fonts',file));

// Version every page dependency so an older cached studio cannot survive a release.
const assets = ['app.js','style.css','card-renderer.js','demo-api.js','studio.html'];
const digest = createHash('sha256');
for (const file of ['index.html', ...assets]) digest.update(await readFile(path.join(out,file)));
const version = digest.digest('hex').slice(0,16);
for (const file of ['index.html','studio.html']) {
  let contents = await readFile(path.join(out,file),'utf8');
  for (const asset of assets) contents = contents.replaceAll('./'+asset+'"','./'+asset+'?v='+version+'"');
  await writeFile(path.join(out,file),contents);
}
