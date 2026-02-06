import streamlit as st
import google.generativeai as genai
from supabase import create_client
from db_services import DBManager
from logic_ai import *

# 모듈 임포트
import ui_search
import ui_admin
import ui_community
import ui_collab 
import ui_inventory 

# --------------------------------------------------------------------------
# [설정] 환경 변수 로드
# --------------------------------------------------------------------------
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except FileNotFoundError:
    st.error("secrets.toml 파일을 찾을 수 없습니다.")
    st.stop()

@st.cache_resource
def init_system():
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

# --------------------------------------------------------------------------
# [UI] 공통 레이아웃 설정
# --------------------------------------------------------------------------
st.set_page_config(page_title="금강수계 AI V265", layout="wide", initial_sidebar_state="collapsed", page_icon="💧")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V265 (통합 관리)</div>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# [메뉴] 라우팅 처리 (드롭다운 방식 롤백)
# --------------------------------------------------------------------------
_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    # 요청 순서: 업무기술 -> 협업 -> 소모품 -> 정도검사 -> 생활정보
    # (데이터 관리 등은 맨 뒤로 배치)
    mode = st.selectbox("작업 메뉴 선택", 
                        ["🤖 업무기술 (AI)", 
                         "🤝 협업 (일정/연락처)", 
                         "📦 소모품 재고관리", 
                         "✅ 정도검사 관리", 
                         "🏠 생활정보",
                         "---",
                         "🛠️ 데이터 전체 관리",
                         "📄 문서(매뉴얼) 등록",
                         "📝 지식 등록"], 
                        label_visibility="collapsed")

st.divider()

# --------------------------------------------------------------------------
# [화면] 선택된 메뉴에 따른 렌더링
# --------------------------------------------------------------------------

if mode == "🤖 업무기술 (AI)":
    # 탭으로 내부 기능 분리
    tab1, tab2 = st.tabs(["🔍 통합 지식 검색", "👥 현장 지식 커뮤니티"])
    with tab1: ui_search.show_search_ui(ai_model, db)
    with tab2: ui_community.show_community_ui(ai_model, db)

elif mode == "🤝 협업 (일정/연락처)":
    ui_collab.show_collab_ui(db)

elif mode == "📦 소모품 재고관리":
    if hasattr(ui_inventory, 'show_inventory_ui'):
        ui_inventory.show_inventory_ui(db)
    else:
        st.info("재고 관리 모듈 준비 중")

elif mode == "✅ 정도검사 관리":
    st.info("🚧 정도검사 관리 기능은 개발 예정입니다.")

elif mode == "🏠 생활정보":
    st.info("🚧 생활정보(날씨, 뉴스 등) 기능은 개발 예정입니다.")

# --- 관리자 기능 ---
elif mode == "🛠️ 데이터 전체 관리":
    ui_admin.show_admin_ui(ai_model, db)

elif mode == "📄 문서(매뉴얼) 등록":
    ui_admin.show_manual_upload_ui(ai_model, db)

elif mode == "📝 지식 등록":
    ui_admin.show_knowledge_reg_ui(ai_model, db)
