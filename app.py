import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Streamlit Cloud 설정(Settings > Secrets)에서 정보를 입력해 주세요.")
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

# --- [시각적 개선] UI/UX 커스텀 설정 ---
st.set_page_config(
    page_title="K-eco 조치 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# [CSS 주입] 작가님이 지적하신 제목 및 표 폰트 사이즈 조정
st.markdown("""
    <style>
    /* 1. 메인 제목 폰트 크기 및 상단 여백 축소 */
    h1 {
        font-size: 1.6rem !important;
        padding-top: 0rem !important;
        padding-bottom: 0.5rem !important;
        margin-bottom: 0.5rem !important;
    }
    
    /* 2. 캡션 및 부제목 크기 조정 */
    .stCaption {
        font-size: 0.85rem !important;
    }
    
    /* 3. 표(Table) 내부 폰트 크기 및 높이 최적화 */
    [data-testid="stTable"] td, [data-testid="stTable"] th {
        font-size: 0.75rem !important;
        padding: 4px 6px !important;
        line-height: 1.2 !important;
    }
    
    /* 4. 데이터프레임 폰트 크기 조정 */
    [data-testid="stDataFrame"] {
        font-size: 0.75rem !important;
    }

    /* 5. 모바일 버튼 스타일 강화 */
    .stButton>button {
        width: 100%;
        border-radius: 8px;
        font-size: 0.9rem !important;
        background-color: #007BFF;
        color: white;
    }
    
    /* 6. 전체 컨테이너 여백 축소 */
    .main .block-container {
        padding-top: 1.5rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    </style>
    """, unsafe_allow_html=True)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 설정")
mode = st.sidebar.radio("작업 선택", ["🤖 조치법 검색", "📝 사례 등록", "🛠️ 데이터 관리"])
st.sidebar.markdown("---")
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)

# 메인 헤더
st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("성주 님의 노하우를 현장에서 가장 빠르게 확인하세요.")
st.markdown("---")

# --- 기능 1: 조치법 검색 (UI 개선 반영) ---
if mode == "🤖 조치법 검색":
    st.subheader("🔍 현장 상황 입력")
    
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("상황을 짧게 입력하세요", placeholder="예: 발광 박테리아 소리 남")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        with st.spinner("최적의 해결책 추출 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    case_list = []
                    context_data = ""
                    for i, c in enumerate(past_cases):
                        context_data += f"### 사례 {i+1}\n"
                        context_data += f"- 제조사: {c['manufacturer']}\n- 모델명: {c['model_name']}\n- 항목: {c['measurement_item']}\n- 조치: {c['solution']}\n\n"
                        case_list.append(f"{c['manufacturer']} {c['model_name']}")

                    prompt = f"당신은 조성주 님의 지식 조수입니다. 질문에 되묻지 말고 데이터베이스에 기반하여 조치법을 설명하세요.\n\n[데이터]\n{context_data}\n\n[질문]\n{user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    # [개선] 표 높이를 줄이기 위해 작은 폰트가 적용된 테이블
                    with st.expander("📚 참조한 원본 데이터 상세 (요약)"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 유사 사례를 찾지 못했습니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 사례 등록 ---
elif mode == "📝 사례 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        with col1:
            mfr_options = ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]
            selected_mfr = st.selectbox("제조사", mfr_options)
            custom_mfr = st.text_input("제조사 직접 입력 (필요시)")
        with col2:
            model = st.text_input("모델명")
        with col3:
            item_options = ["TOC", "TP", "TN", "조류", "기타", "직접 입력"]
            selected_item = st.selectbox("측정항목", item_options)
            custom_item = st.text_input("측정항목 직접 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        reg_button = st.form_submit_button("✅ 저장")
        
        if reg_button:
            final_mfr = custom_mfr if selected_mfr == "직접 입력" else selected_mfr
            final_item = custom_item if selected_item == "직접 입력" else selected_item
            if final_mfr and model and final_item and iss and sol:
                vec = get_embedding(f"제조사:{final_mfr} 모델:{model} 항목:{final_item} 현상:{iss} 조치:{sol}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": final_mfr, "model_name": model, "measurement_item": final_item,
                    "issue": iss, "solution": sol, "embedding": vec
                }).execute()
                st.success("등록 완료")

# --- 기능 3: 데이터 관리 (가독성 개선) ---
elif mode == "🛠️ 데이터 관리":
    st.subheader("🛠️ 지식 리스트")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution").execute()
    if res.data:
        st.write(f"전체: {len(res.data)}건")
        # 데이터프레임 폰트 및 너비 최적화
        st.dataframe(res.data, use_container_width=True, height=450)
    else:
        st.info("데이터가 없습니다.")
