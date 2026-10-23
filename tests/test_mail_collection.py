from email.message import EmailMessage
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import mail_collection as collect, mail_service as mail


def message(subject='영화 개봉 안내', body='영화는 10월 25일 개봉한다.\n\n배급사가 자료를 제공했다.'):
    msg=EmailMessage();msg['Subject']=subject;msg['From']='홍보팀 <press@example.test>';msg['Date']='Fri, 23 Oct 2026 09:00:00 +0900';msg['Message-ID']='<news@example.test>';msg.set_content(body);return msg.as_bytes()


class FakeIMAP:
    def __init__(self,host,port,**kwargs):
        self.calls=[];self.mails={uid:message() for uid in range(1,41)};self.validity='17';self.debug=0;self.fail_uid=None
        self.context=kwargs['ssl_context']; self.host=host;self.port=port
    def login(self,*args): self.calls.append(('login',));return 'OK',[]
    def select(self,folder,readonly=False): self.calls.append(('select',folder,readonly));return 'OK',[b'40']
    def status(self,*args): return 'OK',[f'INBOX (UIDVALIDITY {self.validity})'.encode()]
    def uid(self,command,*args):
        self.calls.append((command,*args))
        if command=='SEARCH':return 'OK',[b' '.join(str(x).encode() for x in self.mails)]
        uid=int(args[0]);raw=self.mails[uid]
        if uid==self.fail_uid:return 'NO',[]
        if args[1]=='(RFC822.SIZE INTERNALDATE)':return 'OK',[f'1 (RFC822.SIZE {len(raw)})'.encode()]
        if 'HEADER.FIELDS' in args[1]:
            from email.parser import BytesParser
            from email import policy
            header=EmailMessage();header['Subject']=str(BytesParser(policy=policy.default).parsebytes(raw,headersonly=True).get('Subject',''))
            raw=header.as_bytes()
        return 'OK',[(b'BODY[]',raw),b')']
    def logout(self):self.calls.append(('logout',));return 'BYE',[]


class CollectionTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory()
        self.env=patch.dict(os.environ,{'CONTENT_MAKER_MAIL_DIR':self.temp.name,'CONTENT_MAKER_ENCRYPTION_KEY':'','CONTENT_MAKER_ENCRYPTION_SECRET':''});self.env.start()
        mail.configure_account('user','APP-SECRET','administrator-password',['INBOX']);self.config=mail.load_configuration()
        self.fake=FakeIMAP('imap.daum.net',993,ssl_context=__import__('ssl').create_default_context())
    def tearDown(self): self.env.stop();self.temp.cleanup();mail._sessions.clear();mail._attempts.clear()
    def run_collect(self,archive=None): return collect.collect_messages(self.config,archive or collect.load_archive(self.config),client_factory=lambda *a,**k:self.fake)
    def test_readonly_body_peek_latest_then_backlog_and_new(self):
        state=self.run_collect();self.assertEqual(len(state['sources']),20)
        self.assertEqual(state['folders']['INBOX']['lowUid'],21)
        self.fake.mails[41]=message('공연 신작')
        state=self.run_collect(state)
        self.assertEqual(len(state['sources']),40)
        self.assertEqual(state['folders']['INBOX']['lowUid'],2)
        state=self.run_collect(state);self.assertEqual(len(state['sources']),41)
        self.assertTrue(all(c[2] for c in self.fake.calls if c[0]=='select'))
        fetch=[c for c in self.fake.calls if c[0]=='FETCH']
        self.assertTrue(all(c[2] in ('(RFC822.SIZE INTERNALDATE)','(BODY.PEEK[]<0.1048577>)','(BODY.PEEK[HEADER.FIELDS (SUBJECT)]<0.65537>)') for c in fetch))
        self.assertFalse(any(c[0] in ('STORE','EXPUNGE','MOVE') for c in self.fake.calls))
    def test_failure_does_not_mutate_cursors_or_archive(self):
        state=self.run_collect();before=json.dumps(state,sort_keys=True)
        self.fake.fail_uid=20
        with self.assertRaises(collect.CollectionError): self.run_collect(state)
        self.assertEqual(json.dumps(state,sort_keys=True),before)
    def test_uidvalidity_reset_removes_old_identifiers(self):
        state=self.run_collect();old={s['id'] for s in state['sources']}
        self.fake.validity='18';state=self.run_collect(state)
        self.assertEqual(len(state['sources']),20)
        self.assertFalse(old & {s['id'] for s in state['sources']})
    def test_size_limit_does_not_fetch_large_body(self):
        self.fake.mails={1:b'x'*(collect.MAX_MAIL+1)};state=self.run_collect()
        self.assertEqual(state['lastCollection']['manualReview'],1)
        self.assertFalse(any(c[0]=='FETCH' and c[2]=='(BODY.PEEK[]<0.1048577>)' for c in self.fake.calls))
        self.assertEqual(state['sources'],[])
        self.assertEqual(state['folders']['INBOX']['highUid'],1)
    def test_archive_encrypted_scoped_and_raw_omitted(self):
        state=self.run_collect();collect.save_archive(self.config,state)
        encrypted=collect.archive_path(self.config).read_bytes()
        self.assertNotIn('영화'.encode(),encrypted);self.assertNotIn(b'press@example.test',encrypted)
        self.assertEqual(collect.load_archive(self.config)['sources'][0]['body'],state['sources'][0]['body'])
        self.assertNotIn('rawMime',collect.safe_sources(state)[0])
        other={**self.config,'username':'another'};self.assertEqual(collect.load_archive(other)['sources'],[])
    def test_html_is_plain_text_and_embargo_held(self):
        msg=EmailMessage();msg['Subject']='엠바고';msg.set_content('<script>steal()</script><p>공연 발표</p>',subtype='html')
        source=collect.decode_message(msg.as_bytes(),1,'1','INBOX','scope')
        self.assertNotIn('steal',source['body']);self.assertIn('공연 발표',source['body'])
        self.assertTrue(source['embargoNeedsReview']);self.assertTrue(source['embargoAt'].startswith('9999'))
        self.assertEqual(source['body'],'\n\n'.join(p['text'] for p in source['paragraphs']))
    def test_authenticated_routes_keep_public_sample_separate(self):
        app=FastAPI();app.include_router(mail.router);app.include_router(collect.router)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',5555)) as client:
            self.assertEqual(client.get('/api/mail/workspace').status_code,401)
            headers={'Origin':'http://127.0.0.1'}
            client.post('/api/mail/login',json={'password':'administrator-password'},headers=headers)
            real_collector=collect.collect_messages
            with patch.object(collect,'collect_messages',side_effect=lambda conf,arc:real_collector(conf,arc,client_factory=lambda *a,**k:self.fake)):
                result=client.post('/api/mail/collect',json={},headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            workspace=client.get('/api/mail/workspace');self.assertEqual(workspace.status_code,200,workspace.text)
            self.assertFalse(workspace.json()['sample']);self.assertEqual(workspace.json()['mode'],'real')
            self.assertNotIn('rawMime',workspace.text);self.assertNotIn('APP-SECRET',workspace.text)
            candidate=workspace.json()['candidates'][0]['id']
            result=client.post('/api/mail/evaluations',json={'candidateId':candidate,'rating':4,'tag':'채택','comment':'검토'},headers=headers)
            self.assertEqual(result.status_code,200,result.text)
            self.assertEqual(len(collect.load_archive(self.config)['evaluations']),1)
            self.assertEqual(client.post('/api/mail/collect',json={}).status_code,403)

    def test_parser_failure_rolls_back_without_exposing_raw_message(self):
        state=self.run_collect();before=json.dumps(state,sort_keys=True)
        with patch.object(collect,'decode_message',side_effect=ValueError('SECRET BODY SHOULD NEVER ESCAPE')):
            with self.assertRaises(collect.CollectionError) as error: self.run_collect(state)
        self.assertEqual(str(error.exception),'')
        self.assertEqual(json.dumps(state,sort_keys=True),before)
    def test_internaldate_is_used_instead_of_sender_date(self):
        original=self.fake.uid
        def fetch(command,*args):
            status,data=original(command,*args)
            if command=='FETCH' and args[1]=='(RFC822.SIZE INTERNALDATE)':
                data=[data[0][:-1]+b' INTERNALDATE "22-Oct-2026 12:34:56 +0900")']
            return status,data
        self.fake.uid=fetch
        result=self.run_collect()['sources'][0]
        self.assertEqual(result['receivedAt'],'2026-10-22T03:34:56+00:00')
        self.assertEqual(result['dateSource'],'IMAP INTERNALDATE')
    def test_concurrent_process_collection_cannot_overwrite_newer_archive(self):
        app=FastAPI();app.include_router(mail.router);app.include_router(collect.router)
        with TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',5555)) as client:
            headers={'Origin':'http://127.0.0.1'}
            client.post('/api/mail/login',json={'password':'administrator-password'},headers=headers)
            real=collect.collect_messages
            def concurrent(conf,archive):
                updated=real(conf,archive,client_factory=lambda *a,**k:self.fake)
                newer=__import__('copy').deepcopy(updated);newer['collectionRevision']='other-process'
                collect.save_archive(conf,newer)
                return updated
            with patch.object(collect,'collect_messages',side_effect=concurrent):
                response=client.post('/api/mail/collect',json={},headers=headers)
            self.assertEqual(response.status_code,409,response.text)
            self.assertEqual(collect.load_archive(self.config)['collectionRevision'],'other-process')

    def test_advertisement_headers_skip_body_and_advance_cursor(self):
        self.fake.mails={1:message('(광고) 할인 안내'),2:message('보도자료'),3:message('안내 (광고) 행사')}
        state=self.run_collect()
        self.assertEqual(len(state['sources']),1)
        self.assertEqual(state['sources'][0]['title'],'보도자료')
        self.assertEqual(state['lastCollection']['advertisementsSkipped'],2)
        self.assertEqual(state['folders']['INBOX']['highUid'],3)
        for call in self.fake.calls:
            if call[0]=='FETCH' and call[1] in ('1','3'):
                self.assertIn('HEADER.FIELDS',call[2])
        self.assertEqual(self.run_collect(state)['lastCollection']['imported'],0)

    def test_existing_advertisements_hidden_with_their_evaluations(self):
        state=self.run_collect()
        state['sources'][0]['title']='(광고) 이전 자료'
        excluded=state['sources'][0]['id']
        state['evaluations']=[{'candidateId':'candidate-'+excluded}]
        collect.save_archive(self.config,state)
        loaded=collect.load_archive(self.config)
        self.assertNotIn(excluded,{s['id'] for s in loaded['sources']})
        self.assertEqual(loaded['evaluations'],[])

    def test_approval_and_large_mail_subjects_skip_body(self):
        self.fake.mails={1:message('[전자결재 문서 도착'),2:message('알림 대용량 메일 도착'),3:message('일반 보도자료')}
        state=self.run_collect()
        self.assertEqual([s['title'] for s in state['sources']],['일반 보도자료'])
        self.assertEqual(state['lastCollection']['advertisementsSkipped'],2)
        for call in self.fake.calls:
            if call[0]=='FETCH' and call[1] in ('1','2'):
                self.assertIn('HEADER.FIELDS',call[2])
