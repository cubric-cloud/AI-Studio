from flask import Flask, request, render_template_string, send_file
import requests, time, subprocess, os, math, cv2
from dotenv import load_dotenv

# 환경 변수 로드
load_dotenv()

app = Flask(__name__)

BASE_URL = "https://api.sora.openai.com/v1/videos"
TOKEN = os.getenv("SORA_TOKEN")
HEADERS = {"Authorization": f"Bearer {TOKEN}", "Content-Type": "application/json"}

# 이하 Flask + 워터마크 흐림 포함 코드 전체 붙여넣기 (이전 대화 버전과 동일)
