"""Delegated Microsoft OAuth + explicit, read-only inbox import. No sending."""
import asyncio
from functools import wraps
import base64
import hashlib
import os
import secrets
import time
from datetime import datetime, timezone
from urllib.parse import urlencode, urlsplit

import httpx
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from app import mail_service as mail

router = APIRouter(prefix='/api/mail/outlook', tags=['outlook'])
AUTH = 'https://login.microsoftonline.com/common/oauth2/v2.0/'
GRAPH = 'https://graph.microsoft.com/v1.0'
SCOPES = 'openid offline_access User.Read Mail.Read'
_pending = {}
_operation_lock = asyncio.Lock()


def serialized(function):
    @wraps(function)
    async def wrapped(*args, **kwargs):
        async with _operation_lock:
            return await function(*args, **kwargs)
    return wrapped

COOKIE = 'content_maker_outlook_oauth'


def settings():
    client = os.environ.get('CONTENT_MAKER_MICROSOFT_CLIENT_ID', '')
    secret = os.environ.get('CONTENT_MAKER_MICROSOFT_CLIENT_SECRET', '')
    redirect = os.environ.get('CONTENT_MAKER_MICROSOFT_REDIRECT_URI', '')
    uri = urlsplit(redirect)
    if not client or not secret or uri.scheme != 'https' or not uri.hostname or uri.username or uri.password or uri.query or uri.fragment or uri.path != '/api/mail/outlook/callback':
        raise HTTPException(503, 'Microsoft 앱 등록과 HTTPS 리디렉션 주소 설정이 필요합니다.')
    return client, secret, redirect


def save_field(configuration, key, value):
    with mail._state_lock, mail._vault_file_lock():
        latest = mail._configuration_or_error()
        if not latest or latest['revision'] != configuration['revision']:
            raise HTTPException(409, '관리자 설정이 바뀌었습니다. 다시 로그인하세요.')
        latest[key] = value
        mail._save_configuration(latest)


def oauth_cookie_response(url):
    response = RedirectResponse(url, status_code=303)
    response.delete_cookie(COOKIE, path='/api/mail/outlook/callback', secure=True, httponly=True, samesite='lax')
    response.headers['Cache-Control'] = 'no-store'
    response.headers['Referrer-Policy'] = 'no-referrer'
    return response


async def token_request(data):
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.post(AUTH + 'token', data=data)
            response.raise_for_status()
            result = response.json()
            if not isinstance(result.get('access_token'), str) or not result['access_token']:
                raise ValueError()
            return result
    except (httpx.HTTPError, ValueError, TypeError):
        raise HTTPException(502, 'Microsoft 인증을 완료하지 못했습니다. 다시 연결하세요.') from None


async def graph_get(path, token, params=None):
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as client:
            response = await client.get(GRAPH + path, headers={'Authorization':'Bearer ' + token}, params=params)
            response.raise_for_status()
            return response.json()
    except (httpx.HTTPError, ValueError):
        raise HTTPException(502, 'Outlook 읽기에 실패했습니다. 권한과 연결 상태를 확인하세요.') from None


@router.get('/status')
def status(request: Request):
    _, config = mail._session(request)
    try:
        settings()
        configured = True
    except HTTPException:
        configured = False
    account = config.get('outlook') or {}
    return {'configured':configured, 'connected':bool(account.get('refreshToken')), 'usernameMasked':mail._masked_username(account.get('username','')), 'lastImportedAt':account.get('lastImportedAt'), 'notice':'인증 저장 상태입니다. 실제 수집은 가져오기를 눌러 확인합니다. 받은편지함 최근 20건을 읽으며 읽음 상태를 변경하지 않습니다. 자동 폴링·후보 추천 연동은 아직 없습니다.'}


@router.post('/start')
@serialized
async def start(request: Request):
    mail._https_secret_guard(request)
    session, config = mail._session(request)
    await mail._strict_secret_json(request, set())
    client, _, redirect = settings()
    if redirect != str(request.base_url).rstrip('/') + '/api/mail/outlook/callback':
        raise HTTPException(503, '현재 서버와 Microsoft 리디렉션 주소가 일치하지 않습니다.')
    state, nonce, verifier = secrets.token_urlsafe(32), secrets.token_urlsafe(32), secrets.token_urlsafe(48)
    with mail._state_lock:
        for key in list(_pending):
            if _pending[key]['expires'] < time.monotonic(): _pending.pop(key)
        if len(_pending) >= 100: raise HTTPException(429, '잠시 뒤 다시 시도하세요.')
        _pending[state] = {'sessionKey':hashlib.sha256(request.cookies.get(mail.COOKIE,'').encode()).hexdigest(),'nonce':nonce,'verifier':verifier,'revision':config['revision'],'expires':min(time.monotonic()+600,session['expires'])}
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
    from fastapi.responses import JSONResponse
    response = JSONResponse({'authorizationUrl':AUTH+'authorize?'+urlencode({'client_id':client,'response_type':'code','redirect_uri':redirect,'response_mode':'query','scope':SCOPES,'state':state,'code_challenge':challenge,'code_challenge_method':'S256','prompt':'select_account'})})
    response.set_cookie(COOKIE,nonce,max_age=600,secure=True,httponly=True,samesite='lax',path='/api/mail/outlook/callback')
    response.headers['Cache-Control']='no-store'
    return response


@router.get('/callback')
@serialized
async def callback(request: Request):
    mail._transport_guard(request)
    if request.url.scheme != 'https': raise HTTPException(403,'HTTPS가 필요합니다.')
    state = request.query_params.get('state','')
    with mail._state_lock: pending = _pending.pop(state, None)
    if not pending or pending['expires'] < time.monotonic() or not secrets.compare_digest(request.cookies.get(COOKIE,''), pending['nonce']):
        raise HTTPException(403, '로그인 요청이 만료됐거나 일치하지 않습니다. 연결을 다시 시작하세요.')
    with mail._state_lock:
        active_session = mail._sessions.get(pending['sessionKey'])
    if not active_session or active_session['expires'] <= time.monotonic():
        raise HTTPException(403,'관리자 로그인이 만료됐습니다. 다시 로그인하세요.')
    config = mail._configuration_or_error()
    if not config or config['revision'] != pending['revision']: raise HTTPException(403,'관리자 설정이 변경됐습니다.')
    if request.query_params.get('error') or not request.query_params.get('code'):
        return oauth_cookie_response('/?outlook=cancelled#settings')
    client, secret, redirect = settings()
    tokens = await token_request({'grant_type':'authorization_code','client_id':client,'client_secret':secret,'code':request.query_params['code'],'redirect_uri':redirect,'code_verifier':pending['verifier'],'scope':SCOPES})
    profile = await graph_get('/me', tokens['access_token'], {'$select':'id,mail,userPrincipalName'})
    if not tokens.get('refresh_token') or not profile.get('id'): raise HTTPException(502,'지속 연결 권한을 확인하세요.')
    save_field(config,'outlook',{'refreshToken':tokens['refresh_token'],'username':profile.get('mail') or profile.get('userPrincipalName',''),'accountId':profile['id'],'lastImportedAt':None})
    save_field(config,'outlookMessages',[])
    return oauth_cookie_response('/?outlook=connected#settings')


@router.post('/import')
@serialized
async def import_inbox(request: Request):
    mail._https_secret_guard(request)
    _, config = mail._session(request)
    await mail._strict_secret_json(request,set())
    account = config.get('outlook') or {}
    if not account.get('refreshToken'): raise HTTPException(409,'Microsoft 로그인을 먼저 완료하세요.')
    client, secret, _ = settings()
    tokens = await token_request({'grant_type':'refresh_token','client_id':client,'client_secret':secret,'refresh_token':account['refreshToken'],'scope':SCOPES})
    # Persist rotated refresh tokens before a subsequent network operation can fail.
    if tokens.get('refresh_token'):
        account = {**account,'refreshToken':tokens['refresh_token']}
        save_field(config,'outlook',account)
    data = await graph_get('/me/mailFolders/inbox/messages',tokens['access_token'],{'$top':'20','$orderby':'receivedDateTime desc','$select':'id,internetMessageId,subject,from,receivedDateTime,bodyPreview'})
    messages = []
    for item in data.get('value',[])[:20]:
        messages.append({'id':str(item['id'])[:512],'messageId':str(item.get('internetMessageId',''))[:256],'subject':item.get('subject','')[:300],'sender':item.get('from',{}).get('emailAddress',{}).get('address','')[:254],'receivedAt':item.get('receivedDateTime'),'preview':item.get('bodyPreview','')[:300]})
    # Separate encrypted preview archive: never mixed with the public sample dataset.
    while len(__import__('json').dumps(messages,ensure_ascii=False).encode()) > 32000:
        messages.pop()
    save_field(config,'outlookMessages',messages)
    save_field(config,'outlook',{**account,'lastImportedAt':datetime.now(timezone.utc).isoformat()})
    return {'importedCount':len(messages),'messages':messages,'notice':'최근 20건의 제목·발신자·본문 미리보기를 암호화 저장했습니다. 전체 본문·첨부·자동 폴링·후보 추천 연동은 아직 없습니다.'}


@router.post('/disconnect')
@serialized
async def disconnect(request: Request):
    mail._https_secret_guard(request)
    _, config = mail._session(request)
    await mail._strict_secret_json(request,set())
    with mail._state_lock: _pending.clear()
    save_field(config,'outlook',None)
    save_field(config,'outlookMessages',[])
    return {'ok':True,'notice':'서버 토큰과 수집 미리보기를 삭제했습니다. Microsoft 계정의 앱 권한 철회는 계정 설정에서 진행하세요.'}
