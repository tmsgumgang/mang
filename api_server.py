"""
api_server.py — 측정망 챗봇 FastAPI 서버
Streamlit Cloud의 챗봇 로직을 REST API로 노출시켜 Flutter 앱에서 호출 가능하게 합니다.
"""
import os
import sys
import types
import logging
import contextlib

# ─────────────────────────────────────────────────────────────
# [중요] Streamlit 의존성 제거
# ─────────────────────────────────────────────────────────────
_st = types.ModuleType("streamlit")
_st.cache_data = lambda **kwargs: (lambda f: f)
_st.cache_resource = lambda **kwargs: (lambda f: f)
_st.error = lambda *args, **kw: logging.error(f"[ST_ERROR] {args}")
_st.warning = lambda *args, **kw: logging.warning(f"[ST_WARN] {args}")
_st.spinner = lambda msg="": contextlib.nullcontext()
_st.session_state = {}
_st.secrets = {}
sys.modules["streamlit"] = _st

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# FastAPI 앱 먼저 생성 (초기화 전에 /health 응답 가능하게)
# ─────────────────────────────────────────────────────────────
app = FastAPI(title="측정망 챗봇 API", version="1.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ─────────────────────────────────────────────────────────────
# Lazy 초기화 — 첫 요청 시 1회만 실행
# (앱 시작 시가 아닌 첫 API 호출 때 초기화해서 healthcheck 통과)
# ─────────────────────────────────────────────────────────────
_ai_model = None
_db = None
_initialized = False

def _get_clients():
    global _ai_model, _db, _initialized
    if _initialized:
        return _ai_model, _db

    import google.generativeai as genai
    from supabase import create_client
    from db_services import DBManager

    GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY", "")
    SUPABASE_URL   = os.environ.get("SUPABASE_URL", "")
    SUPABASE_KEY   = os.environ.get("SUPABASE_KEY", "")

    if not GEMINI_API_KEY:
        raise RuntimeError("환경변수 GEMINI_API_KEY 가 설정되지 않았습니다.")
    if not SUPABASE_URL or not SUPABASE_KEY:
        raise RuntimeError("환경변수 SUPABASE_URL / SUPABASE_KEY 가 설정되지 않았습니다.")

    logger.info("AI 모델 및 DB 초기화 중...")
    genai.configure(api_key=GEMINI_API_KEY)
    _ai_model = genai.GenerativeModel("gemini-2.5-flash")
    _db = DBManager(create_client(SUPABASE_URL, SUPABASE_KEY))
    _initialized = True
    logger.info("초기화 완료!")
    return _ai_model, _db


# ─────────────────────────────────────────────────────────────
# 요청 스키마
# ─────────────────────────────────────────────────────────────
class ChatRequest(BaseModel):
    query: str
    threshold: float = 0.5


# ─────────────────────────────────────────────────────────────
# 엔드포인트
# ─────────────────────────────────────────────────────────────

@app.get("/health")
def health_check():
    """Railway healthcheck용 — 항상 즉시 응답"""
    return {"status": "ok", "service": "측정망 챗봇 API"}


@app.post("/chat")
async def chat(request: ChatRequest):
    """챗봇 질문 처리 — 스트리밍 응답"""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")

    try:
        ai_model, db = _get_clients()
    except Exception as e:
        raise HTTPException(status_code=503, detail=f"서버 초기화 오류: {str(e)}")

    logger.info(f"[CHAT] 질문: {query[:80]}")

    try:
        from utils_search import perform_unified_search
        results, intent, q_vec = perform_unified_search(ai_model, db, query, request.threshold)
        logger.info(f"[CHAT] 검색 결과: {len(results)}건")
    except Exception as e:
        logger.error(f"[CHAT] 검색 오류: {e}")
        raise HTTPException(status_code=500, detail=f"검색 오류: {str(e)}")

    def generate():
        if not results:
            yield "죄송합니다. 관련 정보를 찾지 못했습니다.\n질문을 더 구체적으로 입력해 주십시오.\n예: '시마즈 TOC-4200 E01 에러 조치방법'"
            return
        try:
            from logic_ai import generate_3line_summary_stream
            for chunk in generate_3line_summary_stream(ai_model, query, results):
                yield chunk
        except Exception as e:
            logger.error(f"[CHAT] 스트리밍 오류: {e}")
            yield f"\n\n[오류] 답변 생성 중 문제가 발생했습니다: {str(e)}"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@app.post("/chat/inventory")
async def chat_inventory(request: ChatRequest):
    """소모품 재고 검색"""
    query = request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="질문이 비어있습니다.")
    try:
        _, db = _get_clients()
        result = db.search_inventory_for_chat(query)
        return {"result": result or "검색 결과가 없습니다."}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
