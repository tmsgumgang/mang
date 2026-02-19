import streamlit as st
from google import genai
from google.genai import types
from supabase import create_client
from db_services import DBManager
import ui_search
import ui_admin
import ui_community
# [NEW] 재고관리 UI 모듈
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

# --------------------------------------------------------------------------
# [핵심] 신형 라이브러리(google-genai) 호환 어댑터
# 설명: 기존 UI 코드들이 ai_model.generate_content() 방식으로 호출해도 
#       신형 라이브러리가 알아듣도록 변환해주는 클래스입니다.
# --------------------------------------------------------------------------
class GeminiAdapter:
    def __init__(self, api_key, model_name='gemini-2.0-flash'):
        self.client = genai.Client(api_key=api_key)
        self.model_name = model_name

    def generate_content(self, prompt, stream=False):
        # 신형 SDK 호출 방식
        # config를 통해 일반 텍스트 모드로 명확히 지정
        response = self.client.models.generate_content(
            model=self.model_name,
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type='text/plain')
        )
        return response

@st.cache_resource
def init_system():
    # 1. 신형 어댑터로 AI 모델 초기화 (구형 configure 제거)
    ai_model = GeminiAdapter(api_key=GEMINI_API_KEY, model_name='gemini-2.0-flash')
    
    # 2. Supabase 클라이언트 초기화
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

# --------------------------------------------------------------------------
# [UI] 공통 레이아웃 설정
# --------------------------------------------------------------------------
st.set_page_config(page_title="금강수계 AI V161", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V161 (통합 관리 시스템)</div>""", unsafe_allow_html=True)

# --------------------------------------------------------------------------
# [메뉴] 라우팅 처리
# --------------------------------------------------------------------------
_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    # [NEW] "📦 소모품 재고관리" 메뉴 포함
    mode = st.selectbox("작업 메뉴 선택", 
                        ["🔍 통합 지식 검색", 
                         "👥 현장 지식 커뮤니티", 
                         "📦 소모품 재고관리", 
                         "🛠️ 데이터 전체 관리", 
                         "📝 지식 등록", 
                         "📄 문서(매뉴얼) 등록"], 
                        label_visibility="collapsed")

st.divider()

if mode == "🔍 통합 지식 검색":
    ui_search.show_search_ui(ai_model, db)

elif mode == "👥 현장 지식 커뮤니티":
    ui_community.show_community_ui(ai_model, db)

elif mode == "📦 소모품 재고관리":
    ui_inventory.show_inventory_ui(db)

elif mode == "🛠️ 데이터 전체 관리":
    ui_admin.show_admin_ui(ai_model, db)

elif mode == "📄 문서(매뉴얼) 등록":
    ui_admin.show_manual_upload_ui(ai_model, db)

elif mode == "📝 지식 등록":
    ui_admin.show_knowledge_reg_ui(ai_model, db)
