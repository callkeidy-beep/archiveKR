"""Build public fictional-sample site; never package databases or environment files."""
from pathlib import Path
import hashlib
import shutil
import subprocess
import sys
ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / 'site-dist'
if OUT.exists(): shutil.rmtree(OUT)
OUT.mkdir()
for name in ('index.html','app.js','style.css','favicon.svg','favicon.ico','apple-touch-icon.png'):
    shutil.copyfile(ROOT/'web'/name,OUT/name)
subprocess.run([sys.executable,'-m','app.export_sample',str(OUT/'sample.json')],cwd=ROOT,check=True)
version = hashlib.sha256(b''.join((OUT/name).read_bytes() for name in ('index.html','app.js','style.css','sample.json'))).hexdigest()[:16]
html = (OUT/'index.html').read_text()
html = html.replace('</head>','<script>window.CONTENT_MAKER_STATIC=true;</script></head>')
for name in ('app.js','style.css'):
    html=html.replace('./'+name+'"','./'+name+'?v='+version+'"')
(OUT/'index.html').write_text(html)
(OUT/'.nojekyll').touch()
print(f'Public sample built: site-dist/ ({version}); no real mail, secrets, DB or external API calls.')
