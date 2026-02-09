import streamlit as st
import google.generativeai as genai
from supabase import create_client
from db_services import DBManager
import ui_search
import ui_admin
import ui_community
import ui_inventory
import ui_collab  # [NEW] 협업(캘린더/연락처) UI 모듈

# --------------------------------------------------------------------------
# [UI] 공통 레이아웃 설정 (반드시 맨 처음에 위치해야 함)
# --------------------------------------------------------------------------
st.set_page_config(page_title="금강수계 AI V161", layout="wide", initial_sidebar_state="collapsed")

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
    """
    시스템 초기화: AI 모델 및 DB 연결
    DBManager는 [검색 지능 + 커뮤니티 + 재고 + 협업]이 모두 통합된 객체입니다.
    """
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

# --------------------------------------------------------------------------
# [Header] 상단 고정 헤더
# --------------------------------------------------------------------------
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V161 (통합 관리 시스템)</div>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# [메뉴] 라우팅 처리
# --------------------------------------------------------------------------
_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    # [UPDATE] 메뉴 구조 재정립 (협업 공간 추가)
    mode = st.selectbox("작업 메뉴 선택", 
                        ["🔍 통합 지식 검색", 
                         "👥 현장 지식 커뮤니티", 
                         "🤝 협업 공간 (Collab)",  # [NEW] 캘린더/연락처
                         "📦 소모품 재고관리", 
                         "🛠️ 데이터 전체 관리", 
                         "📝 지식 등록", 
                         "📄 문서(매뉴얼) 등록"], 
                        label_visibility="collapsed")

st.divider()

# --------------------------------------------------------------------------
# [기능 연결] 각 모듈별 UI 호출
# --------------------------------------------------------------------------
if mode == "🔍 통합 지식 검색":
    # utils_search V313 (구원투수 로직 포함) 적용 UI
    ui_search.show_search_ui(ai_model, db)

elif mode == "👥 현장 지식 커뮤니티":
    # 질문/답변 게시판 (db_collab의 Community 기능 사용)
    ui_community.show_community_ui(ai_model, db)

elif mode == "🤝 협업 공간 (Collab)":
    # [NEW] 캘린더, 일정, 연락처 관리 (db_collab의 Schedule/Contact 기능 사용)
    ui_collab.show_collab_ui(db)

elif mode == "📦 소모품 재고관리":
    # 재고 입출고 및 현황 (db_collab의 Inventory 기능 사용)
    ui_inventory.show_inventory_ui(db)

elif mode == "🛠️ 데이터 전체 관리":
    # 관리자 기능 (그래프 관리, 데이터 라벨링 등)
    ui_admin.show_admin_ui(ai_model, db)

elif mode == "📄 문서(매뉴얼) 등록":
    # PDF 업로드 및 학습
    if hasattr(ui_admin, 'show_pdf_reg_ui'):
        ui_admin.show_pdf_reg_ui(ai_model, db)
    elif hasattr(ui_admin, 'show_manual_upload_ui'):
        ui_admin.show_manual_upload_ui(ai_model, db)
    else:
        st.error("문서 등록 UI 함수를 찾을 수 없습니다.")

elif mode == "📝 지식 등록":
    # 텍스트 지식 직접 등록
    ui_admin.show_knowledge_reg_ui(ai_model, db)
