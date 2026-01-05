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

# --- [V5] 하단 네비게이션 및 모바일 최적화 UI ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# 세션 상태 초기화 (페이지 네비게이션용)
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🤖 조치법 검색"

# [CSS 주입] 상단바 고정, 하단바 고정, 겹침 방지
st.markdown("""
    <style>
    /* 1. 고정 상단바 */
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 15px 0; text-align: center;
        font-size: 1.1rem; font-weight: 800;
        z-index: 999; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    
    /* 2. 고정 하단 네비게이션 바 */
    .fixed-footer {
        position: fixed; bottom: 0; left: 0; width: 100%;
        background-color: #ffffff;
        display: flex; justify-content: space-around;
        padding: 10px 0; border-top: 1px solid #e2e8f0;
        z-index: 999;
    }

    /* 3. 여백 조정 */
    .main .block-container {
        padding-top: 5rem !important;
        padding-bottom: 6rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* 4. "Press Enter" 가이드 삭제 */
    [data-testid="InputInstructions"] { display: none !important; }

    /* 5. 카드형 UI */
    .result-card {
        background-color: #ffffff; border-radius: 15px;
        padding: 18px; border-left: 6px solid #004a99;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 15px;
    }
    .card-meta { font-size: 0.8rem; color: #7f8c8d; margin-bottom: 5px; }
    .card-title { font-size: 1rem; font-weight: 800; color: #2c3e50; margin-bottom: 10px; }

    /* 6. 버튼 스타일 */
    .stButton>button {
        width: 100%; border-radius: 12px; height: 3.2rem;
        background-color: #004a99; color: white; border: none;
    }
    </style>
    
    <div class="fixed-header">🌊 금강수계 수질자동측정망 AI 챗봇</div>
    """, unsafe_allow_html=True)

# --- 하단 네비게이션 로직 (버튼 클릭 시 세션 상태 변경) ---
st.markdown('<div class="fixed-footer">', unsafe_allow_html=True)
col_nav1, col_nav2, col_nav3 = st.columns(3)
with col_nav1:
    if st.button("🔍 검색"): st.session_state.page_mode = "🤖 조치법 검색"
with col_nav2:
    if st.button("📝 등록"): st.session_state.page_mode = "📝 사례 등록"
with col_nav3:
    if st.button("🛠️ 관리"): st.session_state.page_mode = "🛠️ 데이터 관리"
st.markdown('</div>', unsafe_allow_html=True)

# 사이드바 설정 (백업용 슬라이더 유지)
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)

# --- 페이지 렌더링 ---
mode = st.session_state.page_mode

# 1. 조치법 검색
if mode == "🤖 조치법 검색":
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("현장 상황", label_visibility="collapsed", placeholder="상황 입력 (예: 시마즈 toc 값 상승)")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        with st.spinner("성주 님의 노하우를 분석 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                if past_cases:
                    case_context = "\n".join([f"사례: {c['manufacturer']} {c['model_name']} - 조치: {c['solution']}" for c in past_cases])
                    prompt = f"당신은 조성주 님의 지식 조수입니다. 다음 데이터를 바탕으로 질문에 짧고 명확하게 답하세요.\n\n{case_context}\n\n질문: {user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    st.markdown("---")
                    st.markdown("### 📚 참조 데이터 (카드)")
                    
                    for c in past_cases:
                        st.markdown(f"""
                        <div class="result-card">
                            <div class="card-meta">{c['manufacturer']} | {c['measurement_item']}</div>
                            <div class="card-title">{c['model_name']}</div>
                            <div style="font-size: 0.9rem; color: #34495e;"><b>⚠️ 현상:</b> {c['issue']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        with st.expander("🛠️ 상세 조치 방법 확인"):
                            st.success(f"**해결책:** {c['solution']}")
                            st.caption(f"일치도: {c['similarity']*100:.1f}%")
                else:
                    st.warning("⚠️ 일치하는 사례를 찾지 못했습니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# 2. 사례 등록
elif mode == "📝 사례 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
        if mfr == "직접 입력": mfr = st.text_input("제조사명 입력")
        model = st.text_input("모델명")
        item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타", "직접 입력"])
        if item == "직접 입력": item = st.text_input("측정항목명 입력")
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        
        if st.form_submit_button("✅ 저장"):
            if mfr and model and item and iss and sol:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": mfr, "model_name": model, "measurement_item": item,
                    "issue": iss, "solution": sol, "embedding": vec
                }).execute()
                st.success("데이터베이스 저장 완료")

# 3. 데이터 관리
elif mode == "🛠️ 데이터 관리":
    st.subheader("🛠️ 지식 리스트")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution").execute()
    if res.data:
        st.write(f"전체: {len(res.data)}건")
        st.dataframe(res.data, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")
