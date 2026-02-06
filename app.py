import streamlit as st
import google.generativeai as genai
from supabase import create_client
from db_services import DBManager
from logic_ai import *

# 모듈 임포트
import ui_search
import ui_admin
import ui_community
import ui_collab # [New] 협업 기능
import ui_inventory # 재고 기능

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
st.set_page_config(page_title="금강수계 AI V264", layout="wide", initial_sidebar_state="collapsed", page_icon="💧")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 4rem !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V264 (통합 관리)</div>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# [메뉴] V264: 탭 메뉴 순서 변경
# 요청 순서: 업무기술 -> 협업 -> 소모품 -> 정도검사 -> 생활정보
# --------------------------------------------------------------------------

# 메인 탭 생성
tab_ai, tab_collab, tab_inventory, tab_check, tab_life = st.tabs([
    "🤖 업무기술 (AI)", 
    "🤝 협업 (일정/연락처)", 
    "📦 소모품 재고", 
    "✅ 정도검사", 
    "🏠 생활정보"
])

# 1. 업무기술 (지식 검색 & 챗봇)
with tab_ai:
    # 기존 업무기술 기능 + 관리자/커뮤니티 기능 통합
    # (탭 내부에서 서브 메뉴로 분기)
    sub_mode = st.radio("기능 선택", ["🔍 통합 지식 검색", "👥 현장 지식 커뮤니티", "🛠️ 데이터/문서 관리"], horizontal=True, label_visibility="collapsed")
    
    if sub_mode == "🔍 통합 지식 검색":
        ui_search.show_search_ui(ai_model, db)
    elif sub_mode == "👥 현장 지식 커뮤니티":
        ui_community.show_community_ui(ai_model, db)
    elif sub_mode == "🛠️ 데이터/문서 관리":
        # 관리 기능 탭 분리
        admin_tab1, admin_tab2, admin_tab3 = st.tabs(["데이터 전체 관리", "문서(매뉴얼) 등록", "지식 등록"])
        with admin_tab1: ui_admin.show_admin_ui(ai_model, db)
        with admin_tab2: ui_admin.show_manual_upload_ui(ai_model, db)
        with admin_tab3: ui_admin.show_knowledge_reg_ui(ai_model, db)

# 2. 협업 (일정/당직/연락처)
with tab_collab:
    ui_collab.show_collab_ui(db)

# 3. 소모품 재고
with tab_inventory:
    if hasattr(ui_inventory, 'show_inventory_ui'):
        ui_inventory.show_inventory_ui(db)
    else:
        st.info("재고 관리 모듈을 불러올 수 없습니다.")

# 4. 정도검사 (Placeholder)
with tab_check:
    st.info("🚧 정도검사 관리 기능은 개발 예정입니다.")

# 5. 생활정보 (Placeholder)
with tab_life:
    st.info("🚧 생활정보(날씨, 뉴스 등) 기능은 개발 예정입니다.")
