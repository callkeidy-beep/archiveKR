"""Sample newsroom plus separately authenticated, read-only Daum connection tests."""
import os
from pathlib import Path
import sqlite3
from datetime import datetime, timezone
from contextlib import contextmanager
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.exceptions import RequestValidationError
from fastapi.exception_handlers import request_validation_exception_handler
from app.mail_service import router as mail_router
from pydantic import BaseModel, Field, ConfigDict

from app.domain import ROOT, bootstrap, load_sources

app = FastAPI(title='콘텐츠메이커 엔진', version='0.3.0')

@app.exception_handler(RequestValidationError)
async def safe_validation_error(request: Request, exc: RequestValidationError):
    if request.url.path.startswith('/api/mail/'):
        return JSONResponse({'detail':'메일 설정 요청 형식을 확인하세요.'},status_code=422)
    return await request_validation_exception_handler(request,exc)

app.include_router(mail_router)
from app.outlook_service import router as outlook_router
app.include_router(outlook_router)


def database_path():
    return Path(os.environ.get('CONTENT_MAKER_DB', ROOT / '.local' / 'content-maker.sqlite3'))


@contextmanager
def database():
    path = database_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(path), timeout=10)
    os.chmod(path, 0o600)
    connection.row_factory = sqlite3.Row
    connection.execute('CREATE TABLE IF NOT EXISTS evaluations (candidate_id TEXT PRIMARY KEY, rating INTEGER NOT NULL CHECK(rating BETWEEN 1 AND 5), tag TEXT NOT NULL, comment TEXT NOT NULL, updated_at TEXT NOT NULL)')
    try:
        yield connection
        connection.commit()
    finally: connection.close()


def evaluations():
    with database() as connection:
        return [{'candidateId': row['candidate_id'], 'rating': row['rating'], 'tag': row['tag'], 'comment': row['comment'], 'updatedAt': row['updated_at']} for row in connection.execute('SELECT * FROM evaluations ORDER BY updated_at DESC')]


@app.middleware('http')
async def sample_request_policy(request: Request, call_next):
    if request.method not in ('GET', 'HEAD', 'OPTIONS'):
        origin = request.headers.get('origin')
        if origin:
            parsed = urlsplit(origin)
            expected = urlsplit(str(request.base_url))
            if parsed.scheme != expected.scheme or parsed.netloc != expected.netloc:
                return JSONResponse({'detail':'다른 사이트에서 보낸 변경 요청은 허용하지 않습니다.'}, status_code=403)
        if request.headers.get('sec-fetch-site') == 'cross-site':
            return JSONResponse({'detail':'교차 사이트 변경 요청은 허용하지 않습니다.'}, status_code=403)
        try:
            if int(request.headers.get('content-length','0')) > 16384:
                return JSONResponse({'detail':'요청이 너무 큽니다.'}, status_code=413)
        except ValueError:
            return JSONResponse({'detail':'잘못된 요청 크기입니다.'}, status_code=400)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'same-origin'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/health')
def health():
    return {'ok':True, 'name':'콘텐츠메이커 엔진', 'phase':1, 'mode':'sample', 'imapConnected':False, 'aiConnected':False, 'publishingEnabled':False,'mailConnectionTestAvailable':True}


@app.get('/api/bootstrap')
def get_bootstrap(): return bootstrap(evaluations())


@app.get('/api/sources/{source_id}')
def get_source(source_id: str):
    item = next((source for source in load_sources() if source['id'] == source_id), None)
    if not item: raise HTTPException(404, '자료가 없습니다.')
    return item


@app.get('/api/evaluations')
def get_evaluations(): return {'items':evaluations()}


class EvaluationInput(BaseModel):
    model_config = ConfigDict(extra='forbid')
    candidateId: str = Field(min_length=1, max_length=100)
    rating: int = Field(ge=1, le=5, strict=True)
    tag: str = Field(pattern=r'^(채택|보류|폐기|후속취재)$')
    comment: str = Field(default='', max_length=1000)


@app.post('/api/evaluations')
def evaluate(value: EvaluationInput):
    if value.candidateId not in {c['id'] for c in bootstrap()['candidates']}:
        raise HTTPException(404, '오늘의 후보에 없는 자료입니다.')
    updated_at = datetime.now(timezone.utc).isoformat()
    with database() as connection:
        connection.execute('INSERT INTO evaluations(candidate_id,rating,tag,comment,updated_at) VALUES(?,?,?,?,?) ON CONFLICT(candidate_id) DO UPDATE SET rating=excluded.rating, tag=excluded.tag, comment=excluded.comment, updated_at=excluded.updated_at', (value.candidateId, value.rating, value.tag, value.comment, updated_at))
    return {'evaluation':{'candidateId':value.candidateId,'rating':value.rating,'tag':value.tag,'comment':value.comment,'updatedAt':updated_at}, 'learningApplied':False, 'notice':'평가를 저장했습니다. 다음 날 가중치 학습은 3단계 예정입니다.'}


@app.post('/api/publish')
@app.post('/api/approve')
@app.post('/api/collect')
@app.post('/api/ai/draft')
def unavailable():
    raise HTTPException(409, '1단계 샘플 모드에서는 실제 수집·AI 작성·승인·외부 송고를 실행하지 않습니다.')


@app.get('/')
def index(): return FileResponse(ROOT / 'web' / 'index.html', headers={'Cache-Control':'no-cache'})


app.mount('/', StaticFiles(directory=ROOT / 'web'), name='web')
