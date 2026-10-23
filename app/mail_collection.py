"""Explicit, read-only IMAP collection into an account-scoped encrypted archive."""
from __future__ import annotations
import base64
import copy
from datetime import datetime, timezone
from email import policy
from email.parser import BytesParser
from email.utils import parsedate_to_datetime, parseaddr
import hashlib
from html.parser import HTMLParser
import imaplib
import json
import re
import secrets
import ssl
import threading
import time

from cryptography.fernet import InvalidToken
from fastapi import APIRouter, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from app import mail_service as mail
from app.mail_connector import load_provider, quote_mailbox, encode_folder, _success

router = APIRouter(prefix='/api/mail', tags=['mail collection'])
_collect_lock = threading.Lock()
MAX_MAIL = 1024 * 1024
MAX_ARCHIVE = 32 * 1024 * 1024


class CollectionError(Exception):
    """Contains no provider exception, credentials or mail content."""


class PlainHTML(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True); self.parts=[]; self.suppressed=0
    def handle_starttag(self, tag, attrs):
        if tag in ('script','style','head'): self.suppressed += 1
        elif tag in ('p','div','br','li','tr','h1','h2'): self.parts.append('\n')
    def handle_endtag(self, tag):
        if tag in ('script','style','head') and self.suppressed: self.suppressed -= 1
        elif tag in ('p','div','li'): self.parts.append('\n')
    def handle_data(self, data):
        if not self.suppressed: self.parts.append(data)


def account_scope(config):
    payload = {'username':config['username'].strip().casefold(),'folders':sorted(config['folders']),'server':load_provider('daum')}
    return hashlib.sha256(json.dumps(payload,sort_keys=True,ensure_ascii=False).encode()).hexdigest()


def archive_path(config):
    return mail._private_directory() / ('messages-' + account_scope(config) + '.enc')


EXCLUDED_SUBJECT_MARKERS = ('(광고)', '[전자결재', '대용량 메일')


def is_excluded_subject(subject):
    return any(marker in str(subject) for marker in EXCLUDED_SUBJECT_MARKERS)


def without_excluded_subjects(archive):
    archive['sources'] = [s for s in archive['sources'] if not is_excluded_subject(s.get('title', ''))]
    retained = {'candidate-' + s['id'] for s in archive['sources']}
    archive['evaluations'] = [e for e in archive['evaluations'] if e['candidateId'] in retained]
    return archive


def load_archive(config):
    path=archive_path(config)
    if not path.exists(): return {'version':1,'folders':{},'sources':[],'evaluations':[],'lastCollectedAt':None}
    try:
        if path.is_symlink() or path.stat().st_size > MAX_ARCHIVE*2: raise ValueError()
        result=json.loads(mail._cipher().decrypt(path.read_bytes()))
        if result.get('version') != 1: raise ValueError()
        return without_excluded_subjects(result)
    except (OSError,ValueError,InvalidToken):
        raise CollectionError() from None


def save_archive(config, archive):
    payload=json.dumps(archive,ensure_ascii=False,separators=(',',':')).encode()
    if len(payload)>MAX_ARCHIVE: raise CollectionError()
    mail._write_private(archive_path(config),mail._cipher().encrypt(payload))


def decode_message(raw, uid, validity, folder, scope):
    message=BytesParser(policy=policy.default).parsebytes(raw)
    title=str(message.get('Subject','제목 없음'))[:1000]
    sender_name,sender_address=parseaddr(str(message.get('From','')))
    now=datetime.now(timezone.utc)
    try:
        received=parsedate_to_datetime(str(message.get('Date','')))
        if received.tzinfo is None: received=received.replace(tzinfo=timezone.utc)
        if received > now: received=now
    except (ValueError,TypeError,OverflowError): received=now
    plain=[]; html=[]; attachments=[]; photos=[]
    for part in message.walk():
        if part.is_multipart(): continue
        filename=part.get_filename()
        kind=part.get_content_type()
        if filename or part.get_content_disposition()=='attachment' or kind.startswith('image/'):
            entry={'id':'attachment-'+str(len(attachments)+1),'name':str(filename or '이름 없는 첨부')[:300],'contentType':kind,'status':'manual_review','notice':'첨부 원문 추출과 사용 권한 확인이 필요합니다.'}
            attachments.append(entry)
            if kind.startswith('image/'):
                photos.append({**entry,'source':'미확인','caption':'','usage':'사용 보류'})
            continue
        if kind in ('text/plain','text/html'):
            try: text=part.get_content()
            except (LookupError,UnicodeError): text=(part.get_payload(decode=True) or b'').decode('utf-8',errors='replace')
            if isinstance(text,str): (plain if kind=='text/plain' else html).append(text)
    body='\n'.join(plain)
    if not body and html:
        parser=PlainHTML();parser.feed('\n'.join(html));body=''.join(parser.parts)
    body=body.replace('\x00','').strip()[:100000]
    body_missing=not bool(body)
    if not body: body='[본문 텍스트 추출 실패: 첨부 또는 원본 메일을 수동 확인하세요.]'
    paragraphs=[{'id':f'p{i+1}','text':text} for i,text in enumerate(re.split(r'\n\s*\n|\n',body)) if text.strip()]
    # Body and paragraph character positions must refer to the same extracted text.
    body='\n\n'.join(p['text'] for p in paragraphs)
    source_id='daum-'+hashlib.sha256(f'{scope}:{folder}:{validity}:{uid}'.encode()).hexdigest()[:24]
    from app.domain import classification
    category,classification_info=classification(title,body)
    embargo=bool(re.search(r'엠바고|embargo',title+'\n'+body,re.I))
    return {'id':source_id,'title':title,'subject':title,'body':body,'paragraphs':paragraphs,'sender':{'organization':sender_name or sender_address or '발신처 미확인','email':sender_address},'messageId':str(message.get('Message-ID',''))[:1000],'receivedAt':received.isoformat(),'accountId':'daum-real','provider':'daum','folder':folder,'uid':str(uid),'uidValidity':str(validity),'attachments':attachments,'photos':photos,'category':category,'classification':classification_info,'embargoAt':'9999-01-01T00:00:00+00:00' if embargo else None,'embargoNeedsReview':embargo,'restricted':bool(category in ('재난','사고','범죄','선거') or re.search(r'재난|사망|범죄|선거',title)),'collectionStatus':'manual_review' if body_missing else 'collected','isSample':False,'rawMime':base64.b64encode(raw).decode(),'contentHash':hashlib.sha256((title+'\n'+body).encode()).hexdigest(),'version':1}


def collect_messages(config, archive, *, client_factory=None, timeout=60):
    """First batch newest20/folder; next batches up to10 new + older to20.

    Every command uses UID and read-only selection/BODY.PEEK. A failure aborts
    this transaction, so no cursor advances past a failed message. Oversized
    messages become explicit manual-review records rather than fetched bodies.
    """
    archive=without_excluded_subjects(copy.deepcopy(archive)); scope=account_scope(config); client=None
    imported=0; oversized=0; advertisements=0; deadline=time.monotonic()+timeout
    def budget():
        remaining=deadline-time.monotonic()
        if remaining<=0: raise CollectionError()
        sock=getattr(client,'sock',None)
        if sock: sock.settimeout(min(10,remaining))
    try:
        settings=load_provider('daum')
        client=(client_factory or imaplib.IMAP4_SSL)(settings['host'],settings['port'],ssl_context=ssl.create_default_context(),timeout=10)
        client.debug=0
        budget(); status,_=client.login(config['username'],config['appPassword'])
        if not _success(status): raise CollectionError()
        for folder in config['folders']:
            quoted=quote_mailbox(encode_folder(folder))
            budget();status,_=client.select(quoted,readonly=True)
            if not _success(status): raise CollectionError()
            budget();status,data=client.status(quoted,'(UIDVALIDITY)')
            match=re.search(rb'UIDVALIDITY\s+(\d+)',b' '.join(x for x in data or [] if isinstance(x,bytes)),re.I)
            if not _success(status) or not match: raise CollectionError()
            validity=match.group(1).decode()
            budget();status,data=client.uid('SEARCH',None,'ALL')
            if not _success(status): raise CollectionError()
            if sum(len(row) for row in data or [] if isinstance(row,bytes)) > 8*1024*1024: raise CollectionError()
            uids=sorted({int(x) for row in data or [] if isinstance(row,bytes) for x in row.split()})
            cursor=archive['folders'].get(folder)
            if cursor and cursor['uidValidity'] != validity:
                # Old server identifiers cannot be reused after UIDVALIDITY reset.
                archive['sources']=[s for s in archive['sources'] if s.get('folder')!=folder]
                cursor=None
            if cursor:
                newer=[u for u in uids if u>cursor['highUid']][:10]
                older=[u for u in uids if u<cursor['lowUid']][-max(0,20-len(newer)):]
                batch=newer+list(reversed(older))
            else: batch=list(reversed(uids[-20:]))
            handled=[]
            for uid in batch:
                # Read only the Subject header before fetching any body/attachment.
                budget();status,header_data=client.uid('FETCH',str(uid),'(BODY.PEEK[HEADER.FIELDS (SUBJECT)]<0.65537>)')
                header_chunks=[x[1] for x in header_data or [] if isinstance(x,tuple) and len(x)>1 and isinstance(x[1],bytes)]
                if not _success(status) or not header_chunks or sum(map(len,header_chunks))>65536: raise CollectionError()
                header=BytesParser(policy=policy.default).parsebytes(b''.join(header_chunks),headersonly=True)
                if is_excluded_subject(header.get('Subject','')):
                    advertisements+=1;handled.append(uid);continue
                budget();status,data=client.uid('FETCH',str(uid),'(RFC822.SIZE INTERNALDATE)')
                size_match=re.search(rb'RFC822.SIZE\s+(\d+)',b' '.join(x for x in data or [] if isinstance(x,bytes)),re.I)
                if not _success(status) or not size_match: raise CollectionError()
                size=int(size_match.group(1))
                internal_raw=b' '.join(x for x in data or [] if isinstance(x,bytes))
                internal_tuple=imaplib.Internaldate2tuple(internal_raw)
                if size>MAX_MAIL:
                    # Fetch nothing from oversized messages. Keep explicit marker.
                    raw=b'Subject: [Manual review: message larger than 1 MiB]\r\n\r\n'
                    source=decode_message(raw,uid,validity,folder,scope)
                    source['title']=source['subject']='대용량 메일: 원본에서 수동 확인 필요'
                    source['attachments']=[{'name':'대용량 메일 원문','status':'manual_review'}]
                    source['body']='1 MiB를 초과하여 본문과 첨부를 가져오지 않았습니다.'
                    source['paragraphs']=[{'id':'p1','text':source['body']}]
                    source['rawMime']=None; source['collectionStatus']='manual_review'; oversized+=1
                else:
                    budget();status,data=client.uid('FETCH',str(uid),'(BODY.PEEK[]<0.1048577>)')
                    chunks=[x[1] for x in data or [] if isinstance(x,tuple) and len(x)>1 and isinstance(x[1],bytes)]
                    if not _success(status) or not chunks or sum(map(len,chunks))>MAX_MAIL: raise CollectionError()
                    source=decode_message(b''.join(chunks),uid,validity,folder,scope)
                if internal_tuple:
                    source['receivedAt']=datetime.fromtimestamp(time.mktime(internal_tuple),timezone.utc).isoformat()
                    source['dateSource']='IMAP INTERNALDATE'
                else:
                    source['dateSource']='메일 Date 헤더 또는 수집 시각 (실제 배달 시각 미확인)'
                if is_excluded_subject(source['title']):
                    advertisements+=1;handled.append(uid);continue
                if source['id'] not in {s['id'] for s in archive['sources']}:
                    archive['sources'].append(source); imported+=1
                handled.append(uid)
            if handled or cursor:
                archive['folders'][folder]={'uidValidity':validity,'highUid':max(handled+[cursor['highUid']] if cursor else handled),'lowUid':min(handled+[cursor['lowUid']] if cursor else handled)}
        archive['sources'].sort(key=lambda s:s['receivedAt'],reverse=True)
        pruned=max(0,len(archive['sources'])-500);archive['sources']=archive['sources'][:500]
        while len(json.dumps(archive,ensure_ascii=False,separators=(',',':')).encode())>MAX_ARCHIVE-4096 and archive['sources']:
            archive['sources'].pop();pruned+=1
        retained={'candidate-'+s['id'] for s in archive['sources']}
        archive['evaluations']=[e for e in archive['evaluations'] if e['candidateId'] in retained]
        archive['collectionRevision']=secrets.token_hex(24)
        archive['lastCollectedAt']=datetime.now(timezone.utc).isoformat()
        archive['lastCollection']={'imported':imported,'manualReview':oversized,'pruned':pruned,'advertisementsSkipped':advertisements}
        return archive
    except Exception:
        raise CollectionError() from None
    finally:
        if client:
            try:
                if getattr(client,'sock',None): client.sock.settimeout(.5)
                client.logout()
            except Exception:
                try: client.shutdown()
                except Exception: pass


def safe_sources(archive):
    return [{k:v for k,v in source.items() if k not in ('rawMime','contentHash')} for source in archive['sources']]


def checked_configuration(config):
    latest=mail._configuration_or_error()
    if not latest or latest['revision']!=config['revision']: raise HTTPException(409,'메일 설정이 변경됐습니다. 다시 로그인하세요.')


@router.post('/collect')
async def collect(request: Request):
    mail._transport_guard(request,mutation=True);_,config=mail._session(request)
    await mail._strict_secret_json(request,set())
    if not config.get('username') or not config.get('appPassword'): raise HTTPException(409,'다음메일 계정을 먼저 설정하세요.')
    if not _collect_lock.acquire(blocking=False): raise HTTPException(409,'다른 수집 작업이 진행 중입니다.')
    try:
        with mail._state_lock,mail._vault_file_lock(): archive=load_archive(config)
        updated=await run_in_threadpool(collect_messages,config,archive)
        with mail._state_lock,mail._vault_file_lock():
            checked_configuration(config)
            # Preserve evaluations submitted while network collection was running.
            current=load_archive(config)
            if current.get('collectionRevision') != archive.get('collectionRevision'):
                raise HTTPException(409,'다른 프로세스에서 수집 자료가 갱신됐습니다. 다시 가져오세요.')
            updated['evaluations']=current['evaluations']
            save_archive(config,updated)
        return {'ok':True,'collected':updated['lastCollection']['imported'],'collectedCount':updated['lastCollection']['imported'],'totalCount':len(updated['sources']),'lastCollectedAt':updated['lastCollectedAt'],'details':updated['lastCollection'],'notice':'읽음 상태를 바꾸지 않고 가져왔습니다. 제목에 (광고), [전자결재, 대용량 메일 문구가 있으면 제외합니다. 처음에는 최신20건, 다음 실행부터 새 메일과 이전 메일을 나눠 가져옵니다. 첨부 추출·자동 폴링·AI·송고는 실행하지 않습니다.'}
    except (CollectionError,mail.MailConfigurationError,OSError):
        raise HTTPException(502,'메일을 가져오거나 암호화 저장하지 못했습니다. 이번 작업의 수집 위치는 변경하지 않았습니다. 계정·폴더·네트워크와 저장 공간을 확인한 뒤 다시 시도하세요.') from None
    finally: _collect_lock.release()


@router.get('/workspace')
def workspace(request: Request):
    _,config=mail._session(request)
    try:
        with mail._state_lock,mail._vault_file_lock(): archive=load_archive(config)
        from app.domain import build_workspace
        result=build_workspace(safe_sources(archive),archive['evaluations'])
        result['lastCollectedAt']=archive['lastCollectedAt'];result['collection']=archive.get('lastCollection')
        return result
    except (CollectionError,mail.MailConfigurationError,OSError):
        raise HTTPException(503,'실제 메일 암호화 자료를 읽지 못했습니다. 저장소와 키를 확인하세요.') from None


@router.post('/evaluations')
async def evaluate(request: Request):
    mail._transport_guard(request,mutation=True);_,config=mail._session(request)
    value=await mail._strict_secret_json(request,{'candidateId','rating','tag','comment'})
    if not isinstance(value['candidateId'],str) or type(value['rating']) is not int or not 1<=value['rating']<=5 or value['tag'] not in ('채택','보류','폐기','후속취재') or not isinstance(value['comment'],str) or len(value['comment'])>2000:
        raise HTTPException(422,'평가 입력값을 확인하세요.')
    try:
        with mail._state_lock,mail._vault_file_lock():
            checked_configuration(config);archive=load_archive(config)
            if value['candidateId'] not in {'candidate-'+s['id'] for s in archive['sources']}: raise HTTPException(404,'수집한 메일 후보가 아닙니다.')
            record={**value,'updatedAt':datetime.now(timezone.utc).isoformat()}
            archive['evaluations']=[e for e in archive['evaluations'] if e['candidateId']!=value['candidateId']]+[record]
            save_archive(config,archive)
        return {'evaluation':record,'learningApplied':False,'notice':'실제 자료 평가를 암호화 저장했습니다. 송고 승인은 아닙니다.'}
    except (CollectionError,mail.MailConfigurationError,OSError):
        raise HTTPException(503,'평가를 안전하게 저장하지 못했습니다.') from None
