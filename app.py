from flask import Flask, request, render_template_string, send_file, jsonify, abort
import os, time, math, json, subprocess, requests, cv2
from dotenv import load_dotenv
from datetime import datetime

# ===== 0) ENV 로드 =====
load_dotenv()
app = Flask(__name__)

# Sora API 설정
BASE_URL = os.getenv("SORA_BASE_URL", "https://api.sora.openai.com/v1/videos")
TOKEN    = os.getenv("SORA_TOKEN")
HEADERS  = {"Authorization": f"Bearer {TOKEN}" if TOKEN else "", "Content-Type": "application/json"}

# 구독 플랜 및 컷 길이
PLAN = os.getenv("PLAN", "PLUS").upper()  # PLUS or PRO
CUT_SEC_OVERRIDE = os.getenv("CUT_SEC")   # 예: "20" → 강제 20초 분할
DEFAULT_CUT_SEC  = 10 if PLAN == "PLUS" else 25

# 최종 리사이즈(선택). 예: FINAL_SCALE=1920:1080
FINAL_SCALE = os.getenv("FINAL_SCALE", "").strip()

# ===== 1) UI =====
HTML_TEMPLATE = """
<!DOCTYPE html>
<html lang="ko">
<head>
  <meta charset="UTF-8" />
  <title>SORA 자동 영상 생성기</title>
  <style>
    *{box-sizing:border-box} body{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#f7f8fb;margin:0;padding:24px}
    .wrap{max-width:880px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:28px}
    h1{margin:0 0 16px} .grid{display:grid;grid-template-columns:1fr 1fr;gap:12px}
    label{font-weight:600;margin:12px 0 6px;display:block} input,select,textarea{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px}
    textarea{min-height:120px} button{margin-top:16px;width:100%;padding:14px;border:0;border-radius:8px;background:#4f46e5;color:#fff;font-weight:700;cursor:pointer}
    #status{display:none;margin-top:12px;padding:12px;border-radius:8px}
    .info{background:#e0ecff;color:#1e429f}.success{background:#e8f5e9;color:#1b5e20}.error{background:#ffebee;color:#b71c1c}
    #videoResult{display:none;margin-top:16px}
  </style>
</head>
<body>
  <div class="wrap">
    <h1>🎬 SORA 자동 영상 생성기</h1>
    <p>플랜: <b>{{ plan }}</b> · 컷 단위: <b>{{ cut }}</b>초</p>

    <form id="form">
      <label>총 길이</label>
      <select name="total_length">
        <option value="60">1분</option>
        <option value="180">3분</option>
        <option value="480">8분</option>
      </select>

      <div class="grid">
        <div>
          <label>해상도 비율</label>
          <select name="ratio">
            <option value="16:9">16:9</option>
            <option value="9:16" selected>9:16</option>
            <option value="1:1">1:1</option>
          </select>
        </div>
        <div>
          <label>언어</label>
          <select name="lang">
            <option value="ko-KR" selected>ko-KR</option>
            <option value="en-US">en-US</option>
            <option value="ja-JP">ja-JP</option>
          </select>
        </div>
      </div>

      <div class="grid">
        <div>
          <label>캐릭터 이름(단일)</label>
          <input type="text" name="character" placeholder="예: grandmother" />
        </div>
        <div>
          <label>캐릭터 참조 이미지 URL(단일)</label>
          <input type="text" name="char_url" placeholder="https://cdn.example.com/face.jpg" />
        </div>
      </div>

      <label>캐릭터 설정(JSON) - 다중 캐릭터 지원</label>
      <textarea name="characters_json" placeholder='[
  {"role":"grandmother","image_url":"https://.../grandma.jpg","voice":"female_calm","language":"ko-KR"},
  {"role":"employee1","image_url":"https://.../emp1.jpg"}
]'></textarea>

      <div class="grid">
        <div>
          <label>전역 음성 프리셋</label>
          <select name="voice">
            <option value="female_calm" selected>여성 / 부드러운</option>
            <option value="female_warm">여성 / 따뜻한</option>
            <option value="male_deep">남성 / 낮은</option>
            <option value="male_energetic">남성 / 활기찬</option>
          </select>
        </div>
        <div>
          <label>연속성 상속 강도</label>
          <select name="inherit">
            <option value="strong" selected>강하게</option>
            <option value="normal">보통</option>
          </select>
        </div>
      </div>

      <label>시나리오 (줄바꿈으로 장면 구분, 비워두면 자동 생성)</label>
      <textarea name="scenario" placeholder="장면1...\n장면2...\n장면3..."></textarea>

      <label>전역 프롬프트(모든 컷에 공통 적용)</label>
      <textarea name="global_prompt" placeholder="same main characters and lighting. cinematic realism."></textarea>

      <button type="submit">🎥 생성 시작</button>
    </form>

    <div id="status"></div>
    <div id="videoResult"></div>
  </div>

  <script>
    const form = document.getElementById('form');
    const status = document.getElementById('status');
    const video = document.getElementById('videoResult');

    function show(msg, cls){ status.textContent=msg; status.className=cls; status.style.display='block'; }

    form.addEventListener('submit', async (e)=>{
      e.preventDefault();
      show('생성 요청 중...', 'info'); video.style.display='none';

      const fd = new FormData(form);
      const r = await fetch('/generate', { method:'POST', body:fd });
      let data;
      try{ data = await r.json(); }catch(e){ show('응답 파싱 실패', 'error'); return; }

      if(data.status === 'success'){
        show('생성 완료', 'success');
        video.innerHTML = `
          <video controls autoplay style="width:100%;border-radius:8px">
            <source src="/download/${data.filename}" type="video/mp4">
          </video>
          <div style="margin-top:8px">
            <a href="/download/${data.filename}" download><button>💾 다운로드</button></a>
          </div>`;
        video.style.display='block';
      }else{
        show('오류: ' + data.message, 'error');
      }
    });
  </script>
</body>
</html>
"""

# ===== 2) 워터마크 흐림 (우하단 비율 영역만) =====
def blur_watermark(input_path: str, output_path: str):
    cap = cv2.VideoCapture(input_path)
    ret, frame = cap.read()
    cap.release()
    if not ret:
        raise RuntimeError(f"비디오 읽기 실패: {input_path}")

    h, w = frame.shape[:2]
    wm_x1, wm_y1 = int(w * 0.70), int(h * 0.85)
    wm_x2, wm_y2 = int(w * 0.98), int(h * 0.98)

    subprocess.run([
        "ffmpeg", "-y", "-i", input_path,
        "-filter_complex",
        f"[0:v]crop={wm_x2-wm_x1}:{wm_y2-wm_y1}:{wm_x1}:{wm_y1},boxblur=20[wm];"
        f"[0:v][wm]overlay={wm_x1}:{wm_y1}:enable='between(t,0,1e9)'",
        "-c:a", "copy", output_path
    ], check=True)

# ===== 3) Sora 호출 유틸 =====
def create_clip(prompt_text: str, ratio: str, cut_sec: int,
                characters: list, global_voice: str, global_lang: str,
                global_prompt: str = "", remix_id=None, ref_url=None, inherit="strong"):
    if not TOKEN:
        abort(500, description="SORA_TOKEN is not set")

    # 참조 입력: 다중 캐릭터 이미지 + 직전 영상
    refs = []
    for c in characters:
        refs.append({"type":"image", "url": c["image_url"], "role": c["role"]})
    if ref_url:
        refs.append({"type":"video", "url": ref_url, "role":"previous_context"})

    continuity = "strong continuity" if inherit == "strong" else "keep continuity"
    full_prompt = " ".join([
        (global_prompt or "").strip(),
        continuity,
        "same characters and lighting and camera tone.",
        prompt_text.strip()
    ]).strip()

    body = {
        "model": "sora-2",  # 테넌트에 따라 sora-turbo일 수 있음
        "prompt": full_prompt,
        "ratio": ratio,                    # 16:9 | 9:16 | 1:1
        "duration_sec": cut_sec,
        "remix_id": remix_id,
        "reference_inputs": refs or None,
        "audio_config": {"voice": global_voice, "language": global_lang}
    }
    r = requests.post(BASE_URL, headers=HEADERS, json=body, timeout=60)
    if r.status_code >= 400:
        abort(r.status_code, description=r.text)
    return r.json()["id"]

def wait_done(video_id: str):
    if not TOKEN:
        abort(500, description="SORA_TOKEN is not set")
    status_url = f"{BASE_URL}/{video_id}"
    while True:
        r = requests.get(status_url, headers=HEADERS, timeout=60)
        if r.status_code >= 400:
            abort(r.status_code, description=r.text)
        j = r.json()
        st = j.get("status")
        if st == "completed":
            return j.get("download_url") or j.get("output_url")
        if st == "failed":
            abort(500, description=f"Generation failed: {j}")
        time.sleep(4)

# ===== 4) 라우트 =====
@app.route("/")
def index():
    cut_sec = int(CUT_SEC_OVERRIDE) if CUT_SEC_OVERRIDE else DEFAULT_CUT_SEC
    return render_template_string(HTML_TEMPLATE, plan=PLAN, cut=cut_sec)

@app.route("/generate", methods=["POST"])
def generate_video():
    try:
        # 기본 입력
        total_len = int(request.form.get("total_length", "60"))
        ratio     = request.form.get("ratio", "9:16")
        lang      = request.form.get("lang", "ko-KR")
        voice     = request.form.get("voice", "female_calm")
        inherit   = request.form.get("inherit", "strong")
        scenario  = (request.form.get("scenario") or "").strip()
        global_prompt = (request.form.get("global_prompt") or "").strip()

        # 단일 캐릭터(Fallback)
        single_role = (request.form.get("character") or "").strip() or "main_character"
        single_url  = (request.form.get("char_url") or "").strip()

        # 다중 캐릭터(JSON)
        characters = []
        chars_raw = (request.form.get("characters_json") or "").strip()
        if chars_raw:
            try:
                arr = json.loads(chars_raw)
                for x in arr:
                    role = (x.get("role") or "character").strip()
                    img  = (x.get("image_url") or "").strip()
                    if img:
                        characters.append({"role": role, "image_url": img})
            except Exception as e:
                return jsonify({"status":"error","message":f"characters_json 파싱 오류: {e}"}), 400

        # 단일 URL이 있고 다중 캐릭터가 없으면 fallback 추가
        if single_url and not characters:
            characters.append({"role": single_role, "image_url": single_url})

        # 컷 길이/개수
        cut_sec   = int(CUT_SEC_OVERRIDE) if CUT_SEC_OVERRIDE else DEFAULT_CUT_SEC
        cut_count = max(1, math.ceil(total_len / cut_sec))

        # 장면 리스트 구성
        if scenario:
            scenes = [s.strip() for s in scenario.splitlines() if s.strip()]
        else:
            scenes = [f"Scene {i}: continue action with same characters, lighting, and camera movement."
                      for i in range(1, cut_count+1)]
        if len(scenes) < cut_count:
            scenes += [scenes[-1]] * (cut_count - len(scenes))
        elif len(scenes) > cut_count:
            scenes = scenes[:cut_count]

        prev_id, prev_url = None, None
        out_paths = []

        # 생성 루프
        for i, text in enumerate(scenes, 1):
            clip_id = create_clip(
                prompt_text=text, ratio=ratio, cut_sec=cut_sec,
                characters=characters, global_voice=voice, global_lang=lang,
                global_prompt=global_prompt, remix_id=prev_id, ref_url=prev_url, inherit=inherit
            )
            file_url = wait_done(clip_id)

            raw = f"clip_{i}_raw.mp4"
            with requests.get(file_url, stream=True) as rr:
                rr.raise_for_status()
                with open(raw, "wb") as f:
                    for chunk in rr.iter_content(1<<20):
                        f.write(chunk)

            done = f"clip_{i}.mp4"
            blur_watermark(raw, done)
            out_paths.append(done)

            prev_id, prev_url = clip_id, file_url

        # 스티칭
        with open("list.txt", "w", encoding="utf-8") as f:
            for p in out_paths:
                f.write(f"file '{p}'\n")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        final_name = f"output_final_{ts}.mp4"

        vf = "format=yuv420p"
        if FINAL_SCALE:
            vf = f"scale={FINAL_SCALE}:flags=lanczos,{vf}"

        subprocess.run([
            "ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", "list.txt",
            "-vf", vf,
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-c:a", "aac", "-b:a", "128k",
            final_name
        ], check=True)

        return jsonify({"status":"success", "filename": final_name})

    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/download/<filename>")
def download_file(filename):
    try:
        return send_file(filename, as_attachment=True)
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 404

if __name__ == "__main__":
    port = int(os.getenv("PORT", "8080"))
    app.run(host="0.0.0.0", port=port, debug=True)
