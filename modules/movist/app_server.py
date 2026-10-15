"""
무비스트 기사 변환기 — 로컬판 (시험판)

claude.ai 웹판과 같은 화면을 내 컴퓨터에서 띄운다.
- Claude 호출: config.env 의 ANTHROPIC_API_KEY 사용
- 기사 URL → 본문·사진 자동 불러오기
- 보관함·편집국 규칙: data/store.json 에 저장
- 카드뉴스·문서 저장: output/변환기_날짜/ 폴더

실행: python app_server.py  (또는 시작_변환기 파일 더블클릭)
"""
import hashlib, json, mimetypes, re, sys, threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

import movist_auto as core   # 설정·기사 가져오기·사진 내려받기 재사용

BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
DATA = BASE / "data"
TMP = DATA / "tmp"
OUT = BASE / "output"
STORE = DATA / "store.json"
PORT = 3102
for p in (DATA, TMP, OUT):
    p.mkdir(parents=True, exist_ok=True)

_lock = threading.Lock()
_client = None


def client():
    global _client
    if _client is None:
        import anthropic
        _client = anthropic.Anthropic(api_key=core.API_KEY)
    return _client


def parse_json(text):
    text = re.sub(r"^```(?:json)?|```$", "", text.strip(), flags=re.M).strip()
    s, e = text.find("{"), text.rfind("}")
    return json.loads(text[s:e + 1])


def ask_claude(prompt):
    last = None
    for _ in range(2):
        msg = client().messages.create(model=core.MODEL, max_tokens=8000, temperature=0.3,
                                       messages=[{"role": "user", "content": prompt}])
        text = "".join(b.text for b in msg.content if getattr(b, "type", "") == "text")
        try:
            return parse_json(text)
        except Exception as e:
            last = e
    raise ValueError("AI 응답 형식이 올바르지 않습니다")


STORE_KEYS = {"movist_history", "movist_rules"}

def load_store():
    if not STORE.exists():
        return {}
    data = json.loads(STORE.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or any(key not in STORE_KEYS for key in data):
        raise ValueError("invalid_store")
    return data


def allowed_article_url(url):
    return core.allowed_movist_url(url)


def safe(s):
    return re.sub(r'[\\/:*?"<>|\n\r\t]', " ", s).strip()[:80] or "file"


class H(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def send(self, code, body, ctype="application/json; charset=utf-8"):
        if isinstance(body, (dict, list)):
            body = json.dumps(body, ensure_ascii=False).encode("utf-8")
        elif isinstance(body, str):
            body = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def body(self):
        n = int(self.headers.get("Content-Length") or 0)
        if n < 0 or n > 25 * 1024 * 1024:
            raise ValueError("요청 크기 제한 초과")
        return self.rfile.read(n) if n else b""

    # ---------- GET ----------
    def do_GET(self):
        u = urlparse(self.path.replace("/api/movist/", "/api/", 1))
        if u.path.startswith("/movist/fonts/"):
            name = u.path.rsplit("/", 1)[-1]
            if name in ("head.ttf", "body.ttf"):
                return self.send(200, (BASE / "fonts" / name).read_bytes(), "font/ttf")
        if u.path == "/api/health":
            return self.send(200, {"ok": True, "agent": "archiveKR 영화제작실", "ai_configured": bool(core.API_KEY)})
        if u.path in ("/", "/index.html", "/movist", "/movist/"):
            html = (WEB / "index.html").read_text(encoding="utf-8")
            html = html.replace("<head>", '<head>\n<script src="/movist/shim.js"></script>', 1)
            return self.send(200, html, "text/html; charset=utf-8")
        if u.path in ("/shim.js", "/movist/shim.js"):
            return self.send(200, (WEB / "shim.js").read_bytes(), "text/javascript; charset=utf-8")
        if u.path == "/api/store":
            try:
                with _lock:
                    return self.send(200, load_store())
            except (ValueError, OSError):
                return self.send(409, {"error": "보관함을 읽을 수 없습니다. 기존 파일을 보존했습니다."})
        if u.path == "/api/latest":
            try:
                return self.send(200, core.latest_articles())
            except core.requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                return self.send(502, {"error": "MOVIST 최신 기사 목록을 가져오지 못했습니다.", "upstreamStatus": status, "items": []})
            except Exception:
                return self.send(502, {"error": "MOVIST 최신 기사 목록에 연결하지 못했습니다.", "items": []})
        if u.path == "/api/fetch":
            return self.fetch_article(parse_qs(u.query).get("url", [""])[0])
        if u.path.startswith("/api/img/"):
            p = (TMP / unquote(u.path[len("/api/img/"):])).resolve()
            if TMP.resolve() in p.parents and p.exists():
                return self.send(200, p.read_bytes(), mimetypes.guess_type(p.name)[0] or "image/jpeg")
            return self.send(404, {"error": "not_found"})
        return self.send(404, {"error": "not_found"})

    def fetch_article(self, url):
        if not allowed_article_url(url):
            return self.send(400, {"error": "주소가 올바르지 않습니다"})
        try:
            art = core.fetch_article(url)
        except Exception:
            return self.send(502, {"error": "기사를 가져오지 못했습니다."})
        key = hashlib.sha1(url.encode()).hexdigest()[:12]
        folder = TMP / key
        for old in folder.glob("*"):
            old.unlink()
        n = core.download_images(art.get("images") or [], folder, url) if art.get("images") else 0
        imgs = [f"/api/movist/img/{key}/{p.name}" for p in sorted(folder.glob("*.jpg"))][:n]
        return self.send(200, {"title": art["title"], "author": art["author"], "credit": art["credit"],
                               "body": art["body"], "images": imgs, "url": url, "publishedAt": art.get("publishedAt", "")})

    # ---------- POST ----------
    def do_POST(self):
        try:
            return self.handle_post()
        except (ValueError, TypeError, KeyError, UnicodeDecodeError):
            return self.send(400, {"error": "요청 형식이 올바르지 않습니다."})
        except Exception:
            return self.send(500, {"error": "요청을 처리하지 못했습니다."})

    def json_body(self):
        data = json.loads(self.body())
        if not isinstance(data, dict):
            raise ValueError("invalid_json_object")
        return data

    def handle_post(self):
        u = urlparse(self.path.replace("/api/movist/", "/api/", 1))
        if u.path == "/api/cards":
            try:
                from cards import render_card
                from io import BytesIO
                data = self.json_body()
                out = BytesIO()
                background = None
                source_image = data.get("sourceImage")
                if source_image is not None:
                    if not isinstance(source_image, str) or not re.fullmatch(r"/api/movist/img/[a-f0-9]{12}/[A-Za-z0-9_-]+\.(?:jpg|jpeg|png|webp)", source_image):
                        raise ValueError("invalid_source_image")
                    image_path = (TMP / source_image.removeprefix("/api/movist/img/")).resolve()
                    if TMP.resolve() not in image_path.parents or not image_path.is_file():
                        raise ValueError("invalid_source_image")
                    from PIL import Image
                    with Image.open(image_path) as photo:
                        if photo.width * photo.height > 40_000_000:
                            raise ValueError("source_image_too_large")
                        background = photo.convert("RGB")
                render_card(data, background=background).save(out, format="PNG")
                return self.send(200, out.getvalue(), "image/png")
            except (ValueError, TypeError) as exc:
                return self.send(400, {"error": "카드 요청 형식이 올바르지 않습니다."})
        if u.path == "/api/claude":
            if not core.API_KEY or core.API_KEY.startswith("여기에"):
                return self.send(400, {"error": "안전한 환경 설정에서 ANTHROPIC_API_KEY를 등록해 주세요"})
            prompt = self.json_body()["prompt"]
            if not isinstance(prompt, str) or not prompt.strip() or len(prompt) > 100000:
                raise ValueError("invalid_prompt")
            try:
                return self.send(200, {"result": ask_claude(prompt)})
            except Exception as e:
                code = 429 if getattr(e, "status_code", None) == 429 else 502
                return self.send(code, {"error": "AI 변환을 완료하지 못했습니다. 환경 설정과 서비스 상태를 확인해 주세요."})
        if u.path == "/api/store":
            d = self.json_body()
            if d.get("key") not in STORE_KEYS or not isinstance(d.get("value"), str):
                raise ValueError("invalid_store_key")
            with _lock:
                try:
                    store = load_store()
                except (ValueError, OSError):
                    return self.send(409, {"error": "보관함을 읽을 수 없습니다. 기존 파일을 보존했습니다."})
                store[d["key"]] = d["value"]
                temporary = STORE.with_suffix(".json.tmp")
                temporary.write_text(json.dumps(store, ensure_ascii=False), encoding="utf-8")
                temporary.replace(STORE)
            return self.send(200, {"ok": True})
        if u.path == "/api/save":
            name = safe(parse_qs(u.query).get("filename", ["file"])[0])
            folder = OUT / f"변환기_{datetime.now():%Y%m%d}"
            folder.mkdir(parents=True, exist_ok=True)
            p = folder / name
            if p.exists():
                p = folder / f"{p.stem}_{datetime.now():%H%M%S}{p.suffix}"
            p.write_bytes(self.body())
            return self.send(200, {"path": str(p.relative_to(BASE))})
        return self.send(404, {"error": "not_found"})


def main():
    try:
        srv = ThreadingHTTPServer(("127.0.0.1", PORT), H)
    except OSError:
        print(f"영화제작실 서버를 시작하지 못했습니다. 포트 {PORT} 상태를 확인해 주세요.", file=sys.stderr)
        raise SystemExit(1)
    url = f"http://127.0.0.1:{PORT}"
    print(f"무비스트 기사 변환기(로컬판) 실행 중: {url}")
    print("이 창을 닫으면 변환기도 꺼집니다.")
    if not core.API_KEY or core.API_KEY.startswith("여기에"):
        print("※ AI 변환은 안전한 환경 설정에서 ANTHROPIC_API_KEY 등록 후 사용할 수 있습니다.")
    # Browser launch omitted for cloud operation.
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
