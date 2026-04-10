"""
api_server.py — 측정망 챗봇 FastAPI 서버
Streamlit Cloud의 챗봇 로직을 REST API로 노출시켜 Flutter 앱에서 호출 가능하게 합니다.
"""
import os
import sys
import types
import logging

# ─────────────────────────────────────────────────────────────
# [중요] Streamlit 의존성 제거
# logic_ai.py 등이 @st.cache_data 와 st.error() 를 사용하므로
# 실제 Streamlit 없이 동작할 수 있도록 빈 모듈로 대체합니다.
# ─────────────────────────────────────────────────────────────
import contextlib

_st = types.ModuleType("streamlit")
_st.cache_data = lambda **kwargs: (lambda f: f)   # @st.cache_data → 아무것도 안 하는 데코레이터
_st.cache_resource = lambda **kwargs: (lambda f: f)
_st.error = lambda msg, **kw: logging.error(f"[CHATBOT ERROR] {msg}")
_st.warning = lambda msg, **kw: logging.warning(f"[CHATBOT WARNING] {msg}")
_st.spinner = lambda msg="": contextlib.nullcontext()
_st.session_state = {}
_st.secrets = {}
sys.modules["streamlit"] = _st

# ─────────────────────────────────────────────────────────────
# 이제 로직 파일들을 안전하게 import
# ─────────────────────────────────────────────────────────────
import google.generativeai as genai
from supabase import create_client
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from db_services import DBManager
from logic_ai import generate_3line_summary_stream
from utils_search import perform_unified_search

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# 환경 변수 로드 (Railway에서 설정)
# ─────────────────────────────────────────────────────────────
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")

if not GEMINI_API_KEY or not SUPABASE_URL or not SUPABASE_KEY:
    logger.warning("⚠️ 환경변수 미설정: GEMINI_API_KEY / SUPABASE_URL / SUPABASE_KEY")

# ─────────────────────────────────────────────────────────────
# AI 모델 및 DB 초기화 (앱 시작 시 1회)
# ─────────────────────────────────────────────────────────────
genai.configure(api_key=GEMINI_API_KEY)
ai_model = genai.GenerativeModel("gemini-2.5-flash")
db = DBManager(create_client(SUPABASE_URL, SUPABASE_KEY))

# ─────────────────────────────────────────────────────────────
# FastAPI 앱
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="측정망 챗봇 API", version="1.0.0")

# Flutter 앱에서 호출 가능하도록 CORS 허용
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ─────────────────────────────────────────────────────────────
# 요청/응답 스키마
# ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    query: str          # 사용자 질문
    threshold: float = 0.5   # 검색 정밀도 (0.0~1.0, 기본 0.5)


# ─────────────────────────────────────────────────────────────
# API 엔드포인트
# ─────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """서버 상태 확인용 (Railway health check)"""
    return {"status": "ok", "service": "측정망 챗봇 API"}


@app.post("/chat")
async def chat(request: ChatRequest):
    """
    챗봇 질문 처리 — 스트리밍 응답 반환

    - 4단계 하이브리드 RAG 검색 (Graph + Vector + Metadata + Keyword)
    - Gemini 2.5 Flash로 최종 답변 생성
    - 텍스트 청크를 실시간 스트리밍으로 전달
    """
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    logger.info(f"[CHAT] 질문: {query[:80]}")

    try:
        # RAG 검색 실행
        results, intent, q_vec = perform_unified_search(
            ai_model, db, query, request.threshold
        )
        logger.info(f"[CHAT] 검색 결과: {len(results)}건")
    except Exception as e:
        logger.error(f"[CHAT] 검색 오류: {e}")
        raise HTTPException(status_code=500, detail=f"검색 중 오류가 발생했습니다: {str(e)}")

    # 스트리밍 응답 생성기
    def generate():
        if not results:
            yield "죄송합니다. 관련 정보를 데이터베이스에서 찾지 못했습니다.\n질문을 좀 더 구체적으로 입력해 주십시오.\n예: '시마즈 TOC-4200 E01 에러 조치방법'"
            return
        try:
            for chunk in generate_3line_summary_stream(ai_model, query, results):
                yield chunk
        except Exception as e:
            logger.error(f"[CHAT] 스트리밍 오류: {e}")
            yield f"\n\n[오류] 답변 생성 중 문제가 발생했습니다: {str(e)}"

    return StreamingResponse(
        generate(),
        media_type="text/plain; charset=utf-8",
    )


@app.post("/chat/inventory")
async def chat_inventory(request: ChatRequest):
    """
    소모품 재고 검색 (비스트리밍)
    """
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    try:
        result = db.search_inventory_for_chat(query)
        return {"result": result or "검색 결과가 없습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
