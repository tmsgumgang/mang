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

# --- [V6] 하단 네비게이션 1열 배치 및 협업 UI ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# 세션 상태 초기화
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🤖 조치법 검색"

# [CSS 주입] 1열 가로 배치 및 겹침 방지 최적화
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
    
    /* 2. 하단 네비게이션 바 (가로 1열 강제) */
    .fixed-footer {
        position: fixed; bottom: 0; left: 0; width: 100%;
        background-color: #ffffff;
        display: flex !important; flex-direction: row !important; /* 가로 배치 */
        justify-content: space-evenly !important; align-items: center !important;
        padding: 10px 5px; border-top: 1px solid #e2e8f0;
        z-index: 999;
    }
    
    /* 하단 버튼 미세 조정 */
    .fixed-footer .stButton > button {
        width: 30vw !important;
        height: 3rem !important;
        font-size: 0.85rem !important;
        border-radius: 10px !important;
        margin: 0 !important;
    }

    /* 3. 여백 조정 */
    .main .block-container {
        padding-top: 5rem !important;
        padding-bottom: 7rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* 4. 가이드 문구 삭제 */
    [data-testid="InputInstructions"] { display: none !important; }

    /* 5. 카드형 UI 및 등록자 태그 */
    .result-card {
        background-color: #ffffff; border-radius: 15px;
        padding: 18px; border-left: 6px solid #004a99;
        box-shadow: 0 2px 8px rgba(0,0,0,0.1); margin-bottom: 15px;
    }
    .card-meta { font-size: 0.75rem; color: #7f8c8d; margin-bottom: 5px; }
    .card-title { font-size: 1rem; font-weight: 800; color: #2c3e50; margin-bottom: 8px; }
    .reg-info { font-size: 0.75rem; color: #004a99; font-weight: 600; }
    </style>
    
    <div class="fixed-header">🌊 금강수계 수질자동측정망 AI 챗봇</div>
    """, unsafe_allow_html=True)

# --- 하단 네비게이션 (1열 배치) ---
st.markdown('<div class="fixed-footer">', unsafe_allow_html=True)
col_n1, col_n2, col_n3 = st.columns(3)
with col_n1:
    if st.button("🔍 검색", key="nav_s"): st.session_state.page_mode = "🤖 조치법 검색"
with col_n2:
    if st.button("📝 등록", key="nav_r"): st.session_state.page_mode = "📝 사례 등록"
with col_n3:
    if st.button("🛠️ 관리", key="nav_m"): st.session_state.page_mode = "🛠️ 데이터 관리"
st.markdown('</div>', unsafe_allow_html=True)

# 검색 설정
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# 1. 조치법 검색
if mode == "🤖 조치법 검색":
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("상황", label_visibility="collapsed", placeholder="상황 입력 (예: 시마즈 toc 값 상승)")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        # 문구 수정: 우리 파트 동료들의 지식 강조
        with st.spinner("금강수계 동료들의 축적된 노하우를 분석 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                if past_cases:
                    case_context = "\n".join([f"사례: {c['manufacturer']} {c['model_name']} - 등록자: {c.get('registered_by', '공동')} - 조치: {c['solution']}" for c in past_cases])
                    prompt = f"당신은 금강수계 동료들의 지식 조수입니다. 다음 데이터를 바탕으로 질문에 짧고 명확하게 답하세요.\n\n{case_context}\n\n질문: {user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    st.markdown("---")
                    
                    for c in past_cases:
                        reg_user = c.get('registered_by', '공동 지식')
                        st.markdown(f"""
                        <div class="result-card">
                            <div class="card-meta">{c['manufacturer']} | {c['measurement_item']} | <span class="reg-info">👤 {reg_user}</span></div>
                            <div class="card-title">{c['model_name']}</div>
                            <div style="font-size: 0.9rem; color: #34495e;"><b>⚠️ 현상:</b> {c['issue']}</div>
                        </div>
                        """, unsafe_allow_html=True)
                        with st.expander(f"🛠️ {reg_user} 님의 상세 조치 확인"):
                            st.success(f"**해결책:** {c['solution']}")
                            st.caption(f"일치도: {c['similarity']*100:.1f}%")
                else:
                    st.warning("⚠️ 아직 등록되지 않은 사례입니다. 동료들을 위해 지식을 등록해 주세요!")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# 2. 사례 등록
elif mode == "📝 사례 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            if mfr == "직접 입력": mfr = st.text_input("제조사명 입력")
            reg_name = st.text_input("등록자 성명", placeholder="이름을 입력하세요") # 등록자 필드
        with col2:
            model = st.text_input("모델명")
            item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타", "직접 입력"])
            if item == "직접 입력": item = st.text_input("측정항목명 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        
        if st.form_submit_button("✅ 지식 베이스 저장"):
            if mfr and model and item and iss and sol and reg_name:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg_name}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": mfr, "model_name": model, "measurement_item": item,
                    "issue": iss, "solution": sol, "registered_by": reg_name, "embedding": vec
                }).execute()
                st.success(f"🎉 {reg_name} 님의 노하우가 성공적으로 공유되었습니다!")
            else:
                st.warning("⚠️ 모든 항목과 등록자 성명을 입력해 주세요.")

# 3. 데이터 관리
elif mode == "🛠️ 데이터 관리":
    st.subheader("🛠️ 지식 데이터셋")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution, registered_by").execute()
    if res.data:
        st.write(f"현재 총 {len(res.data)}건의 지식이 축적되었습니다.")
        st.dataframe(res.data, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")
