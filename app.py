import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Streamlit Cloud 설정에서 정보를 입력해 주세요.")
    st.stop()

@st.cache_resource
def init_clients():
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)
    chat_model = genai.GenerativeModel('gemini-2.0-flash') 
    return supabase_client, chat_model

try:
    supabase, ai_model = init_clients()
except Exception as e:
    st.error(f"시스템 연결 실패: {e}")

def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- [V6-Simple] 하단 네비게이션 1열 고정 및 심플 UI ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# 세션 상태 초기화
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🤖 조치법 검색"

# [CSS 주입] 상단바/하단바 1열 고정 및 겹침 방지 최적화
st.markdown("""
    <style>
    /* 1. 최상단 고정바 */
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 15px 0; text-align: center;
        font-size: 1.1rem; font-weight: 800;
        z-index: 999999; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    
    /* 2. 하단 네비게이션 (모바일 1열 강제 가로 배치) */
    .fixed-footer {
        position: fixed; bottom: 0; left: 0; width: 100%;
        background-color: #ffffff;
        display: flex !important; flex-direction: row !important; /* 가로 배치 강제 */
        justify-content: space-evenly !important; align-items: center !important;
        padding: 10px 5px; border-top: 1px solid #e2e8f0;
        z-index: 999999;
    }
    
    /* 하단 버튼 크기 및 간격 최적화 */
    .fixed-footer .stButton > button {
        width: 30vw !important;
        height: 3.2rem !important;
        font-size: 0.9rem !important;
        border-radius: 12px !important;
        margin: 0 !important;
        background-color: #f8fafc;
        color: #1e293b;
        border: 1px solid #e2e8f0;
    }

    /* 3. 메인 컨텐츠 여백 */
    .main .block-container {
        padding-top: 5rem !important;
        padding-bottom: 7rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* 4. 가이드 문구(Press Enter) 삭제 */
    [data-testid="InputInstructions"] { display: none !important; }

    /* 5. 카드형 UI */
    .result-card {
        background-color: #ffffff; border-radius: 15px;
        padding: 18px; border-left: 6px solid #004a99;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 15px;
    }
    .card-meta { font-size: 0.75rem; color: #7f8c8d; margin-bottom: 5px; }
    .card-title { font-size: 1rem; font-weight: 800; color: #2c3e50; margin-bottom: 8px; }
    .reg-tag { font-size: 0.75rem; color: #004a99; font-weight
