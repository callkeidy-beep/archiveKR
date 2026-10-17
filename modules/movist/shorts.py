"""
쇼츠 자동 제작 모듈

순서
  1. 컷 구성표(Claude가 만든 것)를 읽는다
  2. 컷마다 배경 영상을 만든다
       - 히그스필드 사용 컷: 보도 사진 → 카메라만 천천히 움직이는 AI 클립
       - 나머지 컷: 사진에 줌인 효과(무료, 컴퓨터에서 처리)
  3. 내레이션 음성(TTS)을 만든다
  4. 자막·로고를 얹고 이어 붙여 1080x1920 MP4로 저장한다
"""
import asyncio, json, math, os, re, subprocess, time
from pathlib import Path

import requests
from PIL import Image, ImageDraw, ImageFont, ImageOps

BASE = Path(__file__).resolve().parent
FONT_DIR = BASE / "fonts"
W, H, FPS = 1080, 1920, 30

FONT_URLS = {
    "head": "https://github.com/google/fonts/raw/main/ofl/blackhansans/BlackHanSans-Regular.ttf",
    "body": "https://github.com/google/fonts/raw/main/ofl/notosanskr/NotoSansKR%5Bwght%5D.ttf",
}
SYSTEM_FONTS = [
    "C:/Windows/Fonts/malgunbd.ttf", "C:/Windows/Fonts/malgun.ttf",
    "/System/Library/Fonts/AppleSDGothicNeo.ttc", "/Library/Fonts/AppleGothic.ttf",
]

# 히그스필드: 인물은 그대로 두고 카메라만 움직이도록 강하게 제한한다
HF_PROMPT = ("Very subtle, slow cinematic camera push-in on this still photograph. "
             "Keep every person exactly as in the photo: same face, same expression, same pose, "
             "no mouth movement, no new actions, no added objects or text. "
             "Only gentle camera motion and soft light.")


def log(msg):
    print(f"    [쇼츠] {msg}", flush=True)


# ---------- 도구 준비 ----------
def ffmpeg_exe():
    import imageio_ffmpeg
    return imageio_ffmpeg.get_ffmpeg_exe()


def run(args):
    p = subprocess.run([ffmpeg_exe(), "-y", "-loglevel", "error"] + args, capture_output=True, text=True)
    if p.returncode != 0:
        raise RuntimeError(p.stderr[-600:])


def media_duration(path):
    p = subprocess.run([ffmpeg_exe(), "-i", str(path)], capture_output=True, text=True)
    m = re.search(r"Duration:\s*(\d+):(\d+):([\d.]+)", p.stderr)
    return int(m.group(1)) * 3600 + int(m.group(2)) * 60 + float(m.group(3)) if m else 0.0


def font_path(kind):
    FONT_DIR.mkdir(exist_ok=True)
    f = FONT_DIR / ("head.ttf" if kind == "head" else "body.ttf")
    if not f.exists():
        try:
            r = requests.get(FONT_URLS[kind], timeout=60)
            r.raise_for_status()
            f.write_bytes(r.content)
        except Exception:
            for s in SYSTEM_FONTS:
                if Path(s).exists():
                    return s
            return None
    return str(f)


def load_font(kind, size, bold=True):
    p = font_path(kind)
    if not p:
        return ImageFont.load_default()
    ft = ImageFont.truetype(p, size)
    if kind == "body":
        try:
            ft.set_variation_by_name("Bold" if bold else "Medium")
        except Exception:
            pass
    return ft


# ---------- 자막·로고 오버레이 ----------
def wrap(draw, text, ft, max_w):
    words, lines, line = str(text or "").split(), [], ""
    for w in words:
        t = (line + " " + w).strip()
        if draw.textlength(t, font=ft) <= max_w:
            line = t
            continue
        if line:
            lines.append(line)
        line = ""
        if draw.textlength(w, font=ft) <= max_w:
            line = w
            continue
        part = ""
        for ch in w:
            if draw.textlength(part + ch, font=ft) > max_w:
                lines.append(part)
                part = ch
            else:
                part += ch
        line = part
    if line:
        lines.append(line)
    return lines


def make_overlay(path, subtitle, credit, accent, is_first, is_last, title=""):
    im = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    # 위·아래 그라데이션 (글씨가 잘 보이게)
    for y in range(320):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(130 * (1 - y / 320))))
    for y in range(900, H):
        d.line([(0, y), (W, y)], fill=(0, 0, 0, int(170 * (y - 900) / (H - 900))))
    # 로고 (쇼츠 상단 UI 아래)
    d.text((72, 150), "archiveKD", font=load_font("head", 60), fill="white")
    # 첫 컷: 영상 제목 띠
    if is_first and title:
        ft = load_font("body", 44)
        lines = wrap(d, title, ft, W - 144)[:2]
        y = 240
        for ln in lines:
            d.text((72, y), ln, font=ft, fill=(255, 255, 255, 235))
            y += 60
    # 자막: 화면 중앙보다 조금 아래 (하단 UI·오른쪽 버튼 피함)
    ft = load_font("head", 92)
    lines = wrap(d, subtitle, ft, W - 220)
    lh = 116
    y0 = 1180 - (len(lines) * lh) // 2
    for k, ln in enumerate(lines):
        tw = d.textlength(ln, font=ft)
        x = (W - tw) / 2
        d.text((x, y0 + k * lh), ln, font=ft, fill="white", stroke_width=7, stroke_fill="black")
    # 강조 막대
    d.rectangle([(W / 2 - 40, y0 - 34), (W / 2 + 40, y0 - 24)], fill=accent)
    if is_last:
        ft2 = load_font("body", 40)
        msg = "전문은 원문 링크에서"
        d.text(((W - d.textlength(msg, font=ft2)) / 2, y0 + len(lines) * lh + 30), msg, font=ft2, fill="white")
    if credit:
        d.text((72, 1560), "사진 " + credit, font=load_font("body", 28, bold=False), fill=(255, 255, 255, 190))
    im.save(path)


# ---------- 배경 영상 ----------
def prep_photo(src, dst):
    """사진을 세로 1620x2880(1.5배)으로 꽉 차게 자른다. 줌 효과 여유분."""
    im = ImageOps.exif_transpose(Image.open(src)).convert("RGB")
    im = ImageOps.fit(im, (1620, 2880), method=Image.LANCZOS, centering=(0.5, 0.35))
    im.save(dst, quality=92)


def blank_photo(dst, accent):
    Image.new("RGB", (1620, 2880), "#14181F").save(dst, quality=92)


def kenburns(photo, overlay, dur, out, k):
    frames = max(1, int(dur * FPS))
    zoom_in = k % 2 == 0
    z = f"min(1+0.12*on/{frames},1.12)" if zoom_in else f"max(1.12-0.12*on/{frames},1.0)"
    vf = (f"[0]zoompan=z='{z}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d=1:s={W}x{H}:fps={FPS}[b];"
          f"[b][1]overlay=0:0,format=yuv420p[v]")
    run(["-loop", "1", "-i", str(photo), "-i", str(overlay), "-filter_complex", vf, "-map", "[v]",
         "-t", f"{dur:.2f}", "-r", str(FPS), "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


def from_clip(clip, overlay, dur, out):
    vf = (f"[0]scale={W}:{H}:force_original_aspect_ratio=increase,crop={W}:{H},fps={FPS}[b];"
          f"[b][1]overlay=0:0,format=yuv420p[v]")
    run(["-stream_loop", "-1", "-i", str(clip), "-i", str(overlay), "-filter_complex", vf, "-map", "[v]",
         "-t", f"{dur:.2f}", "-r", str(FPS), "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "20", str(out)])


# ---------- 히그스필드 ----------
def higgsfield_clip(photo, dur, out, cfg):
    key_id, secret, model = cfg["hf_id"], cfg["hf_secret"], cfg["hf_model"]
    if not (key_id and secret):
        return False
    try:
        os.environ.setdefault("HF_API_KEY", key_id)
        os.environ.setdefault("HF_API_SECRET", secret)
        os.environ.setdefault("HF_KEY", f"{key_id}:{secret}")
        import higgsfield_client
        img = Image.open(photo).convert("RGB")
        image_url = higgsfield_client.upload_image(img, format="jpeg")
    except Exception as e:
        log(f"히그스필드 사진 업로드 실패 → 줌 효과로 대체 ({str(e)[:120]})")
        return False
    headers = {"Authorization": f"Key {key_id}:{secret}", "Content-Type": "application/json",
               "Idempotency-Key": f"movist-{int(time.time()*1000)}"}
    body = {"prompt": HF_PROMPT, "image_url": image_url, "duration": max(2, math.ceil(dur)),
            "resolution": cfg["hf_resolution"], "aspect_ratio": "9:16", "generate_audio": False}
    try:
        r = requests.post(f"https://api.higgsfield.ai/{model}", headers=headers, json=body, timeout=60)
        r.raise_for_status()
        status_url = r.json()["status_url"]
        log("히그스필드 영상 생성 요청됨, 완료 대기 중…")
        t0 = time.time()
        while time.time() - t0 < 600:
            time.sleep(8)
            s = requests.get(status_url, headers=headers, timeout=30).json()
            st = s.get("status")
            if st == "completed":
                url = (s.get("video") or {}).get("url")
                Path(out).write_bytes(requests.get(url, timeout=120).content)
                log("히그스필드 클립 받음")
                return True
            if st in ("failed", "nsfw", "cancelled", "canceled"):
                log(f"히그스필드 생성 실패({st}) → 줌 효과로 대체")
                return False
        log("히그스필드 시간 초과 → 줌 효과로 대체")
    except Exception as e:
        log(f"히그스필드 오류 → 줌 효과로 대체 ({str(e)[:160]})")
    return False


# ---------- 음성 ----------
def tts(text, out, cfg):
    if cfg["tts"] == "elevenlabs" and cfg["el_key"]:
        r = requests.post(f"https://api.elevenlabs.io/v1/text-to-speech/{cfg['el_voice']}",
                          headers={"xi-api-key": cfg["el_key"], "Content-Type": "application/json"},
                          json={"text": text, "model_id": "eleven_multilingual_v2"}, timeout=120)
        r.raise_for_status()
        Path(out).write_bytes(r.content)
        return
    import edge_tts
    asyncio.run(edge_tts.Communicate(text, cfg["voice"], rate="+8%").save(str(out)))


# ---------- 전체 조립 ----------
def parse_secs(cuts):
    out = []
    for c in cuts:
        m = re.match(r"\s*([\d.]+)\s*[-~]\s*([\d.]+)", str(c.get("sec", "")))
        out.append(max(1.0, float(m.group(2)) - float(m.group(1))) if m else 3.0)
    return out


def make_shorts(folder, result, article, cfg):
    folder = Path(folder)
    sh = result.get("shorts") or {}
    cuts = [c for c in sh.get("cuts", []) if c]
    if not cuts or not sh.get("narration"):
        log("컷 구성표나 내레이션이 없어 건너뜀")
        return None
    work = folder / "_shorts_work"
    work.mkdir(exist_ok=True)
    photos = sorted([p for p in (folder / "photos").glob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png", ".webp")]) \
        if (folder / "photos").exists() else []
    log(f"사진 {len(photos)}장, 컷 {len(cuts)}개")

    # 1) 음성
    voice = work / "narration.mp3"
    tts(sh["narration"], voice, cfg)
    vdur = media_duration(voice)
    log(f"내레이션 {vdur:.1f}초")

    # 2) 컷 길이를 음성 길이에 맞춤
    secs = parse_secs(cuts)
    total = vdur + 0.8
    secs = [s * total / sum(secs) for s in secs]

    # 3) 컷별 영상
    segs, hf_used = [], 0
    for k, (cut, dur) in enumerate(zip(cuts, secs)):
        ov = work / f"ov{k}.png"
        make_overlay(ov, cut.get("subtitle", ""), article.get("credit", ""), cfg["accent"],
                     k == 0, k == len(cuts) - 1, sh.get("title", ""))
        photo = work / f"p{k}.jpg"
        if photos:
            prep_photo(photos[k % len(photos)], photo)
        else:
            blank_photo(photo, cfg["accent"])
        seg = work / f"seg{k}.mp4"
        use_hf = photos and (cfg["hf_cuts"] == "all" or (cfg["hf_cuts"] == "first" and k == 0))
        done = False
        if use_hf:
            clip = work / f"hf{k}.mp4"
            if higgsfield_clip(photos[k % len(photos)], dur, clip, cfg):
                from_clip(clip, ov, dur, seg)
                done, hf_used = True, hf_used + 1
        if not done:
            kenburns(photo, ov, dur, seg, k)
        segs.append(seg)
        log(f"컷 {k+1}/{len(cuts)} 완료")

    # 4) 이어 붙이기 + 소리
    lst = work / "list.txt"
    lst.write_text("".join(f"file '{s.name}'\n" for s in segs), encoding="utf-8")
    video = work / "video.mp4"
    run(["-f", "concat", "-safe", "0", "-i", str(lst), "-c", "copy", str(video)])
    final = folder / "쇼츠.mp4"
    bgm = BASE / "bgm.mp3"
    if bgm.exists():
        run(["-i", str(video), "-i", str(voice), "-stream_loop", "-1", "-i", str(bgm),
             "-filter_complex", "[1]adelay=300|300[n];[2]volume=0.12[b];[n][b]amix=inputs=2:duration=first:dropout_transition=0[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    else:
        run(["-i", str(video), "-i", str(voice), "-filter_complex", "[1]adelay=300|300[a]",
             "-map", "0:v", "-map", "[a]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", str(final)])
    (folder / "쇼츠_업로드정보.txt").write_text(
        f"제목: {sh.get('title','')}\n\n설명:\n{sh.get('narration','')}\n\n{article.get('url','')}\n\n"
        f"#archiveKD #Shorts\n\n※ AI 생성 클립 사용: {'예 (' + str(hf_used) + '컷)' if hf_used else '아니오'}\n"
        f"   AI 클립을 썼다면 유튜브 업로드 시 '변경되거나 합성된 콘텐츠' 표시를 켜 주세요.\n",
        encoding="utf-8")
    log(f"완성: {final.name}")
    return final
