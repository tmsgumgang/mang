import streamlit as st
import google.generativeai as genai
from supabase import create_client
from db_services import DBManager
from logic_ai import *
import ui_search
import ui_admin

# 환경 변수 로드
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_system():
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

# UI 공통 설정
st.set_page_config(page_title="금강수계 AI V160", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V160 (모듈형)</div>""", unsafe_allow_html=True)

# 메인 메뉴 라우팅
_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("작업 메뉴 선택", ["🔍 통합 지식 검색", "🛠️ 데이터 전체 관리", "📝 지식 등록", "📄 문서(매뉴얼) 등록"], label_visibility="collapsed")

st.divider()

if mode == "🔍 통합 지식 검색":
    ui_search.show_search_ui(ai_model, db)

elif mode == "🛠️ 데이터 전체 관리":
    ui_admin.show_admin_ui(ai_model, db)

elif mode == "📄 문서(매뉴얼) 등록":
    ui_admin.show_manual_upload_ui(ai_model, db)

elif mode == "📝 지식 등록":
    ui_admin.show_knowledge_reg_ui(ai_model, db)
