import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
from pathlib import Path
import tempfile
import subprocess
import sys
import time
import threading
import unittest
from unittest.mock import patch

from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app import mail_service as service


class MailServiceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.folder = Path(self.temp.name) / 'mail'
        self.environment = patch.dict(os.environ, {'CONTENT_MAKER_MAIL_DIR':str(self.folder), 'CONTENT_MAKER_ENCRYPTION_KEY':'', 'CONTENT_MAKER_TRUSTED_HOSTS':'','CONTENT_MAKER_TRUSTED_HTTP_PEERS':''})
        self.environment.start()
        self.username = 'editor@example.test'
        self.app_password = 'SECRET-DAUM-APP-PASSWORD'
        self.admin_password = 'separate-admin-password-123'
        service.configure_account(self.username,self.app_password,self.admin_password,['보도자료','제보'])
        app = FastAPI()
        app.include_router(service.router)
        self.client = TestClient(app,base_url='http://127.0.0.1',client=('127.0.0.1',50000))
        self.origin = {'Origin':'http://127.0.0.1'}

    def tearDown(self):
        self.client.close()
        with service._state_lock:
            service._sessions.clear()
            service._attempts.clear()
        self.environment.stop()
        self.temp.cleanup()

    def login(self):
        result = self.client.post('/api/mail/login',json={'password':self.admin_password},headers=self.origin)
        self.assertEqual(result.status_code,200,result.text)
        return result

    def probe_result(self,ok=True):
        return {'ok':ok,'status':'connected' if ok else 'authentication_failed','checkedAt':datetime.now(timezone.utc).isoformat(),'provider':'daum','folders':[{'name':'보도자료','readOnly':True,'exists':True,'uidValidity':'42','messageCount':3}], 'capabilities':{'idleAdvertised':True,'idleTested':False},'errorCode':None if ok else 'AUTHENTICATION_FAILED','userMessage':'접속 시험에 성공했습니다.' if ok else '앱 비밀번호를 확인하세요.'}

    def test_vault_encrypted_password_hashed_and_private_files(self):
        raw=(self.folder/'vault.enc').read_bytes()
        self.assertNotIn(self.app_password.encode(),raw)
        self.assertNotIn(self.admin_password.encode(),raw)
        self.assertNotIn(self.username.encode(),raw)
        state=service.load_configuration()
        self.assertEqual(state['appPassword'],self.app_password)
        self.assertNotIn(self.admin_password,json.dumps(state))
        self.assertEqual((self.folder.stat().st_mode&0o777),0o700)
        for name in ['key','vault.enc']:self.assertEqual(((self.folder/name).stat().st_mode&0o777),0o600)

    def test_external_encryption_key_has_no_local_fallback_key(self):
        other=Path(self.temp.name)/'external'
        with patch.dict(os.environ,{'CONTENT_MAKER_MAIL_DIR':str(other),'CONTENT_MAKER_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            service.configure_account(self.username,self.app_password,self.admin_password,['INBOX'])
            self.assertFalse((other/'key').exists())
            self.assertTrue(service.load_configuration())
        with patch.dict(os.environ,{'CONTENT_MAKER_MAIL_DIR':str(other),'CONTENT_MAKER_ENCRYPTION_KEY':Fernet.generate_key().decode()}):
            with self.assertRaises(service.MailConfigurationError):service.load_configuration()

    def test_authentication_cookie_and_masked_status(self):
        self.assertEqual(self.client.get('/api/mail/status').status_code,401)
        login=self.login()
        cookie=login.headers['set-cookie'].lower()
        self.assertIn('httponly',cookie)
        self.assertIn('samesite=strict',cookie)
        self.assertIn('path=/api/mail',cookie)
        result=self.client.get('/api/mail/status')
        self.assertEqual(result.status_code,200)
        self.assertFalse(result.json()['connected'])
        self.assertEqual(result.json()['usernameMasked'],'e***@example.test')
        for secret in [self.username,self.app_password,self.admin_password]:self.assertNotIn(secret,result.text)
        self.assertEqual(self.client.post('/api/mail/logout',headers=self.origin).status_code,200)
        self.assertEqual(self.client.get('/api/mail/status').status_code,401)

    def test_same_origin_transport_and_dns_rebinding_checks(self):
        result=self.client.post('/api/mail/login',json={'password':self.admin_password})
        self.assertEqual(result.status_code,403)
        result=self.client.post('/api/mail/login',json={'password':self.admin_password},headers={'Origin':'https://evil.example'})
        self.assertEqual(result.status_code,403)
        result=self.client.post('/api/mail/login',json={'password':self.admin_password},headers={**self.origin,'sec-fetch-site':'cross-site'})
        self.assertEqual(result.status_code,403)
        result=self.client.get('/api/mail/status',headers={'Host':'evil.example'})
        self.assertEqual(result.status_code,403)
        app=FastAPI();app.include_router(service.router)
        with TestClient(app,base_url='http://127.0.0.1',client=('203.0.113.1',50000)) as remote:
            self.assertEqual(remote.get('/api/mail/status').status_code,403)

    def test_docker_gateway_requires_explicit_http_peer_and_loopback_host(self):
        app=FastAPI();app.include_router(service.router)
        with TestClient(app,base_url='http://127.0.0.1',client=('172.17.0.1',50000)) as client:
            login=lambda: client.post('/api/mail/login',json={'password':self.admin_password},headers={'Origin':'http://127.0.0.1'})
            self.assertEqual(login().status_code,403)
            with patch.dict(os.environ,{'CONTENT_MAKER_TRUSTED_HTTP_PEERS':'172.17.0.1/32'}):
                self.assertEqual(login().status_code,200)
                self.assertEqual(client.get('/api/mail/status').status_code,200)
                with patch.dict(os.environ,{'CONTENT_MAKER_TRUSTED_HOSTS':'editor.example.test'}):
                    self.assertEqual(client.get('/api/mail/status',headers={'Host':'editor.example.test'}).status_code,403)
            with patch.dict(os.environ,{'CONTENT_MAKER_TRUSTED_HTTP_PEERS':'invalid,172.18.0.0/24'}):
                self.assertEqual(login().status_code,403)
        with TestClient(app,base_url='http://127.0.0.1',client=('203.0.113.1',50000)) as remote:
            with patch.dict(os.environ,{'CONTENT_MAKER_TRUSTED_HTTP_PEERS':'172.17.0.1/32'}):
                result=remote.post('/api/mail/login',json={'password':self.admin_password},headers={'Origin':'http://127.0.0.1','X-Forwarded-For':'172.17.0.1'})
                self.assertEqual(result.status_code,403)

    def test_failed_login_rate_limit_and_no_password_echo(self):
        secret='NEVER-ECHO-THIS'
        for _ in range(5):
            r=self.client.post('/api/mail/login',json={'password':secret},headers=self.origin)
            self.assertEqual(r.status_code,401)
            self.assertNotIn(secret,r.text)
        self.assertEqual(self.client.post('/api/mail/login',json={'password':self.admin_password},headers=self.origin).status_code,429)

    def test_bad_login_payload_never_echoes_input(self):
        secret='DO-NOT-ECHO'
        for payload in [{'password':[secret]},{'password':secret,'extra':secret}]:
            r=self.client.post('/api/mail/login',json=payload,headers=self.origin)
            self.assertEqual(r.status_code,422)
            self.assertNotIn(secret,r.text)
        self.assertEqual(self.client.post('/api/mail/login',content='password=secret',headers={**self.origin,'Content-Type':'application/x-www-form-urlencoded'}).status_code,415)
        r=self.client.post('/api/mail/login',content=b'X'*5000,headers={**self.origin,'Content-Type':'application/json'})
        self.assertEqual(r.status_code,413)

    def test_probe_success_failure_and_no_credential_response(self):
        self.login()
        with patch('app.mail_connector.probe_connection',return_value=self.probe_result()) as probe:
            r=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertEqual(r.status_code,200,r.text)
            self.assertTrue(r.json()['connected'])
            self.assertTrue(r.json()['lastTest']['folders'][0]['readOnly'])
            probe.assert_called_once_with('daum',self.username,self.app_password,['보도자료','제보'],timeout=10)
            for secret in [self.username,self.app_password,self.admin_password]:self.assertNotIn(secret,r.text)
        with patch('app.mail_connector.probe_connection',return_value=self.probe_result(False)):
            r=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertFalse(r.json()['connected'])
            self.assertEqual(r.json()['lastTest']['status'],'authentication_failed')

    def test_exception_details_never_leak_and_old_success_cleared(self):
        self.login()
        with patch('app.mail_connector.probe_connection',side_effect=RuntimeError(self.app_password+' '+self.username)):
            r=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertEqual(r.status_code,200)
            self.assertFalse(r.json()['connected'])
            self.assertNotIn(self.app_password,r.text)
            self.assertNotIn(self.username,r.text)

    def test_result_freshness_expiry_and_configuration_change(self):
        self.login()
        state=service.load_configuration()
        result=self.probe_result()
        result['configurationRevision']=state['revision']
        result['checkedAt']=(datetime.now(timezone.utc)-timedelta(minutes=11)).isoformat()
        state['lastTest']=result
        service._save_configuration(state)
        self.assertFalse(self.client.get('/api/mail/status').json()['connected'])
        result['checkedAt']=(datetime.now(timezone.utc)+timedelta(days=1)).isoformat()
        service._save_configuration(state)
        self.assertFalse(self.client.get('/api/mail/status').json()['connected'])
        service.configure_account(self.username,self.app_password,self.admin_password,['INBOX'])
        self.assertEqual(self.client.get('/api/mail/status').status_code,401)
        self.login()
        self.assertIsNone(self.client.get('/api/mail/status').json()['lastTest'])

    def test_session_expiry_requires_login(self):
        self.login()
        with service._state_lock:
            for session in service._sessions.values():session['expires']=0
        self.assertEqual(self.client.get('/api/mail/status').status_code,401)

    def test_probe_rejects_supplied_credentials_and_targets_before_network(self):
        self.login()
        with patch('app.mail_connector.probe_connection') as probe:
            for payload in [{'password':'DO-NOT-ECHO'},{'host':'evil.example.test'},[]]:
                result=self.client.post('/api/mail/test',json=payload,headers=self.origin)
                self.assertEqual(result.status_code,422)
                self.assertNotIn('DO-NOT-ECHO',result.text)
            self.assertEqual(self.client.post('/api/mail/test',content=b'X'*1200,headers={**self.origin,'Content-Type':'application/json'}).status_code,413)
            self.assertEqual(self.client.post('/api/mail/test',content='{}',headers=self.origin).status_code,415)
            probe.assert_not_called()

    def test_concurrent_probe_is_rejected(self):
        self.login()
        self.assertTrue(service._probe_lock.acquire(blocking=False))
        try:
            r=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertEqual(r.status_code,409)
        finally:service._probe_lock.release()

    def test_account_edit_while_probe_inflight_discards_result(self):
        self.login()
        def changed(*args,**kwargs):
            service.configure_account(self.username,self.app_password,self.admin_password,['INBOX'])
            return self.probe_result()
        with patch('app.mail_connector.probe_connection',side_effect=changed):
            result=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertEqual(result.status_code,409)
            self.assertIsNone(service.load_configuration()['lastTest'])


    def test_provider_file_change_invalidates_success_and_malformed_yaml_is_safe(self):
        from app import mail_connector
        config=Path(self.temp.name)/'mail.yaml'
        config.write_text(mail_connector.DEFAULT_CONFIG.read_text())
        with patch('app.mail_connector.DEFAULT_CONFIG',config):
            self.login()
            with patch('app.mail_connector.probe_connection',return_value=self.probe_result()):
                result=self.client.post('/api/mail/test',json={},headers=self.origin)
                self.assertTrue(result.json()['connected'])
            config.write_text(config.read_text()+'\n# reviewed configuration changed\n')
            result=self.client.get('/api/mail/status')
            self.assertFalse(result.json()['connected'])
            self.assertEqual(result.json()['status'],'test_required')
            config.write_text('providers: [bad yaml')
            result=self.client.get('/api/mail/status')
            self.assertFalse(result.json()['connected'])
            self.assertEqual(result.json()['status'],'configuration_error')
            result=self.client.post('/api/mail/test',json={},headers=self.origin)
            self.assertEqual(result.status_code,503)
            self.assertNotIn('bad yaml',result.text)

    def test_cli_loads_same_dotenv_external_key_as_server(self):
        from app import mail_setup
        envroot=Path(self.temp.name)/'envroot'
        envroot.mkdir()
        key=Fernet.generate_key().decode()
        (envroot/'.env').write_text('CONTENT_MAKER_ENCRYPTION_KEY='+key+'\n')
        accountdir=Path(self.temp.name)/'dotenv-account'
        with patch.dict(os.environ,{'CONTENT_MAKER_MAIL_DIR':str(accountdir)}):
            os.environ.pop('CONTENT_MAKER_ENCRYPTION_KEY',None)
            with patch.object(mail_setup,'ROOT',envroot), patch.object(mail_setup.sys.stdin,'isatty',return_value=True), patch('builtins.input',side_effect=[self.username,'INBOX']), patch.object(mail_setup,'getpass',side_effect=[self.app_password,self.admin_password,self.admin_password]), patch('builtins.print'):
                self.assertEqual(mail_setup.main(),0)
            self.assertEqual(os.environ['CONTENT_MAKER_ENCRYPTION_KEY'],key)
            self.assertFalse((accountdir/'key').exists())
            self.assertEqual(service.load_configuration()['username'],self.username)

    def test_trusted_https_host_uses_secure_cookie(self):
        app=FastAPI();app.include_router(service.router)
        with patch.dict(os.environ,{'CONTENT_MAKER_TRUSTED_HOSTS':'editor.example.test'}):
            with TestClient(app,base_url='https://editor.example.test',client=('203.0.113.1',50000)) as client:
                result=client.post('/api/mail/login',json={'password':self.admin_password},headers={'Origin':'https://editor.example.test'})
                self.assertEqual(result.status_code,200)
                self.assertIn('Secure',result.headers['set-cookie'])
                self.assertEqual(client.get('/api/mail/status').status_code,200)
                self.assertEqual(client.get('/api/mail/status',headers={'Host':'untrusted.example.test'}).status_code,403)

    def test_cli_configuration_serializes_with_server_file_transaction(self):
        started=Path(self.temp.name)/'started'
        finished=Path(self.temp.name)/'finished'
        command = "from pathlib import Path;from app.mail_service import configure_account;Path(%r).touch();configure_account('new-editor@example.test','new-app-password','new-admin-password-123',['INBOX']);Path(%r).touch()" % (str(started),str(finished))
        child=None
        try:
            with service._vault_file_lock():
                child=subprocess.Popen([sys.executable,'-c',command],cwd=service.ROOT,env=os.environ.copy(),stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL)
                until=time.monotonic()+5
                while not started.exists() and time.monotonic()<until:time.sleep(.01)
                self.assertTrue(started.exists())
                time.sleep(.1)
                self.assertFalse(finished.exists())
                self.assertEqual(service.load_configuration()['username'],self.username)
            self.assertEqual(child.wait(timeout=5),0)
            self.assertTrue(finished.exists())
            self.assertEqual(service.load_configuration()['username'],'new-editor@example.test')
        finally:
            if child and child.poll() is None:child.kill();child.wait()

    def test_tampered_encrypted_state_is_not_treated_connected(self):
        self.login()
        (self.folder/'vault.enc').write_bytes(b'not valid ciphertext')
        result=self.client.get('/api/mail/status')
        self.assertEqual(result.status_code,503)
        self.assertNotIn('Traceback',result.text)


if __name__=='__main__': unittest.main()
