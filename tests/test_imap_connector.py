import json
from pathlib import Path
import ssl
import tempfile
import unittest
from unittest.mock import patch
import imaplib

from app.mail_connector import decode_folder, encode_folder, probe_connection, quote_mailbox


class FakeSocket:
    def __init__(self): self.timeouts = []
    def settimeout(self, value): self.timeouts.append(value)


class FakeIMAP:
    def __init__(self, host, port, *, ssl_context, timeout):
        self.host, self.port, self.context, self.timeout = host, port, ssl_context, timeout
        self.sock = FakeSocket()
        self.calls = []
        self.debug = 9

    def login(self, username, password):
        self.calls.append(('login', username, password))
        if password == 'bad-password':
            raise imaplib.IMAP4.error('private username and bad-password raw server reply')
        return 'OK', [b'authenticated']

    def capability(self):
        self.calls.append(('capability',))
        return 'OK', [b'IMAP4rev1 UIDPLUS IDLE']

    def list(self, reference, pattern):
        self.calls.append(('list', reference, pattern))
        if pattern == '"missing"': return 'OK', [None]
        return 'OK', [b'(\\HasNoChildren) "/" '+pattern.encode('ascii')]

    def select(self, mailbox, readonly=False):
        self.calls.append(('select', mailbox, readonly))
        if mailbox == '"denied"': return 'NO', [b'raw private response']
        return 'OK', [b'7']

    def status(self, mailbox, names):
        self.calls.append(('status', mailbox, names))
        return 'OK', [mailbox.encode('ascii') + b' (MESSAGES 7 UIDVALIDITY 12345)']

    def logout(self):
        self.calls.append(('logout',))
        return 'BYE', [b'logout']

    def shutdown(self): self.calls.append(('shutdown',))


class ConnectorTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.config = Path(self.directory.name)/'mail.yaml'
        self.config.write_text('providers:\n  daum:\n    host: imap.daum.net\n    port: 993\n    ssl: true\n')
        self.instances = []

    def tearDown(self): self.directory.cleanup()

    def factory(self, *args, **kwargs):
        instance = FakeIMAP(*args, **kwargs)
        self.instances.append(instance)
        return instance

    def probe(self, **kwargs):
        return probe_connection('daum', 'editor@example.test', kwargs.pop('password','valid-app-password'),
                                kwargs.pop('folders',['보도자료','제보']),config_path=self.config,
                                client_factory=kwargs.pop('factory',self.factory), **kwargs)

    def test_modified_utf7_roundtrip_korean_ampersand_quotes_and_unicode(self):
        for folder in ['보도자료','제보','INBOX','A & B','따옴표 "검사"',r'상위\하위','영화 🎬','日本語/메일']:
            encoded = encode_folder(folder)
            self.assertTrue(encoded.isascii())
            self.assertEqual(decode_folder(encoded), folder)
            self.assertEqual(decode_folder(encoded.encode()), folder)
        self.assertEqual(encode_folder('&'), '&-')
        self.assertEqual(quote_mailbox('a"b\\c'), '"a\\"b\\\\c"')

    def test_modified_utf7_rejects_malformed_text(self):
        for text in ['&unterminated','&!invalid-','&AA-','é']:
            with self.assertRaises((ValueError,UnicodeError)): decode_folder(text)

    def test_success_requires_tls_verified_and_all_folders_readonly_without_fetch(self):
        result = self.probe()
        self.assertTrue(result['ok'])
        self.assertEqual(result['status'],'connected')
        self.assertEqual(len(result['folders']),2)
        self.assertEqual(result['folders'][0]['uidValidity'],'12345')
        self.assertEqual(result['folders'][0]['messageCount'],7)
        self.assertTrue(all(f['exists'] and f['readOnly'] for f in result['folders']))
        self.assertEqual(result['capabilities'],{'idleAdvertised':True,'idleTested':False})
        instance = self.instances[0]
        self.assertEqual(instance.host,'imap.daum.net')
        self.assertEqual(instance.port,993)
        self.assertEqual(instance.context.verify_mode,ssl.CERT_REQUIRED)
        self.assertTrue(instance.context.check_hostname)
        self.assertEqual(instance.debug,0)
        self.assertEqual([call[2] for call in instance.calls if call[0]=='select'],[True,True])
        self.assertEqual(instance.calls[-1],('logout',))
        self.assertFalse(any(call[0] in ['fetch','uid','store','close','expunge','append','copy','delete'] for call in instance.calls))
        self.assertNotIn('valid-app-password',json.dumps(result))
        self.assertNotIn('editor@example.test',json.dumps(result))

    def test_korean_folder_is_modified_utf7_and_quoted(self):
        folder = '보도자료 "새 소식" & 영화'
        result = self.probe(folders=[folder])
        self.assertTrue(result['ok'])
        expected = quote_mailbox(encode_folder(folder))
        calls = self.instances[0].calls
        self.assertIn(('list','""',expected),calls)
        self.assertIn(('select',expected,True),calls)
        self.assertIn(('status',expected,'(UIDVALIDITY MESSAGES)'),calls)

    def test_auth_failure_is_sanitized_and_always_logs_out(self):
        result = self.probe(password='bad-password')
        self.assertFalse(result['ok'])
        self.assertEqual(result['status'],'authentication_failed')
        self.assertNotIn('bad-password',json.dumps(result))
        self.assertNotIn('private username',json.dumps(result))
        self.assertEqual(self.instances[0].calls[-1],('logout',))
        self.assertFalse(any(call[0]=='select' for call in self.instances[0].calls))

    def test_any_missing_or_denied_folder_prevents_connected(self):
        for folder in ['missing','denied']:
            result = self.probe(folders=['INBOX',folder])
            self.assertFalse(result['ok'])
            self.assertEqual(result['status'],'folder_error')
            self.assertTrue(result['folders'][0]['readOnly'])
            self.assertEqual(self.instances[-1].calls[-1],('logout',))

    def test_folder_status_must_supply_uidvalidity_and_count(self):
        def factory(*args,**kwargs):
            item=self.factory(*args,**kwargs)
            item.status=lambda *_: ('OK',[b'(MESSAGES 3)'])
            return item
        result=self.probe(factory=factory)
        self.assertFalse(result['ok'])
        self.assertEqual(result['folders'][0]['errorCode'],'FOLDER_STATUS_INCOMPLETE')

    def test_capability_does_not_claim_idle_was_executed(self):
        def factory(*args,**kwargs):
            item=self.factory(*args,**kwargs)
            item.capability=lambda: ('OK',[b'IMAP4rev1'])
            return item
        result=self.probe(factory=factory)
        self.assertTrue(result['ok'])
        self.assertEqual(result['capabilities'],{'idleAdvertised':False,'idleTested':False})

    def test_timeout_tls_and_network_errors_have_no_exception_text(self):
        cases=[(TimeoutError('valid-app-password'),'CONNECTION_TIMEOUT'),
               (ssl.SSLCertVerificationError('valid-app-password'),'TLS_VERIFICATION_FAILED'),
               (OSError('valid-app-password'),'CONNECTION_FAILED')]
        for error,code in cases:
            def factory(*args,**kwargs): raise error
            result=self.probe(factory=factory)
            self.assertFalse(result['ok'])
            self.assertEqual(result['errorCode'],code)
            self.assertNotIn('valid-app-password',json.dumps(result))

    def test_logout_failure_closes_transport(self):
        def factory(*args,**kwargs):
            item=self.factory(*args,**kwargs)
            def logout(): raise OSError('secret')
            item.logout=logout
            return item
        self.assertTrue(self.probe(factory=factory)['ok'])
        self.assertEqual(self.instances[0].calls[-1],('shutdown',))

    def test_disallows_insecure_provider_invalid_folder_and_empty_credentials(self):
        self.config.write_text('providers:\n  daum:\n    host: imap.daum.net\n    port: 993\n    ssl: false\n')
        self.assertEqual(self.probe()['errorCode'],'PROVIDER_CONFIGURATION')
        self.assertEqual(len(self.instances),0)
        for folder in ['foo\r\nSTORE 1 +FLAGS (\\Deleted)','', '\x00']:
            self.assertEqual(self.probe(folders=[folder])['errorCode'],'INVALID_FOLDERS')
        self.assertEqual(self.probe(password='')['errorCode'],'CREDENTIALS_REQUIRED')
        self.assertEqual(len(self.instances),0)

    def test_provider_endpoint_cannot_be_redirected_to_another_host_or_port(self):
        for host, port in [('localhost',993),('imap.daum.net',143),('imap.daum.net.evil.test',993)]:
            self.config.write_text(f'providers:\n  daum:\n    host: {host}\n    port: {port}\n    ssl: true\n')
            self.assertEqual(self.probe()['errorCode'],'PROVIDER_CONFIGURATION')
        self.assertEqual(self.instances,[])

    def test_connection_budget_is_bounded(self):
        result=self.probe(timeout=500)
        self.assertTrue(result['ok'])
        self.assertEqual(self.instances[0].timeout,30)
        self.assertTrue(all(0<value<=30 for value in self.instances[0].sock.timeouts))


if __name__=='__main__': unittest.main()
