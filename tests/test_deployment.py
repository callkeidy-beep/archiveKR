import os,tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from app.deployment import runtime_config,DeploymentConfigurationError

class DeploymentTests(unittest.TestCase):
    def test_local_defaults_and_explicit_port(self):
        with patch.dict(os.environ,{},clear=True):
            self.assertEqual(runtime_config()['host'],'127.0.0.1');self.assertEqual(runtime_config()['port'],3100)
        with patch.dict(os.environ,{'CONTENT_MAKER_PORT':'3200'},clear=True):self.assertEqual(runtime_config()['port'],3200)
    def hosted(self,folder):
        return {'RENDER':'true','RENDER_EXTERNAL_HOSTNAME':'editor-sample.onrender.com','PORT':'10000','CONTENT_MAKER_PORT':'3100','CONTENT_MAKER_MAIL_DIR':folder,'CONTENT_MAKER_SETUP_TOKEN':'s'*48,'CONTENT_MAKER_ENCRYPTION_SECRET':'k'*48,'FORWARDED_ALLOW_IPS':'*','CONTENT_MAKER_PROXY_ISOLATED':'true'}
    def test_hosted_dynamic_port_trusted_domain_and_proxy(self):
        with tempfile.TemporaryDirectory() as folder,patch.dict(os.environ,self.hosted(folder),clear=True):
            c=runtime_config();self.assertEqual(c['port'],10000);self.assertEqual(c['host'],'0.0.0.0');self.assertIn('editor-sample.onrender.com',os.environ['CONTENT_MAKER_TRUSTED_HOSTS']);self.assertEqual(c['forwarded_allow_ips'],'*')
    def test_fail_closed_if_hosted_secrets_domain_or_proxy_invalid(self):
        with tempfile.TemporaryDirectory() as folder:
            for key,value in [('CONTENT_MAKER_ENCRYPTION_SECRET','short'),('CONTENT_MAKER_SETUP_TOKEN',''),('RENDER_EXTERNAL_HOSTNAME','evil.invalid/path'),('CONTENT_MAKER_PROXY_ISOLATED','')]:
                settings=self.hosted(folder);settings[key]=value
                with self.subTest(key=key),patch.dict(os.environ,settings,clear=True):
                    with self.assertRaises(DeploymentConfigurationError) as e:runtime_config()
                    self.assertNotIn('s'*48,str(e.exception));self.assertNotIn('k'*48,str(e.exception))
    def test_existing_vault_does_not_require_setup_token_again(self):
        with tempfile.TemporaryDirectory() as folder:
            Path(folder,'vault.enc').write_bytes(b'encrypted-state-presence-only')
            settings=self.hosted(folder);settings.pop('CONTENT_MAKER_SETUP_TOKEN')
            with patch.dict(os.environ,settings,clear=True):self.assertEqual(runtime_config()['port'],10000)
    def test_wildcard_proxy_not_allowed_on_generic_server(self):
        with patch.dict(os.environ,{'FORWARDED_ALLOW_IPS':'*'},clear=True):
            with self.assertRaises(DeploymentConfigurationError):runtime_config()
    def test_invalid_port_rejected(self):
        for value in ['0','65536','not-a-port']:
            with patch.dict(os.environ,{'CONTENT_MAKER_PORT':value},clear=True):
                with self.assertRaises(DeploymentConfigurationError):runtime_config()

if __name__=='__main__':unittest.main()
