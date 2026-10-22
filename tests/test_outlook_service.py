import os
import tempfile
import unittest
from unittest.mock import patch, AsyncMock
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app import mail_service as mail, outlook_service as outlook


class OutlookTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CONTENT_MAKER_MAIL_DIR':self.temp.name,'CONTENT_MAKER_ENCRYPTION_KEY':'','CONTENT_MAKER_ENCRYPTION_SECRET':'','CONTENT_MAKER_TRUSTED_HOSTS':'engine.test','CONTENT_MAKER_MICROSOFT_CLIENT_ID':'test-client','CONTENT_MAKER_MICROSOFT_CLIENT_SECRET':'secret-test','CONTENT_MAKER_MICROSOFT_REDIRECT_URI':'https://engine.test/api/mail/outlook/callback'})
        self.env.start()
        mail.configure_account('editor@example.test','app-test','admin-password-test',['INBOX'])
        app = FastAPI(); app.include_router(mail.router); app.include_router(outlook.router)
        self.client = TestClient(app,base_url='https://engine.test')
        self.headers = {'Origin':'https://engine.test'}
        self.client.post('/api/mail/login',json={'password':'admin-password-test'},headers=self.headers)
    def tearDown(self):
        self.client.close(); self.env.stop(); self.temp.cleanup(); outlook._pending.clear(); mail._sessions.clear()
    def test_requires_administrator_and_origin(self):
        self.assertEqual(self.client.post('/api/mail/outlook/start',json={}).status_code,403)
        self.client.cookies.clear()
        self.assertEqual(self.client.get('/api/mail/outlook/status').status_code,401)
    def test_pkce_state_and_callback_replay(self):
        from urllib.parse import urlsplit,parse_qs
        response=self.client.post('/api/mail/outlook/start',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        query=parse_qs(urlsplit(response.json()['authorizationUrl']).query)
        self.assertEqual(query['code_challenge_method'],['S256'])
        state=query['state'][0]
        with patch.object(outlook,'token_request',AsyncMock(return_value={'access_token':'ACCESS-TEST','refresh_token':'REFRESH-TEST'})),patch.object(outlook,'graph_get',AsyncMock(return_value={'id':'me','mail':'person@example.test'})):
            response=self.client.get('/api/mail/outlook/callback',params={'state':state,'code':'code'},follow_redirects=False)
        self.assertEqual(response.status_code,303,response.text)
        from pathlib import Path
        self.assertNotIn(b'REFRESH-TEST',Path(self.temp.name+'/vault.enc').read_bytes())
        self.assertEqual(self.client.get('/api/mail/outlook/callback',params={'state':state,'code':'code'}).status_code,403)
        self.assertNotIn('refreshToken',self.client.get('/api/mail/outlook/status').text)
    def test_import_rotates_token_without_marking_read(self):
        config=mail.load_configuration(); outlook.save_field(config,'outlook',{'refreshToken':'old','username':'person@example.test'})
        graph=AsyncMock(return_value={'value':[{'id':'m1','subject':'자료','bodyPreview':'미리보기','from':{'emailAddress':{'address':'press@example.test'}}}]})
        with patch.object(outlook,'token_request',AsyncMock(return_value={'access_token':'access','refresh_token':'new'})),patch.object(outlook,'graph_get',graph):
            response=self.client.post('/api/mail/outlook/import',json={},headers=self.headers)
        self.assertEqual(response.status_code,200,response.text)
        self.assertEqual(response.json()['importedCount'],1)
        self.assertEqual(graph.call_args.args[0],'/me/mailFolders/inbox/messages')
        self.assertEqual(mail.load_configuration()['outlook']['refreshToken'],'new')
        self.assertEqual(self.client.post('/api/mail/outlook/disconnect',json={},headers=self.headers).status_code,200)
        self.assertEqual(mail.load_configuration()['outlookMessages'],[])
    def test_unbound_state_rejected_without_network(self):
        response=self.client.post('/api/mail/outlook/start',json={},headers=self.headers)
        from urllib.parse import urlsplit,parse_qs
        state=parse_qs(urlsplit(response.json()['authorizationUrl']).query)['state'][0]
        self.client.cookies.clear()
        with patch.object(outlook,'token_request',AsyncMock()) as token:
            self.assertEqual(self.client.get('/api/mail/outlook/callback',params={'state':state,'code':'code'}).status_code,403)
            token.assert_not_called()
