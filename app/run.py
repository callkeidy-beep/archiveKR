"""Launch sample-only server. Bind loopback by default."""
import os
import uvicorn
from pathlib import Path
from dotenv import load_dotenv
# Server-only secrets; never override securely injected deployment values.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=False)

if __name__ == '__main__':
    uvicorn.run('app.main:app', host=os.environ.get('CONTENT_MAKER_HOST',os.environ.get('HOST','127.0.0.1')), port=int(os.environ.get('CONTENT_MAKER_PORT',os.environ.get('PORT','3100'))), access_log=False)
