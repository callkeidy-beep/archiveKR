"""Discovery must only return real, permitted editorial links and bounded responses."""
import unittest
from unittest.mock import patch, MagicMock
import movist_auto as core

class IngestionTests(unittest.TestCase):
    def test_official_links_only_deduplicated(self):
        html='''<a href="http://www.movist.com/movist3d/view.asp?type=13&id=atc000000013047"></a>
        <a href="/movist3d/view.asp?id=atc000000013047&type=13&page=2">실제 제목</a>
        <a href="https://evil.test/movist3d/view.asp?type=13&id=atc000000013047">악성</a>
        <a href="/comm/view.asp?type=13&id=atc000000013047">독자글</a>
        <a href="/movist3d/view.asp?type=13&id=bad">오류</a>'''
        self.assertEqual(core.parse_latest(html),[{'url':'https://www.movist.com/movist3d/view.asp?type=13&id=atc000000013047','title':'실제 제목'}])
    def test_mobile_allowed_credentials_and_ports_rejected(self):
        self.assertTrue(core.allowed_movist_url('https://m.movist.com/article'))
        for url in ['https://m.movist.com.evil.test/', 'https://u:p@m.movist.com/', 'https://m.movist.com:444/', 'http://m.movist.com/']:
            self.assertFalse(core.allowed_movist_url(url))
    def test_dynamic_article_uses_api_not_navigation(self):
        html = "<nav>unrelated navigation</nav><script>ajaxData = 'c='+ id + '&apikey=public-example'; url='/API/article/get_MOVIST_view.php';</script>"
        page=MagicMock();page.text=html
        api=MagicMock();api.json.return_value={'article':[{'tit':'원문 제목','writer':'기자','contents':'<article><p>검증된 실제 기사 본문입니다. 영화 개봉 소식을 전합니다.</p></article>','regidate':'2026-10-10'}]}
        with patch.object(core,'bounded_get',side_effect=[page,api]) as get:
            article=core.fetch_article('https://www.movist.com/movist3d/view.asp?type=13&id=atc000000013047')
            self.assertEqual(article['title'],'원문 제목')
            self.assertNotIn('navigation',article['body'])
            self.assertTrue(get.call_args.args[0].startswith('https://m.movist.com/API/article/get_MOVIST_view.php?'))
        with patch.object(core,'bounded_get',side_effect=[page,RuntimeError('blocked')]):
            with self.assertRaises(RuntimeError):core.fetch_article('https://www.movist.com/movist3d/view.asp?type=13&id=atc000000013047')

    def test_size_limit_and_redirects(self):
        response=MagicMock();response.__enter__.return_value=response
        response.status_code=200;response.iter_content.return_value=[b'a'*9,b'b'*9]
        with patch.object(core.requests,'get',return_value=response) as get:
            with self.assertRaisesRegex(ValueError,'size_limit'):core.bounded_get(core.LATEST_URL,limit=10)
            self.assertFalse(get.call_args.kwargs['allow_redirects'])
            self.assertEqual(get.call_args.kwargs['timeout'],(8,20))
        response.status_code=302
        with patch.object(core.requests,'get',return_value=response):
            with self.assertRaisesRegex(ValueError,'upstream_response'):core.bounded_get(core.LATEST_URL)

if __name__ == '__main__':unittest.main()
