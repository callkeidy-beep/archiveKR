"""Deterministic editorial support. No AI, IMAP, or publication calls."""
from collections import Counter
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path
import json
import math
import re
import yaml

ROOT = Path(__file__).resolve().parents[1]
REFERENCE_TIME = datetime.fromisoformat('2026-10-22T07:00:00+09:00')
DIMENSIONS = {
    'timeliness': ('시의성', 20), 'impact': ('독자 영향력', 20),
    'rarity': ('독점성·희소성', 10), 'fit': ('매체 적합도', 20),
    'visuals': ('사진·시각 자료', 10), 'embargo': ('엠바고 시점', 5),
    'followup': ('후속 취재 가능성', 15), 'duplication': ('중복도 감점', 10),
}


def load_settings():
    settings = {}
    for name in ('settings.yaml', 'editorial.yaml', 'scoring.yaml', 'categories.yaml', 'app.yaml'):
        p = ROOT / 'config' / name
        if p.exists():
            content = yaml.safe_load(p.read_text()) or {}
            if isinstance(content, dict): settings.update(content)
    settings.setdefault('media', settings.get('publication', {}).get('default_medium', '무비스트'))
    settings.setdefault('preferredCategories', settings.get('recommendations', {}).get('preferred_categories', ['영화', '공연', '전시', '방송']))
    settings.setdefault('weights', {k: v[1] for k, v in DIMENSIONS.items()})
    return settings


def date(value):
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError): return REFERENCE_TIME


def classification(title, body, expected=None):
    path = ROOT / 'config' / 'classification.yaml'
    taxonomy = yaml.safe_load(path.read_text()) if path.exists() else {}
    keywords = (taxonomy or {}).get('classification', {}).get('keywords', {})
    if not keywords:
        return expected or '기타', {'method':'sample_label','reason':'샘플 자료에 지정된 분류입니다. 실제 메일 자동 분류 결과가 아닙니다.'}
    title_text, body_text = title.casefold(), body.casefold()
    scores = {}
    matched = {}
    for category, words in keywords.items():
        if not isinstance(words, list): continue
        hits = [str(word) for word in words if str(word).casefold() in title_text or str(word).casefold() in body_text]
        scores[category] = sum((3 if word.casefold() in title_text else 0)+(1 if word.casefold() in body_text else 0) for word in hits)
        matched[category] = hits
    maximum = max(scores.values(), default=0)
    winners = [category for category, score in scores.items() if score==maximum and maximum>0]
    category = winners[0] if winners else '기타'
    return category, {'method':'rules','reason':f'설정 키워드 일치: {", ".join(matched.get(category, [])) or "없음 → 기타"}. 제목 가중치3·본문1의 규칙 분류입니다.','matchedKeywords':matched.get(category, []),'scores':scores}

def load_sources():
    payload = json.loads((ROOT / 'fixtures' / 'mail.json').read_text())
    if isinstance(payload, dict): payload = payload.get('sources', payload.get('messages', payload.get('mails', [])))
    sources = []
    for index, raw in enumerate(payload):
        item = dict(raw)
        item.setdefault('id', f'mail-{index+1:03d}')
        item['title'] = item.get('title', item.get('subject', '제목 없음'))
        item['subject'] = item['title']
        paragraphs = item.get('paragraphs') or [{'id': f'p{n+1}', 'text': text} for n, text in enumerate(re.split(r'\n+', item.get('body', ''))) if text.strip()]
        item['paragraphs'] = [dict(p, id=p.get('id', f'p{n+1}')) for n,p in enumerate(paragraphs)]
        item['body'] = '\n\n'.join(p['text'] for p in item['paragraphs'])
        item['sampleCategory'] = item.get('category')
        item['category'], item['classification'] = classification(item['title'], item['body'], item.get('category'))
        item.setdefault('sender', {'organization': item.get('organization', '샘플 발신처'), 'email': 'sample@example.invalid'})
        if isinstance(item['sender'], str): item['sender'] = {'organization': item['sender'], 'email': 'sample@example.invalid'}
        item.setdefault('photos', [])
        item.setdefault('attachments', [])
        item.setdefault('accountId', item.get('account', 'naver-sample'))
        item['embargoAt'] = item.get('embargoAt') or item.get('embargoUntil') or None
        item['restricted'] = bool(item.get('restricted') or item['category'] in ('재난', '사고', '범죄', '선거'))
        item['isSample'] = True
        item['receivedAt'] = item.get('receivedAt', REFERENCE_TIME.isoformat())
        sources.append(item)
    return sources


def evidence(source, paragraph=0):
    if not source['paragraphs']: return []
    p = source['paragraphs'][min(paragraph, len(source['paragraphs'])-1)]
    return [{'sourceId': source['id'], 'paragraphId': p['id'], 'start': 0, 'end': len(p['text']), 'text': p['text']}]


def deduplicate(sources):
    """Group exact IDs or substantially identical title/body; keep newest version."""
    groups = []
    for source in sorted(sources, key=lambda x: (date(x['receivedAt']), x['id']), reverse=True):
        existing = next((group for group in groups if same_material(source, group[0])), None)
        if existing is None: groups.append([source])
        else: existing.append(source)
    for group in groups:
        group[0]['versionIds'] = [s['id'] for s in group if s.get('revisionGroup')]
        group[0]['isLatestVersion'] = True
        for older in group[1:]:
            older['isLatestVersion'] = False if older.get('revisionGroup') else None
        group[0]['duplicateIds'] = [s['id'] for s in group[1:] if not s.get('revisionGroup') or s.get('messageId') == group[0].get('messageId')]
        group[0]['receivedAccounts'] = sorted(set(s['accountId'] for s in group))
    return groups


def same_material(a, b):
    if a.get('revisionGroup') and a.get('revisionGroup') == b.get('revisionGroup'): return True
    if a.get('messageId') and a.get('messageId') == b.get('messageId'): return True
    a_title = re.sub(r'\s|\[수정\]|\[재발송\]|\[보도자료\]', '', a['title'])
    b_title = re.sub(r'\s|\[수정\]|\[재발송\]|\[보도자료\]', '', b['title'])
    if a_title != b_title: return False
    return SequenceMatcher(None, a['body'], b['body']).ratio() >= .9


def rank(sources, settings, reference_time=REFERENCE_TIME):
    groups = deduplicate([source for source in sources if date(source['receivedAt']) <= reference_time])
    recommendation_settings = settings.get('recommendations', {})
    def bounded(value, fallback, minimum, maximum):
        try: return max(minimum, min(maximum, int(value)))
        except (ValueError, TypeError): return fallback
    count = bounded(recommendation_settings.get('count',12),12,1,12)
    exploration_count = bounded(recommendation_settings.get('exploration_count',2),2,0,min(2,count))
    preferred = settings.get('preferredCategories', settings.get('preferred_categories', ['영화', '공연', '전시', '방송']))
    configured = settings.get('weights', {})
    candidates = []
    for group in groups:
        source = group[0]
        age = max(0, (reference_time - date(source['receivedAt'])).total_seconds()/86400)
        duplicate_count = len(source.get('duplicateIds', []))
        embargo_active = bool(source['embargoAt'] and date(source['embargoAt']) > reference_time)
        # Observable signals only, each reason explains its mechanical limits.
        raw = {
            'timeliness': max(1, 5 - min(4, int(age))),
            'impact': min(5, 1 + len(re.findall(r'\d+(?:[.,]\d+)*', source['body']))),
            'rarity': 5 if duplicate_count == 0 else 2,
            'fit': 5 if source['category'] in preferred else 2,
            'visuals': 5 if source['photos'] else 1,
            'embargo': 0 if embargo_active else 5,
            'followup': min(5, 1 + len(source['paragraphs'])),
            'duplication': min(5, duplicate_count),
        }
        reasons = {
            'timeliness': f'샘플 기준시각 대비 수신 후 {int(age)}일. 실제 뉴스 가치 판정은 아닙니다.',
            'impact': '본문의 숫자 표현 수를 사용한 초기 대리 지표입니다. 영향력의 실제 검증은 필요합니다.',
            'rarity': f'동일 내용 중복 수신 {duplicate_count+1}건. 독점 취재 여부를 확인한 값은 아닙니다.',
            'fit': '설정의 선호 분야 일치 여부를 사용합니다.',
            'visuals': f'첨부 사진 {len(source["photos"])}장. 사용 권한 확인과는 별개입니다.',
            'embargo': '엠바고 해제 전입니다. 송고 불가.' if embargo_active else '기록된 미래 엠바고가 없습니다. 원문 확인이 필요합니다.',
            'followup': f'원문 문단 {len(source["paragraphs"])}개에 기반한 초기 대리 지표입니다.',
            'duplication': f'추가 중복 수신 {duplicate_count}건을 감점합니다.',
        }
        scores = []
        for key, (label, fallback) in DIMENSIONS.items():
            weight = configured.get(key, fallback)
            if isinstance(weight, dict): weight = weight.get('weight', fallback)
            try: weight = float(weight)
            except (ValueError, TypeError): weight = fallback
            if not math.isfinite(weight): weight = fallback
            weight = min(100, abs(weight))
            sign = -1 if key == 'duplication' else 1
            contribution = round(sign * raw[key] / 5 * abs(weight), 2)
            scores.append({'key': key, 'label': label, 'raw': raw[key], 'weight': abs(weight), 'contribution': contribution, 'reason': reasons[key]})
        candidates.append({'id': 'candidate-' + source['id'], 'sourceId': source['id'], 'sourceIds': [s['id'] for s in group], 'title': source['title'], 'category': source['category'], 'totalScore': round(sum(s['contribution'] for s in scores), 2), 'scores': scores, 'reason': f'{source["category"]} 자료 · 원문 {len(source["paragraphs"])}문단 · 사진 {len(source["photos"])}장. 항목별 규칙 점수를 확인하세요.', 'exploratory': False, 'evidence': evidence(source), 'embargoAt': source['embargoAt'], 'sendBlocked': embargo_active, 'restricted': source['restricted']})
    ordered = sorted(candidates, key=lambda c: (-c['totalScore'], c['id']))
    exploration = [c for c in ordered if c['category'] not in preferred][:exploration_count]
    explore_ids = {c['id'] for c in exploration}
    regular = [c for c in ordered if c['id'] not in explore_ids][:count-len(exploration)]
    selected = regular + [dict(c, exploratory=True) for c in exploration]
    if len(selected) < count:
        selected_ids = {c['id'] for c in selected}
        selected += [c for c in ordered if c['id'] not in selected_ids][:count-len(selected)]
    for n, candidate in enumerate(selected, 1): candidate['rank'] = n
    return selected, groups


def make_plans(sources, candidates):
    by_id = {s['id']: s for s in sources}
    first = by_id[candidates[0]['sourceId']] if candidates else None
    single = {'id': 'plan-single', 'type': 'single', 'title': '단일 보도자료 기사', 'reason': '선정 자료 한 건의 원문 사실을 정리하는 스트레이트 기획입니다.', 'sourceIds': [first['id']] if first else [], 'evidence': evidence(first) if first else []}
    unique_sources = [group[0] for group in deduplicate(sources)]
    categories = Counter(s['category'] for s in sources)
    category = categories.most_common(1)[0][0] if categories else '기타'
    bundle_sources = [s for s in unique_sources if s['category'] == category][:3]
    bundle = {'id':'plan-bundle', 'type':'bundle', 'title':f'{category} 자료 묶음 기사', 'reason':f'같은 분야({category})로 분류된 자료를 묶었습니다. 동일 업계·기간 여부는 원문 대조로 확인하세요.', 'sourceIds':[s['id'] for s in bundle_sources], 'evidence':[e for s in bundle_sources for e in evidence(s)]}
    trend = {'id':'plan-trend', 'type':'trend', 'title':'수신 자료의 분야별 분포', 'reason':'현재 샘플의 분야별 건수만 집계합니다. 이전 기간 비교 데이터가 없어 증가·감소 추세는 판정하지 않습니다.', 'sourceIds':[s['id'] for s in sources], 'evidence':[e for s in sources for e in evidence(s)], 'table':[{'category':k,'count':v} for k,v in sorted(categories.items())], 'limitations':['메일 건수이며 시장 규모나 독자 관심도 통계가 아닙니다.', '키워드 증감 분석은 비교 기간 자료가 필요합니다.']}
    questions = {'id':'plan-questions','type':'questions','title':'추가 취재 질문과 확인할 쟁점','reason':'아래 항목은 사실 주장이 아닌 취재 질문입니다. 원문을 근거로 편집자가 확인 범위를 정합니다.', 'sourceIds':[first['id']] if first else [],'evidence':evidence(first) if first else [],'questions':[{'target':first['sender'].get('organization','발신처') if first else '발신처','question':'발표한 숫자의 기준 시점과 집계 방법은 무엇인가요?'},{'target':'관련 이해관계자','question':'원문에 없는 비교 대상과 비용 부담은 어떻게 확인할 수 있나요?'},{'target':'사진 제공처','question':'첨부 사진의 사용 범위와 필수 출처 표기는 무엇인가요?'}]}
    for plan in [single,bundle,trend,questions]:
        linked = [by_id[sid] for sid in plan['sourceIds']]
        plan['restricted'] = any(source['restricted'] for source in linked)
        plan['sendBlocked'] = any(source['embargoAt'] and date(source['embargoAt']) > REFERENCE_TIME for source in linked)
        plan['draftingEnabled'] = False
    return [single,bundle,trend,questions]


def bootstrap(evaluations=None):
    settings = load_settings()
    sources = load_sources()
    candidates, groups = rank(sources, settings)
    try: desired = max(1,min(12,int(settings.get('recommendations', {}).get('count',12))))
    except (TypeError,ValueError): desired=12
    try: desired_exploration=max(0,min(2,int(settings.get('recommendations',{}).get('exploration_count',2))))
    except (TypeError,ValueError): desired_exploration=2
    warnings=[]
    if len(candidates)<desired: warnings.append('자료가 부족해 설정한 후보 수를 채우지 않았습니다.')
    if sum(c['exploratory'] for c in candidates)<desired_exploration: warnings.append('선호 분야 밖 자료가 부족해 탐색 후보 수를 채우지 않았습니다.')
    return {'name':'콘텐츠메이커 엔진','mode':'sample','sample':True,'referenceTime':REFERENCE_TIME.isoformat(),'sampleReferenceTime':REFERENCE_TIME.isoformat(),'notice':'샘플 자료 20건으로 동작합니다. 실제 메일 수집·AI 작성·송고는 연결하지 않았습니다.','sources':sources,'candidates':candidates,'plans':make_plans(sources,candidates),'evaluations':evaluations or [],'settings':settings,'overview':{'received':len(sources),'uniqueSources':len(groups),'duplicateCount':sum(len(g[0].get('duplicateIds',[])) for g in groups),'supersededCount':sum(max(0,len(g[0].get('versionIds',[]))-1) for g in groups),'deferredCount':sum(date(source['receivedAt'])>REFERENCE_TIME for source in sources),'candidates':len(candidates),'exploratory':sum(c['exploratory'] for c in candidates)},'connections':[{'id':'naver','name':'네이버 메일 IMAP','status':'미연결','detail':'앱 비밀번호·IMAP 설정·실제 SSL 접속 시험이 필요합니다.'},{'id':'daum','name':'다음 메일 IMAP','status':'미연결','detail':'앱 비밀번호 요건과 공식 도움말 확인 후 실제 접속 시험이 필요합니다.'},{'id':'ai','name':'AI API','status':'미연결','detail':'1단계는 규칙 기반입니다. AI API를 호출하지 않습니다.'},{'id':'publishing','name':'외부 송고·SNS','status':'미연결','detail':'이번 단계에는 게시 기능이 없습니다.'}], 'warnings':warnings, 'capabilities':{'imap':False,'ai':False,'publication':False,'learning':False,'scheduledBackup':False,'evaluations':True}}
