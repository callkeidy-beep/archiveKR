"""Offline regressions for API input handling, secret-safe failures and workbook size."""
import io,json,threading,unittest,urllib.request,urllib.error,tempfile
from pathlib import Path
from unittest.mock import patch
from http.server import ThreadingHTTPServer
from PIL import Image
import app_server as app

class ServerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server=ThreadingHTTPServer(('127.0.0.1',0),app.H)
        cls.worker=threading.Thread(target=cls.server.serve_forever,daemon=True);cls.worker.start()
        cls.base=f'http://127.0.0.1:{cls.server.server_port}/api/movist'
    @classmethod
    def tearDownClass(cls):cls.server.shutdown();cls.server.server_close();cls.worker.join()
    def post(self,path,data):
        raw=data if isinstance(data,bytes) else json.dumps(data).encode()
        try:r=urllib.request.urlopen(urllib.request.Request(self.base+path,data=raw,headers={'Content-Type':'application/json'}))
        except urllib.error.HTTPError as e:r=e
        return r.code,r.read()
    def test_card_dimensions(self):
        code,raw=self.post('/cards',{'headline':'영화의 다음 장면'});self.assertEqual(code,200)
        self.assertEqual(Image.open(io.BytesIO(raw)).size,(1080,1440))
    def test_card_local_photo_and_invalid_paths(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'abcdef012345';folder.mkdir()
            Image.new('RGB',(600,800),'#e04020').save(folder/'01.jpg')
            with patch.object(app,'TMP',root):
                code,raw=self.post('/cards',{'headline':'사진 카드','sourceImage':'/api/movist/img/abcdef012345/01.jpg'})
                self.assertEqual(code,200)
                image=Image.open(io.BytesIO(raw));self.assertEqual(image.size,(1080,1440))
                pixel=image.getpixel((10,10));self.assertGreater(pixel[0],pixel[1]*2)
                for source in ['/api/movist/img/abcdef012345/../secret.jpg','/etc/passwd','https://www.movist.com/a.jpg','/api/movist/img/abcdef012345/missing.jpg']:
                    self.assertEqual(self.post('/cards',{'sourceImage':source})[0],400)

    def test_render_set_preserves_photos_and_rights_gate(self):
        import base64
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);folder=root/'abcdef012345';folder.mkdir()
            for name,color in [('01.jpg','#e04020'),('02.jpg','#2040e0')]:
                Image.new('RGB',(600,800),color).save(folder/name)
            with patch.object(app,'TMP',root):
                code,raw=self.post('/cards/render-set',{'cards':[
                    {'headline':'첫 번째\n영화 이야기','sourceImage':'/api/movist/img/abcdef012345/01.jpg'},
                    {'headline':'두 번째 장면','body':'기사에 담긴 영화 이야기를 정리합니다.','sourceImage':'/api/movist/img/abcdef012345/02.jpg'}]})
                self.assertEqual(code,200)
                result=json.loads(raw);self.assertTrue(result['manifest']['approvalRequired'])
                self.assertEqual(result['manifest']['photoRights'],'pending')
                self.assertEqual(len(result['cards']),2)
                colors=[]
                for card in result['cards']:
                    image=Image.open(io.BytesIO(base64.b64decode(card['data'])))
                    self.assertEqual(image.size,(1080,1440));colors.append(image.getpixel((10,300)))
                self.assertGreater(colors[0][0],colors[0][2]);self.assertGreater(colors[1][2],colors[1][0])
    def test_render_limits_and_ratios(self):
        code,raw=self.post('/cards',{'headline':'세로 카드','ratio':'916'})
        self.assertEqual(code,200);self.assertEqual(Image.open(io.BytesIO(raw)).size,(1080,1920))
        self.assertEqual(self.post('/cards',{'cover':False,'body':'긴 문안 '*300})[0],400)
        self.assertEqual(self.post('/cards',{'headline':'첫째 줄\n둘째 줄\n셋째 줄'})[0],400)
        self.assertEqual(self.post('/cards',{'headline':'12345678901234'})[0],400)
        for cards in [[],[{}]*11,'invalid']:
            self.assertEqual(self.post('/cards/render-set',{'cards':cards})[0],400)

    def test_malformed_and_invalid_store(self):
        for data in [b'{',[],{'key':'ANTHROPIC_API_KEY','value':'must-not-persist'},{'key':'movist_rules','value':{}}]:
            self.assertEqual(self.post('/store',data)[0],400)
    def test_corrupt_store_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Path(tmp)/'store.json';store.write_text('{bad')
            with patch.object(app,'STORE',store):
                self.assertEqual(self.post('/store',{'key':'movist_rules','value':'rules'})[0],409)
                self.assertEqual(store.read_text(),'{bad')
    def test_valid_store(self):
        with tempfile.TemporaryDirectory() as tmp:
            store=Path(tmp)/'store.json'
            with patch.object(app,'STORE',store):
                self.assertEqual(self.post('/store',{'key':'movist_rules','value':'rules'})[0],200)
                self.assertEqual(json.loads(store.read_text()),{'movist_rules':'rules'})
    def test_ai_exception_redacted(self):
        with patch.object(app.core,'API_KEY','test-present'),patch.object(app,'ask_claude',side_effect=RuntimeError('fake-secret-never-return')):
            code,raw=self.post('/claude',{'prompt':'test'})
            self.assertEqual(code,502);self.assertNotIn(b'fake-secret',raw)
    def test_urls(self):
        for url in ['http://www.movist.com','https://127.0.0.1','https://www.movist.com.evil.test','https://user:pw@www.movist.com','https://www.movist.com:bad']:
            self.assertFalse(app.allowed_article_url(url),url)
        self.assertTrue(app.allowed_article_url('https://www.movist.com/article'))
if __name__=='__main__':unittest.main()
