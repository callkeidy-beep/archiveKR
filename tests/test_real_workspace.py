import unittest
from datetime import datetime, timezone
from app.domain import build_workspace


class RealWorkspaceTests(unittest.TestCase):
    def test_real_workspace_uses_actual_date_and_exact_evidence(self):
        now=datetime.now(timezone.utc).isoformat()
        sources=[{'id':'real-1','title':'영화 개봉 보도자료','body':'영화가 11월 1일 개봉한다.','receivedAt':now,'sender':{'organization':'홍보팀','email':'press@example.test'},'embargoAt':'9999-12-31T00:00:00+00:00'}]
        result=build_workspace(sources)
        self.assertFalse(result['sample'])
        self.assertEqual(result['mode'],'real')
        self.assertEqual(len(result['candidates']),1)
        self.assertTrue(result['candidates'][0]['sendBlocked'])
        self.assertTrue(result['plans'][0]['sendBlocked'])
        ev=result['candidates'][0]['evidence'][0]
        self.assertEqual(ev['text'],result['sources'][0]['paragraphs'][0]['text'][ev['start']:ev['end']])
        self.assertNotIn('category',sources[0])
        self.assertFalse(result['sources'][0]['isSample'])
    def test_empty_real_inbox_does_not_invent_candidates(self):
        result=build_workspace([])
        self.assertEqual(result['candidates'],[])
        self.assertEqual(result['sources'],[])
        self.assertTrue(result['warnings'])

    def test_manual_review_placeholders_are_not_article_evidence(self):
        result=build_workspace([{'id':'manual-1','title':'대용량 메일','body':'본문 미수집',
                                'receivedAt':datetime.now(timezone.utc).isoformat(),
                                'collectionStatus':'manual_review'}])
        self.assertEqual(len(result['sources']),1)
        self.assertEqual(result['candidates'],[])
        self.assertTrue(all(not plan['evidence'] for plan in result['plans']))
