import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
from fastapi.testclient import TestClient

from app.domain import bootstrap, load_sources, rank, load_settings, REFERENCE_TIME, classification, date
from app.main import app


class DomainTests(unittest.TestCase):
    def setUp(self): self.data = bootstrap()

    def test_twenty_synthetic_sources_twelve_candidates_and_two_explorations(self):
        self.assertEqual(len(self.data['sources']), 20)
        self.assertEqual(len(self.data['candidates']), 12)
        self.assertEqual(len({c['id'] for c in self.data['candidates']}), 12)
        exploratory = [c for c in self.data['candidates'] if c['exploratory']]
        self.assertEqual(len(exploratory), 2)
        self.assertTrue(all(c['category'] not in self.data['settings']['preferredCategories'] for c in exploratory))
        self.assertTrue(all(s['isSample'] for s in self.data['sources']))

    def test_scores_are_explained_and_total_matches_contributions(self):
        for c in self.data['candidates']:
            self.assertEqual(len(c['scores']), 8)
            self.assertAlmostEqual(c['totalScore'], sum(item['contribution'] for item in c['scores']))
            self.assertTrue(all(item['reason'] for item in c['scores']))
            self.assertLessEqual(next(s['contribution'] for s in c['scores'] if s['key']=='duplication'), 0)

    def test_all_citations_resolve_exact_original_positions(self):
        sources = {s['id']: s for s in self.data['sources']}
        refs = [e for item in self.data['candidates']+self.data['plans'] for e in item['evidence']]
        self.assertGreater(len(refs), 20)
        for ref in refs:
            paragraph = next(p for p in sources[ref['sourceId']]['paragraphs'] if p['id']==ref['paragraphId'])
            self.assertEqual(paragraph['text'][ref['start']:ref['end']], ref['text'])

    def test_four_plans_never_claim_unobserved_keyword_trend(self):
        self.assertEqual({p['type'] for p in self.data['plans']}, {'single','bundle','trend','questions'})
        trend = next(p for p in self.data['plans'] if p['type']=='trend')
        self.assertEqual(sum(row['count'] for row in trend['table']), 20)
        self.assertTrue(trend['limitations'])
        self.assertIn('판정하지 않습니다', trend['reason'])

    def test_config_weight_change_affects_its_component(self):
        settings = load_settings()
        settings['weights']['fit'] = 0
        candidates, _ = rank(load_sources(), settings)
        self.assertTrue(all(next(s for s in c['scores'] if s['key']=='fit')['contribution']==0 for c in candidates))

    def test_deduplicated_material_only_has_one_candidate(self):
        sources = load_sources()
        candidates, groups = rank(sources, load_settings())
        self.assertLess(len(groups), len(sources))
        all_ids = [i for c in candidates for i in c['sourceIds']]
        self.assertEqual(len(all_ids), len(set(all_ids)))

    def test_future_embargo_is_locked_and_sensitive_category_flagged(self):
        source = load_sources()[0]
        source['embargoAt'] = '2099-01-01T09:00:00+09:00'
        source['restricted'] = True
        candidates, _ = rank([source], load_settings())
        self.assertTrue(candidates[0]['sendBlocked'])
        self.assertTrue(candidates[0]['restricted'])
        self.assertEqual(next(s['raw'] for s in candidates[0]['scores'] if s['key']=='embargo'), 0)


    def test_configurable_limit_and_insufficient_material_never_invent_sources(self):
        sources = load_sources()
        settings = load_settings()
        settings['recommendations'] = {'count':4,'exploration_count':1}
        candidates, _ = rank(sources, settings)
        self.assertEqual(len(candidates),4)
        self.assertEqual(sum(c['exploratory'] for c in candidates),1)
        self.assertEqual(rank([],settings)[0],[])
        candidates, _ = rank(sources[:1],settings)
        self.assertEqual(len(candidates),1)

    def test_mail_received_after_reference_is_not_recommended(self):
        source=load_sources()[0]
        source['receivedAt']='2099-01-01T09:00:00+09:00'
        self.assertEqual(rank([source],load_settings())[0],[])
        by_id={s['id']:s for s in self.data['sources']}
        self.assertTrue(all(date(by_id[c['sourceId']]['receivedAt'])<=REFERENCE_TIME for c in self.data['candidates']))

    def test_corrected_version_replaces_initial_without_duplicate_penalty(self):
        ids={c['sourceId'] for c in self.data['candidates']}
        self.assertNotIn('sample-05',ids)
        sources=load_sources()
        versions=[s for s in sources if s.get('revisionGroup')]
        self.assertTrue(versions)
        candidates,_=rank(versions,load_settings())
        self.assertEqual(len(candidates),1)
        self.assertEqual(candidates[0]['sourceId'],'sample-06')
        self.assertEqual(next(s['raw'] for s in candidates[0]['scores'] if s['key']=='duplication'),0)

    def test_classification_uses_external_keyword_rules_not_expected_label(self):
        category, explanation=classification('새 영화 상영','영화 관객과 극장','기업')
        self.assertEqual(category,'영화')
        self.assertEqual(explanation['method'],'rules')
        self.assertTrue(explanation['matchedKeywords'])
        self.assertEqual(classification('unmatched xyz','plain zzz','기업')[0],'기타')


class APITests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.env = patch.dict(os.environ, {'CONTENT_MAKER_DB':str(Path(self.folder.name)/'sample.sqlite3')})
        self.env.start()
        self.client = TestClient(app)
        self.candidate_id = bootstrap()['candidates'][0]['id']

    def tearDown(self):
        self.client.close()
        self.env.stop()
        self.folder.cleanup()

    def payload(self, **changes):
        return {'candidateId':self.candidate_id,'rating':4,'tag':'후속취재','comment':'숫자 기준 확인 필요',**changes}

    def test_real_connections_never_inferred_from_environment_credentials(self):
        with patch.dict(os.environ, {'NAVER_APP_PASSWORD':'do-not-use','ANTHROPIC_API_KEY':'do-not-use'}):
            data = self.client.get('/api/bootstrap').json()
        self.assertEqual(data['mode'], 'sample')
        self.assertTrue(all(c['status']=='미연결' for c in data['connections']))
        self.assertFalse(data['capabilities']['publication'])
        self.assertNotIn('do-not-use', json.dumps(data))

    def test_evaluation_persists_and_replaces_same_candidate_after_client_restart(self):
        response = self.client.post('/api/evaluations', json=self.payload())
        self.assertEqual(response.status_code, 200)
        self.assertFalse(response.json()['learningApplied'])
        with TestClient(app) as restarted:
            self.assertEqual(restarted.get('/api/evaluations').json()['items'][0]['rating'], 4)
            self.assertEqual(restarted.post('/api/evaluations', json=self.payload(rating=2, tag='보류')).status_code, 200)
            values = restarted.get('/api/bootstrap').json()['evaluations']
            self.assertEqual(len(values), 1)
            self.assertEqual(values[0]['rating'], 2)

    def test_reject_invalid_ratings_unknown_candidates_and_control_fields(self):
        for rating in [0,6,True,'5',3.5]:
            self.assertEqual(self.client.post('/api/evaluations',json=self.payload(rating=rating)).status_code,422)
        self.assertEqual(self.client.post('/api/evaluations',json=self.payload(candidateId='unknown')).status_code,404)
        self.assertEqual(self.client.post('/api/evaluations',json=self.payload(tag='승인')).status_code,422)
        self.assertEqual(self.client.post('/api/evaluations',json=self.payload(comment='x'*1001)).status_code,422)
        self.assertEqual(self.client.post('/api/evaluations',json=self.payload(publish=True)).status_code,422)
        self.assertEqual(self.client.get('/api/evaluations').json()['items'], [])

    def test_cross_origin_cannot_mutate_sample_store(self):
        r=self.client.post('/api/evaluations',json=self.payload(),headers={'Origin':'https://untrusted.example'})
        self.assertEqual(r.status_code,403)
        self.assertEqual(self.client.get('/api/evaluations').json()['items'], [])

    def test_future_functions_are_explicitly_unavailable(self):
        for path in ['/api/publish','/api/approve','/api/collect','/api/ai/draft']:
            self.assertEqual(self.client.post(path).status_code,409)

    def test_source_lookup_and_health_are_truthful(self):
        self.assertEqual(self.client.get('/api/sources/not-present').status_code,404)
        source=load_sources()[0]
        self.assertEqual(self.client.get('/api/sources/'+source['id']).json()['id'],source['id'])
        h=self.client.get('/api/health').json()
        self.assertEqual(h['phase'],1)
        self.assertFalse(h['imapConnected'])

    def test_export_never_includes_saved_evaluations(self):
        self.client.post('/api/evaluations',json=self.payload(comment='private-editor-comment'))
        self.assertEqual(bootstrap([])['evaluations'],[])
        self.assertNotIn('private-editor-comment',json.dumps(bootstrap([])))

if __name__=='__main__': unittest.main()
