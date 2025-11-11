from flask import Flask, request, render_template_string, send_file, jsonify, abort
import os, time, math, json, re, subprocess, requests, cv2
from dotenv import load_dotenv
from datetime import datetime

# ===== ENV =====
load_dotenv()
app = Flask(__name__)

BASE_URL = os.getenv("SORA_BASE_URL", "https://api.sora.openai.com/v1/videos")
TOKEN    = os.getenv("SORA_TOKEN")
HEADERS  = {"Authorization": f"Bearer {TOKEN}" if TOKEN else "", "Content-Type": "application/json"}

PLAN = os.getenv("PLAN", "PLUS").upper()   # PLUS | PRO
CUT_SEC_OVERRIDE = os.getenv("CUT_SEC")    # 예: "20"
DEFAULT_CUT_SEC  = 10 if PLAN == "PLUS" else 25
FINAL_SCALE      = os.getenv("FINAL_SCALE", "").strip()

def resolve_cut_sec():
    """구독 플랜 기준 컷 길이 계산(오버라이드 우선)."""
    return int(CUT_SEC_OVERRIDE) if CUT_SEC_OVERRIDE else (10 if PLAN == "PLUS" else 25)

# ===== HTML (자동 시나리오 생성: 입력 변경 시 디바운스 호출) =====
HTML = """
<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8" />
<title>SORA 자동 영상 생성기</title>
<style>
*{box-sizing:border-box} body{font-family:system-ui,-apple-system,Segoe UI,Roboto;background:#f7f8fb;margin:0;padding:24px}
.wrap{max-width:980px;margin:0 auto;background:#fff;border-radius:16px;box-shadow:0 10px 30px rgba(0,0,0,.08);padding:28px}
h1{margin:0 0 16px} .grid2{display:grid;grid-template-columns:1fr 1fr;gap:12px} .grid3{display:grid;grid-template-columns:1fr 1fr 1fr;gap:12px}
label{font-weight:600;margin:12px 0 6px;display:block} input,select,textarea{width:100%;padding:10px;border:1px solid #ddd;border-radius:8px}
textarea{min-height:120px} button{margin-top:12px;padding:12px 16px;border:0;border-radius:8px;background:#4f46e5;color:#fff;font-weight:700;cursor:pointer}
.section{margin-top:20px;padding:16px;border:1px solid #eee;border-radius:12px}
.row{display:flex;gap:8px;align-items:center;margin:6px 0} .small{font-size:12px;color:#666} .card{border:1px solid #eee;border-radius:10px;padding:12px;margin-top:8px}
#status{display:none;margin-top:12px;padding:12px;border-radius:8px} .info{background:#e0ecff;color:#1e429f}.success{background:#e8f5e9;color:#1b5e20}.error{background:#ffebee;color:#b71c1c}
#videoResult{display:none;margin-top:16px} .add{background:#10b981} .danger{background:#ef4444}
</style>
</head><body>
<div class="wrap">
  <h1>🎬 SORA 자동 영상 생성기</h1>
  <p class="small">플랜: <b>{{ plan }}</b> · 컷 단위: <b>{{ cut }}</b>초</p>

  <!-- 상단 입력 -->
  <div class="section">
    <div class="grid2">
      <div>
        <label>영상 주제</label>
        <input type="text" id="topic" placeholder="예: 낡은 차를 무시한 직원들, 다음 날 회장님 등장" />
      </div>
      <div>
        <label>총 길이</label>
        <select id="total_length">
          <option value="60">1분</option>
          <option value="180">3분</option>
          <option value="480">8분</option>
        </select>
      </div>
    </div>

    <div class="grid3">
      <div>
        <label>컷 수(비워두면 자동)</label>
        <input type="number" id="cuts" min="1" placeholder="자동 계산됨" />
        <div class="small">총 길이 ÷ 컷 길이(플랜 기반)으로 자동 추정</div>
      </div>
      <div>
        <label>해상도 비율</label>
        <select id="ratio">
          <option value="16:9">16:9</option>
          <option value="9:16" selected>9:16</option>
          <option value="1:1">1:1</option>
        </select>
      </div>
      <div>
        <label>언어</label>
        <select id="lang">
          <option value="ko-KR" selected>ko-KR</option>
          <option value="en-US">en-US</option>
          <option value="ja-JP">ja-JP</option>
        </select>
      </div>
    </div>

    <label>전역 프롬프트</label>
    <textarea id="global_prompt" placeholder="same main characters and lighting. cinematic realism."></textarea>
    <div class="row"><span class="small">입력 변경 시 자동으로 시나리오를 생성하여 아래 영역에 채웁니다.</span></div>
  </div>

  <!-- 자동 생성된 시나리오 -->
  <div class="section" id="scenarioBox" style="display:none;">
    <h3>자동 생성된 시나리오</h3>
    <textarea id="scenario"></textarea>
  </div>

  <!-- 캐릭터 동적 입력 -->
  <div class="section" id="charsSection" style="display:none;">
    <div class="row" style="justify-content:space-between;">
      <h3>캐릭터</h3>
      <button class="add" id="addChar">+ 캐릭터 추가</button>
    </div>
    <div id="chars"></div>
  </div>

  <!-- 오디오 옵션 -->
  <div class="section">
    <h3>오디오 옵션</h3>
    <div class="grid3">
      <div>
        <label>전역 내레이션 음성</label>
        <select id="voice">
          <option value="female_calm" selected>여성 / 부드러운</option>
          <option value="female_warm">여성 / 따뜻한</option>
          <option value="male_deep">남성 / 낮은</option>
          <option value="male_energetic">남성 / 활기찬</option>
        </select>
      </div>
      <div>
        <label>연속성 상속 강도</label>
        <select id="inherit">
          <option value="strong" selected>강하게</option>
          <option value="normal">보통</option>
        </select>
      </div>
      <div>
        <label>배경음악 사용</label>
        <select id="use_bgm">
          <option value="no" selected>사용 안 함</option>
          <option value="yes">사용</option>
        </select>
      </div>
    </div>
    <div class="grid2" id="bgmBox" style="display:none;">
      <div>
        <label>BGM URL (mp3/mp4 등)</label>
        <input type="text" id="bgm_url" placeholder="https://..." />
      </div>
      <div>
        <label>BGM 볼륨(0.0~1.0)</label>
        <input type="number" id="bgm_vol" step="0.1" min="0" max="1" value="0.25" />
      </div>
    </div>
  </div>

  <!-- 생성 버튼 -->
  <div class="section">
    <div class="row">
      <button id="generate">🎥 영상 생성</button>
      <button class="danger" id="reset">초기화</button>
    </div>
    <div id="status"></div>
    <div id="videoResult"></div>
  </div>
</div>

<script>
const statusBox = document.getElementById('status');
const scenarioBox = document.getElementById('scenarioBox');
const scenarioEl  = document.getElementById('scenario');
const charsSection= document.getElementById('charsSection');
const charsEl     = document.getElementById('chars');

function showStatus(msg, cls){ statusBox.textContent=msg; statusBox.className=cls; statusBox.style.display='block'; }

document.getElementById('use_bgm').addEventListener('change', e=>{
  document.getElementById('bgmBox').style.display = e.target.value === 'yes' ? 'grid' : 'none';
});

// 캐릭터 카드
function newCharCard(name="Character", image_url=""){
  const card = document.createElement('div'); card.className='card';
  card.innerHTML = `
    <div class="grid3">
      <div><label>캐릭터 이름</label><input type="text" name="c_name" value="${name}"/></div>
      <div><label>성별</label><select name="c_gender">
        <option value="female" selected>여성</option><option value="male">남성</option></select></div>
      <div><label>음성 톤</label><select name="c_tone">
        <option value="calm" selected>부드러움</option><option value="warm">따뜻함</option>
        <option value="deep">낮음</option><option value="energetic">활기참</option></select></div>
    </div>
    <label>참고 이미지 URL</label><input type="text" name="c_img" placeholder="https://..." value="${image_url}"/>
    <div class="row" style="justify-content:flex-end;"><button class="danger" type="button" onclick="this.closest('.card').remove()">삭제</button></div>`;
  return card;
}

// 자동 시나리오 생성 호출 (디바운스)
let timer=null;
['topic','total_length','cuts','ratio','lang','global_prompt'].forEach(id=>{
  document.getElementById(id).addEventListener('input', ()=>{
    clearTimeout(timer);
    timer = setTimeout(autoScriptCall, 500);
  });
});

async function autoScriptCall(){
  showStatus('시나리오 생성 중...', 'info');
  const fd = new FormData();
  fd.append('topic', document.getElementById('topic').value || '');
  fd.append('total_length', document.getElementById('total_length').value);
  fd.append('cuts', document.getElementById('cuts').value || '');
  fd.append('ratio', document.getElementById('ratio').value);
  fd.append('lang', document.getElementById('lang').value);
  const r = await fetch('/autoscript', {method:'POST', body:fd});
  const data = await r.json();
  if(data.status !== 'success'){ showStatus('오류: '+data.message,'error'); return; }

  // 컷 수 자동 계산 결과가 있으면 UI에 반영
  if(data.cut_count){ document.getElementById('cuts').value = data.cut_count; }

  scenarioEl.value = data.scenario.join('\\n'); scenarioBox.style.display='block';

  charsEl.innerHTML = '';
  (data.characters || []).forEach(c=>{ charsEl.appendChild(newCharCard(c.name, '')); });
  charsSection.style.display = 'block';
  showStatus('시나리오 자동 생성 완료', 'success');
}

// 캐릭터 수동 추가
document.getElementById('addChar').addEventListener('click', ()=>{ charsEl.appendChild(newCharCard()); });

// 초기화
document.getElementById('reset').addEventListener('click', ()=>{
  scenarioBox.style.display='none'; charsSection.style.display='none';
  scenarioEl.value=''; charsEl.innerHTML='';
  document.getElementById('videoResult').style.display='none';
  showStatus('초기화됨', 'info');
});

// 생성
document.getElementById('generate').addEventListener('click', async ()=>{
  showStatus('생성 요청 중...', 'info');

  // 캐릭터 수집
  const cards = Array.from(document.querySelectorAll('#chars .card'));
  const characters = cards.map(card=>{
    const name = card.querySelector('input[name="c_name"]').value.trim() || 'Character';
    const gender= card.querySelector('select[name="c_gender"]').value;
    const tone  = card.querySelector('select[name="c_tone"]').value;
    const img   = card.querySelector('input[name="c_img"]').value.trim();
    const voice_hint = (gender==='female' && tone==='calm') ? 'female_calm' :
                       (gender==='female' && tone==='warm') ? 'female_warm' :
                       (gender==='male'   && tone==='deep') ? 'male_deep'   : 'male_energetic';
    return {name, image_url: img, voice_hint};
  });

  const payload = {
    total_length: parseInt(document.getElementById('total_length').value,10),
    ratio: document.getElementById('ratio').value,
    lang: document.getElementById('lang').value,
    inherit: document.getElementById('inherit').value,
    voice: document.getElementById('voice').value,
    global_prompt: document.getElementById('global_prompt').value || '',
    scenario: (document.getElementById('scenario').value || '').split('\\n').filter(s=>s.trim().length>0),
    characters, use_bgm: document.getElementById('use_bgm').value,
    bgm_url: document.getElementById('bgm_url').value || '',
    bgm_vol: parseFloat(document.getElementById('bgm_vol').value || '0.25')
  };

  const r = await fetch('/generate', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(payload)});
  const data = await r.json();
  if(data.status==='success'){
    const box = document.getElementById('videoResult');
    box.innerHTML = `
      <video controls autoplay style="width:100%;border-radius:8px">
        <source src="/download/${data.filename}" type="video/mp4">
      </video>
      <div class="row"><a href="/download/${data.filename}" download><button>💾 다운로드</button></a></div>`;
    box.style.display='block';
    showStatus('생성 완료', 'success');
  }else{
    showStatus('오류: '+data.message, 'error');
  }
});
</script>
</body></html>
"""

# ===== 워터마크 흐림 =====
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

# ===== Sora 호출 =====
def create_clip(prompt_text: str, ratio: str, cut_sec: int,
                characters: list, global_voice: str, global_lang: str,
                global_prompt: str = "", remix_id=None, ref_url=None, inherit="strong"):
    if not TOKEN:
        abort(500, description="SORA_TOKEN is not set")
    refs = []
    for c in characters:
        if c.get("image_url"):
            refs.append({"type":"image", "url": c["image_url"], "role": c["name"]})
    if ref_url:
        refs.append({"type":"video", "url": ref_url, "role":"previous_context"})
    voice_hints = ", ".join([f"{c['name']}:{c.get('voice_hint','')}" for c in characters if c.get('voice_hint')])
    continuity = "strong continuity" if inherit=="strong" else "keep continuity"
    full_prompt = " ".join([
        (global_prompt or "").strip(),
        continuity,
        "keep same characters, faces, lighting, camera tone, and environment across cuts.",
        f"voices style hints: {voice_hints}." if voice_hints else "",
        prompt_text.strip()
    ]).strip()
    body = {
        "model": "sora-2",  # 환경에 따라 sora-turbo일 수 있음
        "prompt": full_prompt,
        "ratio": ratio,
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

# ===== Routes =====
@app.route("/")
def index():
    return render_template_string(HTML, plan=PLAN, cut=resolve_cut_sec())

@app.route("/autoscript", methods=["POST"])
def autoscript():
    try:
        topic = (request.form.get("topic") or "").strip()
        total_length = int(request.form.get("total_length", "60"))
        ratio = request.form.get("ratio", "9:16")
        lang  = request.form.get("lang", "ko-KR")
        cuts_in = request.form.get("cuts", "").strip()

        cut_sec = resolve_cut_sec()
        cut_count = int(cuts_in) if cuts_in.isdigit() and int(cuts_in)>0 else max(1, math.ceil(total_length / cut_sec))

        if not topic:
            topic = "일상적인 상황에서의 작은 반전"

        # 아주 단순한 자동 시나리오 템플릿
        scenes = [f"Scene {i}: {topic} — maintain same cast and visuals; advance the story logically. Camera subtle motion."
                  for i in range(1, cut_count+1)]

        # 토픽으로부터 러프 캐릭터 추정
        def guess_chars_kor(t):
            names = []
            if re.search(r"할머니|노부인", t): names.append("할머니")
            if re.search(r"회장|사장|대표", t): names.append("회장")
            if re.search(r"직원|점원|알바", t): names += ["직원A", "직원B"]
            if not names: names = ["주인공", "상대역"]
            # 중복 제거
            s, res = set(), []
            for n in names:
                if n not in s: res.append(n); s.add(n)
            return res

        char_names = guess_chars_kor(topic)

        return jsonify({
            "status":"success",
            "scenario": scenes,
            "characters": [{"name": n} for n in char_names],
            "cut_sec": cut_sec,
            "cut_count": cut_count
        })
    except Exception as e:
        return jsonify({"status":"error","message":str(e)}), 500

@app.route("/generate", methods=["POST"])
def generate():
    try:
        data = request.get_json(force=True)
        total_length = int(data.get("total_length", 60))
        ratio   = data.get("ratio", "9:16")
        lang    = data.get("lang", "ko-KR")
        inherit = data.get("inherit", "strong")
        voice   = data.get("voice", "female_calm")
        global_prompt = data.get("global_prompt", "")
        scenario = data.get("scenario") or []
        characters = data.get("characters") or []
        use_bgm = data.get("use_bgm", "no")
        bgm_url = data.get("bgm_url", "")
        bgm_vol = float(data.get("bgm_vol", 0.25))

        cut_sec   = resolve_cut_sec()
        cut_count = max(1, math.ceil(total_length / cut_sec))
        if len(scenario) < cut_count:
            scenario += [scenario[-1] if scenario else "Continue the story."] * (cut_count - len(scenario))
        elif len(scenario) > cut_count:
            scenario = scenario[:cut_count]

        prev_id, prev_url = None, None
        outputs = []

        for i, text in enumerate(scenario, 1):
            vid = create_clip(text, ratio, cut_sec, characters, voice, lang,
                              global_prompt=global_prompt, remix_id=prev_id, ref_url=prev_url, inherit=inherit)
            url = wait_done(vid)

            raw  = f"clip_{i}_raw.mp4"
            done = f"clip_{i}.mp4"
            with requests.get(url, stream=True) as rr:
                rr.raise_for_status()
                with open(raw, "wb") as f:
                    for chunk in rr.iter_content(1<<20):
                        f.write(chunk)
            blur_watermark(raw, done)
            outputs.append(done)
            prev_id, prev_url = vid, url

        # 스티칭
        with open("list.txt", "w", encoding="utf-8") as f:
            for p in outputs:
                f.write(f"file '{p}'\n")

        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        merged = f"merged_{ts}.mp4"
        vf = "format=yuv420p"
        if FINAL_SCALE:
            vf = f"scale={FINAL_SCALE}:flags=lanczos,{vf}"

        subprocess.run([
            "ffmpeg","-y","-f","concat","-safe","0","-i","list.txt",
            "-vf", vf,
            "-c:v","libx264","-preset","fast","-crf","18",
            "-c:a","aac","-b:a","128k",
            merged
        ], check=True)

        # BGM 믹스(선택)
        final_name = merged
        if use_bgm == "yes" and bgm_url:
            bgm_file = f"bgm_{ts}.mp3"
            with requests.get(bgm_url, stream=True) as rbgm:
                rbgm.raise_for_status()
                with open(bgm_file, "wb") as f:
                    for ck in rbgm.iter_content(1<<20):
                        f.write(ck)
            final_name = f"output_final_{ts}.mp4"
            subprocess.run([
                "ffmpeg","-y","-i", merged, "-i", bgm_file,
                "-filter_complex", f"[1:a]volume={bgm_vol}[bgm];[0:a][bgm]amix=inputs=2:duration=longest:dropout_transition=2[aout]",
                "-map","0:v","-map","[aout]",
                "-c:v","copy","-c:a","aac","-b:a","192k", final_name
            ], check=True)

        return jsonify({"status":"success","filename": final_name})
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
