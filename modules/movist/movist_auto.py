"""
콘텐츠 기사 자동 변환기 (로컬 실행용)

하는 일
  1. 새 기사를 찾는다 (RSS 주소, 또는 inbox 폴더에 넣은 파일)
  2. Claude API로 채널별 문구를 만든다 (텔레그램·카카오·인스타·쇼츠·영문)
  3. Claude로 한 번 더 원문과 대조해 검증한다
  4. output 폴더에 결과를 저장하고, 텔레그램은 설정돼 있으면 자동 게시한다
  5. 기사 사진을 내려받고, 쇼츠 적합도가 높으면 쇼츠 영상(MP4)까지 만든다

실행
  python movist_auto.py            # 계속 켜 두고 주기적으로 확인
  python movist_auto.py --once     # 한 번만 확인하고 종료
  python movist_auto.py --url 주소  # 기사 1건만 바로 변환
  python movist_auto.py --shorts output/기사폴더  # 사진을 바꾼 뒤 쇼츠만 다시 만들기
"""
import argparse, hashlib, json, os, re, sys, time
from datetime import datetime
from pathlib import Path

import requests
from dotenv import load_dotenv

BASE = Path(__file__).resolve().parent
load_dotenv(BASE / "config.env")

API_KEY = os.getenv("ANTHROPIC_API_KEY", "").strip()
MODEL = os.getenv("MODEL", "claude-sonnet-4-5").strip()
RSS_URL = os.getenv("RSS_URL", "").strip()
TG_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TG_CHAT = os.getenv("TELEGRAM_CHAT_ID", "").strip()
TG_AUTO = os.getenv("TELEGRAM_AUTO_POST", "no").strip().lower() == "yes"
MINUTES = int(os.getenv("CHECK_MINUTES", "10"))
VERIFY = os.getenv("VERIFY", "yes").strip().lower() == "yes"

SHORTS = os.getenv("SHORTS", "yes").strip().lower() == "yes"
SHORTS_MIN_FIT = int(os.getenv("SHORTS_MIN_FIT", "4"))
SHORTS_CFG = {
    "hf_id": os.getenv("HIGGSFIELD_KEY_ID", "").strip(),
    "hf_secret": os.getenv("HIGGSFIELD_KEY_SECRET", "").strip(),
    "hf_model": os.getenv("HIGGSFIELD_MODEL", "alibaba/wan-3.0-prime/image-to-video").strip(),
    "hf_resolution": os.getenv("HIGGSFIELD_RESOLUTION", "720p").strip(),
    "hf_cuts": os.getenv("HIGGSFIELD_CUTS", "first").strip().lower(),   # none / first / all
    "tts": os.getenv("TTS_ENGINE", "edge").strip().lower(),             # edge / elevenlabs
    "voice": os.getenv("TTS_VOICE", "ko-KR-InJoonNeural").strip(),
    "el_key": os.getenv("ELEVENLABS_API_KEY", "").strip(),
    "el_voice": os.getenv("ELEVENLABS_VOICE_ID", "").strip(),
    "accent": os.getenv("ACCENT_COLOR", "#C8102E").strip(),
}

INBOX = BASE / "inbox"
DONE = BASE / "inbox" / "done"
OUT = BASE / "output"
STATE = BASE / "seen.json"
for p in (INBOX, DONE, OUT):
    p.mkdir(parents=True, exist_ok=True)

UA = {"User-Agent": "Mozilla/5.0 (MOVIST auto converter)"}


def log(msg):
    print(f"[{datetime.now():%H:%M:%S}] {msg}", flush=True)


# ---------- 상태 기록 (같은 기사 중복 처리 방지) ----------
def load_seen():
    try:
        return set(json.loads(STATE.read_text(encoding="utf-8")))
    except Exception:
        return set()


def save_seen(seen):
    STATE.write_text(json.dumps(sorted(seen), ensure_ascii=False, indent=1), encoding="utf-8")


def key_of(s):
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:16]


MOVIST_HOSTS = {"movist.com", "www.movist.com", "m.movist.com"}
LATEST_URL = "https://www.movist.com/"


def allowed_movist_url(url):
    from urllib.parse import urlparse
    try:
        p = urlparse(url)
        return p.scheme == "https" and p.hostname in MOVIST_HOSTS and p.port in (None, 443) and not p.username and not p.password
    except (ValueError, TypeError):
        return False


def bounded_get(url, limit=3 * 1024 * 1024, headers=None):
    """Verified HTTPS, fixed destinations, no redirects, bounded response body."""
    if not allowed_movist_url(url):
        raise ValueError("설정된 수집 출처의 HTTPS 주소만 사용할 수 있습니다")
    with requests.get(url, headers=headers or UA, timeout=(8, 20), allow_redirects=False, stream=True) as resp:
        resp.raise_for_status()
        if resp.status_code != 200:
            raise ValueError("upstream_response")
        content = bytearray()
        for chunk in resp.iter_content(65536):
            content.extend(chunk)
            if len(content) > limit:
                raise ValueError("upstream_size_limit")
        resp._content = bytes(content)
        if not resp.encoding or resp.encoding.lower() in ("iso-8859-1", "latin-1", "ascii"):
            resp.encoding = resp.apparent_encoding or "utf-8"
        return resp


def parse_latest(html, page_url=LATEST_URL):
    """Only official editorial article links, excluding community posts and ads."""
    from urllib.parse import urljoin, urlparse, parse_qs, urlencode, urlunparse
    import lxml.html
    doc = lxml.html.fromstring(html)
    items = {}
    for a in doc.xpath('//a[@href]'):
        p = urlparse(urljoin(page_url, a.get("href")))
        if p.scheme == "http" and p.hostname in MOVIST_HOSTS:
            p = p._replace(scheme="https")
        if not allowed_movist_url(p.geturl()) or p.path.lower() not in ("/movist3d/view.asp", "/star3d/view.asp"):
            continue
        q = parse_qs(p.query)
        article_id = q.get("id", [""])[0]
        article_type = q.get("type", [""])[0]
        if not re.fullmatch(r"atc[0-9]{8,20}", article_id) or not article_type.isdigit():
            continue
        url = urlunparse(("https", "www.movist.com", p.path.lower(), "", urlencode({"type": article_type, "id": article_id}), ""))
        title = " ".join(a.text_content().split())[:500]
        if url not in items or (title and not items[url]["title"]):
            items[url] = {"url": url, "title": title}
    return list(items.values())[:40]


def latest_articles():
    response = bounded_get(LATEST_URL)
    return {"items": parse_latest(response.text), "source": LATEST_URL, "upstreamStatus": response.status_code,
            "checkedAt": datetime.now().astimezone().isoformat()}


# ---------- 기사 가져오기 ----------
def fetch_article(url):
    """기사 URL에서 제목과 본문을 뽑는다."""
    import trafilatura
    resp = bounded_get(url)
    html = resp.text
    # Current official pages load the article via their public browser API.
    # Never treat the surrounding navigation as the article when that API fails.
    if "/API/article/get_MOVIST_view.php" in html:
        from urllib.parse import parse_qs, urlparse, urlencode
        from html import unescape
        article_id = parse_qs(urlparse(url).query).get("id", [""])[0]
        public_key = re.search(r"ajaxData\s*=\s*['\"]c=['\"]\s*\+\s*id\s*\+\s*['\"]&apikey=([^'\"]+)", html)
        if not public_key or not re.fullmatch(r"atc[0-9]{8,20}", article_id):
            raise ValueError("article_api_unavailable")
        api_url = "https://m.movist.com/API/article/get_MOVIST_view.php?" + urlencode({"c": article_id, "apikey": public_key.group(1)})
        payload = bounded_get(api_url).json()
        records = payload.get("article") if isinstance(payload, dict) else None
        if not records or not isinstance(records[0], dict):
            raise ValueError("article_missing")
        article = records[0]
        html = unescape(str(article.get("contents") or ""))
        import lxml.html
        document = lxml.html.fromstring(html or "<p></p>")
        for node in document.xpath("//script|//style"):
            node.drop_tree()
        body = "\n".join(line.strip() for line in document.text_content().splitlines() if line.strip())
        if not body.strip():
            raise ValueError("article_body_missing")
        return {"title": unescape(str(article.get("tit") or "")), "author": str(article.get("writer") or ""),
                "url": url, "publishedAt": str(article.get("regidate") or ""), "credit": "", "body": body.strip(),
                "images": find_images(html, url)}
    body = trafilatura.extract(html, include_comments=False, include_tables=False) or ""
    meta = trafilatura.extract_metadata(html)
    title = (meta.title if meta and meta.title else "").strip()
    credit = ""
    m = re.search(r"사진\s*제공[.\s:]*([^\n]+)", body)
    if m:
        credit = m.group(1).strip()
    return {"title": title, "author": (meta.author if meta and meta.author else ""), "url": url,
            "credit": credit, "body": body.strip(), "images": find_images(html, url)}


SKIP_IMG = re.compile(r"logo|icon|banner|btn|button|sprite|blank|spacer|ad[_/-]|/ads?/|profile|avatar|sns|facebook|kakao|twitter", re.I)


def find_images(html, page_url):
    """기사 페이지에서 본문 사진 후보 주소를 찾는다."""
    from urllib.parse import urljoin
    import lxml.html
    try:
        doc = lxml.html.fromstring(html)
    except Exception:
        return []
    urls = []
    for m in doc.xpath('//meta[@property="og:image"]/@content'):
        urls.append(urljoin(page_url, m))
    for img in doc.xpath("//img"):
        src = img.get("data-src") or img.get("data-original") or img.get("src") or ""
        if not src or src.startswith("data:") or SKIP_IMG.search(src):
            continue
        urls.append(urljoin(page_url, src))
    seen, out = set(), []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:20]


def download_images(urls, folder, referer=""):
    """사진을 내려받아 가로·세로 400px 이상인 것만 남긴다."""
    from PIL import Image
    folder.mkdir(parents=True, exist_ok=True)
    kept, sigs = 0, set()
    for u in urls:
        if not allowed_movist_url(u):
            continue
        try:
            r = bounded_get(u, limit=12 * 1024 * 1024, headers={**UA, "Referer": referer})
            if not r.ok or len(r.content) < 15000:
                continue
            sig = hashlib.sha1(r.content).hexdigest()
            if sig in sigs:
                continue
            p = folder / f"{kept+1:02d}.jpg"
            from io import BytesIO
            im = Image.open(BytesIO(r.content))
            if im.width < 400 or im.height < 400:
                continue
            im.convert("RGB").save(p, quality=92)
            sigs.add(sig)
            kept += 1
        except Exception:
            continue
    return kept


def from_rss(seen):
    if not RSS_URL:
        return []
    import feedparser
    feed = feedparser.parse(RSS_URL, request_headers=UA)
    items = []
    for e in feed.entries[:20]:
        link = e.get("link", "")
        if not link or key_of(link) in seen:
            continue
        items.append(("rss", link, link))
    return items


def from_inbox(seen):
    """inbox 폴더의 .txt 파일. 내용이 URL 한 줄이면 그 기사를 가져오고,
    아니면 첫 줄=제목, 나머지=본문으로 본다."""
    items = []
    for f in sorted(INBOX.glob("*.txt")):
        items.append(("file", str(f), f.name))
    for d in sorted(p for p in INBOX.iterdir() if p.is_dir() and p.name != "done"):
        if list(d.glob("*.txt")):
            items.append(("dir", str(d), d.name))
    return items


IMG_EXT = (".jpg", ".jpeg", ".png", ".webp")


def load_item(kind, ref):
    if kind == "rss":
        return fetch_article(ref)
    if kind == "dir":
        d = Path(ref)
        art = load_item("file", str(sorted(d.glob("*.txt"))[0]))
        art["local_images"] = sorted(str(p) for p in d.iterdir() if p.suffix.lower() in IMG_EXT)
        return art
    text = Path(ref).read_text(encoding="utf-8", errors="ignore").strip()
    if re.fullmatch(r"https?://\S+", text):
        return fetch_article(text)
    lines = text.splitlines()
    title = lines[0].strip() if lines else ""
    body = "\n".join(lines[1:]).strip()
    url = ""
    m = re.search(r"https?://\S+", body)
    if m and len(body) < 300:
        url = m.group(0)
    credit = ""
    m2 = re.search(r"사진\s*제공[.\s:]*([^\n]+)", body)
    if m2:
        credit = m2.group(1).strip()
    return {"title": title, "author": "", "url": url, "credit": credit, "body": body}


# ---------- Claude 호출 ----------
SYSTEM = """당신은 archiveKD의 콘텐츠 디지털 배포 에디터다.

[절대 규칙]
1. 원문 기사에 없는 사실, 수치, 발언을 만들지 않는다.
2. 따옴표 안 인물 발언은 원문 그대로 쓰거나, 줄일 때만 앞뒤를 자른다. 단어를 바꾸지 않는다.
3. 스포일러(결말, 반전)는 쓰지 않는다.
4. 제작 브랜드는 'archiveKD'로 표기하고 원문 출처는 별도로 유지한다.
5. 과장 표현(충격, 경악, 소름, 역대급)을 쓰지 않는다.
6. 이모지는 채널 규격에서 허용한 경우에만 쓴다.

[문체] 짧고 구체적인 문장. 형용사보다 장면과 숫자.
[출력] 지정한 JSON 객체 하나만 출력한다. 설명, 마크다운, 코드펜스를 붙이지 않는다."""

CHANNELS = """[채널 규격]
A. telegram: title(이모지 1개 허용, 30자 이내), lines 3개(각 50자 이내, 1개는 인물 발언 인용).
B. kakao: text(대화체 2~3문장, 이모지 1개 허용), question(독자 질문 1개). 합계 150자 이내.
C. instagram: cards 5장. 1장=표지(headline 15자 이내 인용구, body 인물명/작품명). 2~4장=headline 15자 이내 + body 60자 이내. 5장=마무리 인용 + body "전문은 프로필 링크에서". caption 300자 이내(해시태그 제외), hashtags 5~8개(# 포함, 인물명·작품명·archiveKD 필수).
D. shorts: hook(첫 2초 문장), narration(18~22초, 110~130자), title(40자 이내), cuts 5~7개(sec는 "0-2" 형식, visual=화면 지시, subtitle=12자 이내).
E. english: title(120자 이내, 사실형), body(3~4문장, 해외 독자가 모르는 고유명사는 짧게 풀이, 끝에 "Full interview (Korean): [link]").
F. 판단: global_fit(1~5), shorts_fit(1~5), risk_flags(사람이 확인할 이유 목록. 사진 저작권, 미확인 사실, 민감 주제 등).

형식:
{"telegram":{"title":"","lines":["","",""]},"kakao":{"text":"","question":""},"instagram":{"cards":[{"no":1,"headline":"","body":""}],"caption":"","hashtags":[]},"shorts":{"hook":"","narration":"","title":"","cuts":[{"sec":"0-2","visual":"","subtitle":""}]},"english":{"title":"","body":""},"global_fit":0,"shorts_fit":0,"risk_flags":[]}"""

VERIFY_PROMPT = """[원문]과 [산출물 JSON]을 비교하라. 다음을 확인하고 JSON 하나만 답하라.
1. 원문에 없는 사실·수치가 있는가 (해당 문장 인용)
2. 따옴표 안 발언이 원문과 다른가
3. 결말·반전 노출이 있는가
4. 글자 수 규격을 크게 넘었는가
형식: {"pass": true, "issues": [{"channel": "", "problem": "", "quote": ""}]}"""


def claude(client, system, user, max_tokens=4000):
    msg = client.messages.create(model=MODEL, max_tokens=max_tokens, temperature=0.3,
                                 system=system, messages=[{"role": "user", "content": user}])
    text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1])


def convert(client, art):
    user = (f"[기사 메타]\n제목: {art['title']}\n기자: {art['author'] or '(없음)'}\n"
            f"URL: {art['url'] or '(없음)'}\n사진 출처: {art['credit'] or '(없음)'}\n\n"
            f"[기사 본문]\n{art['body']}\n\n{CHANNELS}")
    try:
        return claude(client, SYSTEM, user)
    except json.JSONDecodeError:
        log("  JSON 형식 오류, 한 번 더 시도")
        return claude(client, SYSTEM, user)


def verify(client, art, result):
    user = f"[원문]\n{art['body']}\n\n[산출물 JSON]\n{json.dumps(result, ensure_ascii=False)}"
    return claude(client, "JSON 하나만 출력한다. 설명 금지.", user + "\n\n" + VERIFY_PROMPT, 1500)


# ---------- 저장 ----------
def safe_name(s):
    s = re.sub(r"[\\/:*?\"<>|\n\r\t]", " ", s).strip()
    return re.sub(r"\s+", " ", s)[:40] or "untitled"


def link_of(art):
    return art["url"] or "[링크]"


def telegram_text(r, art):
    t = r.get("telegram", {})
    lines = "\n".join("• " + x for x in t.get("lines", []))
    return f"{t.get('title', '')}\n\n{lines}\n\n👉 전문 보기: {link_of(art)}"


def save(art, r, check):
    folder = OUT / f"{datetime.now():%Y%m%d_%H%M}_{safe_name(art['title'])}"
    folder.mkdir(parents=True, exist_ok=True)
    (folder / "result.json").write_text(json.dumps({"article": {k: v for k, v in art.items() if k not in ('body', 'images', 'local_images')},
                                                    "result": r, "verify": check}, ensure_ascii=False, indent=2),
                                        encoding="utf-8")
    ig, sh, en, kk = r.get("instagram", {}), r.get("shorts", {}), r.get("english", {}), r.get("kakao", {})
    cards = "\n\n".join(f"[{i+1}장]\n{c.get('headline','')}\n{c.get('body','')}" for i, c in enumerate(ig.get("cards", [])))
    cuts = "\n".join(f"| {c.get('sec','')} | {c.get('visual','')} | {c.get('subtitle','')} |" for c in sh.get("cuts", []))
    issues = (check or {}).get("issues") or []
    md = f"""# {art['title']}

원문: {link_of(art)}
쇼츠 적합도 {r.get('shorts_fit')}/5 · 해외 적합도 {r.get('global_fit')}/5

## 사람이 확인할 것
{chr(10).join('- ' + x for x in r.get('risk_flags', [])) or '- 없음'}
{chr(10).join('- [검증] ' + i.get('channel','') + ': ' + i.get('problem','') for i in issues)}

## 텔레그램
{telegram_text(r, art)}

## 카카오 오픈채팅
{kk.get('text','')}

{kk.get('question','')}
{link_of(art)}

## 인스타그램 카드뉴스
{cards}

### 캡션
{ig.get('caption','')}

{' '.join(ig.get('hashtags', []))}

## 쇼츠
제목: {sh.get('title','')}

내레이션: {sh.get('narration','')}

| 시간(초) | 화면 | 자막 |
| --- | --- | --- |
{cuts}

## 영문 (레딧·미디엄)
{en.get('title','')}

{en.get('body','').replace('[link]', link_of(art))}
"""
    (folder / "결과.md").write_text(md, encoding="utf-8")
    return folder


def post_telegram(text):
    if not (TG_TOKEN and TG_CHAT and TG_AUTO):
        return False
    r = requests.post(f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
                      data={"chat_id": TG_CHAT, "text": text, "disable_web_page_preview": "false"}, timeout=20, allow_redirects=False)
    if not r.ok:
        log(f"  텔레그램 게시 실패: {r.text[:200]}")
    return r.ok


# ---------- 처리 ----------
def process(client, kind, ref, seen, label):
    log(f"새 기사: {label}")
    art = load_item(kind, ref)
    if len(art["body"]) < 200:
        log("  본문이 너무 짧아 건너뜀 (200자 미만). 본문을 직접 붙여넣은 txt로 넣어 주세요.")
        return
    r = convert(client, art)
    check = verify(client, art, r) if VERIFY else None
    folder = save(art, r, check)
    log(f"  저장: {folder.name}")
    photos_dir = folder / "photos"
    if art.get("local_images"):
        import shutil
        photos_dir.mkdir(exist_ok=True)
        for k, p in enumerate(art["local_images"]):
            shutil.copy(p, photos_dir / f"{k+1:02d}{Path(p).suffix.lower()}")
        log(f"  사진 {len(art['local_images'])}장 복사")
    elif art.get("images"):
        n = download_images(art["images"], photos_dir, art["url"])
        log(f"  기사 사진 {n}장 내려받음")
    if SHORTS and (r.get("shorts_fit") or 0) >= SHORTS_MIN_FIT:
        try:
            import shorts
            shorts.make_shorts(folder, r, art, SHORTS_CFG)
        except Exception as e:
            log(f"  쇼츠 제작 오류: {str(e)[:300]}")
    elif SHORTS:
        log(f"  쇼츠 적합도 {r.get('shorts_fit')}점 → 쇼츠는 건너뜀 (기준 {SHORTS_MIN_FIT}점)")
    passed = (check is None or check.get("pass", False)) and not (check or {}).get("issues")
    if passed:
        if post_telegram(telegram_text(r, art)):
            log("  텔레그램 게시 완료")
    else:
        log("  검증에서 지적 사항이 있어 텔레그램 자동 게시는 보류. 결과.md 확인")
    seen.add(key_of(ref if kind == "rss" else label + art["body"][:200]))
    if kind in ("file", "dir"):
        Path(ref).rename(DONE / Path(ref).name)


def run_once(client, seen):
    items = from_rss(seen) + from_inbox(seen)
    if not items:
        log("새 기사 없음")
    for kind, ref, label in items:
        try:
            process(client, kind, ref, seen, label)
        except Exception as e:
            log(f"  오류: {e}")
        save_seen(seen)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--url")
    ap.add_argument("--shorts", help="output 안의 기사 폴더를 지정해 쇼츠만 다시 만들기")
    a = ap.parse_args()
    if a.shorts:
        folder = Path(a.shorts)
        if not folder.is_absolute():
            folder = OUT / folder if (OUT / folder).exists() else BASE / folder
        data = json.loads((folder / "result.json").read_text(encoding="utf-8"))
        import shorts
        shorts.make_shorts(folder, data["result"], data["article"], SHORTS_CFG)
        return
    if not API_KEY or API_KEY.startswith("여기에"):
        sys.exit("config.env에 ANTHROPIC_API_KEY를 넣어 주세요.")
    import anthropic
    client = anthropic.Anthropic(api_key=API_KEY)
    seen = load_seen()
    if a.url:
        process(client, "rss", a.url, seen, a.url); save_seen(seen); return
    if a.once:
        run_once(client, seen); return
    log(f"시작. {MINUTES}분마다 확인합니다. 끄려면 이 창을 닫거나 Ctrl+C")
    while True:
        run_once(client, seen)
        time.sleep(MINUTES * 60)


if __name__ == "__main__":
    main()
