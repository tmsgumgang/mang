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

# --- [V3] 지능형 UI/UX 커스텀 설정 ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# [CSS 주입] 상단바, 카드형 UI, 겹침 방지 최적화
st.markdown("""
    <style>
    /* 1. 상단바(Header Bar) 구현 */
    .top-bar {
        position: fixed;
        top: 0;
        left: 0;
        width: 100%;
        background-color: #1E3A8A; /* 금강의 깊은 물색 */
        color: white;
        padding: 12px 16px;
        text-align: center;
        font-size: 1.1rem;
        font-weight: 700;
        z-index: 1000;
        box-shadow: 0 2px 4px rgba(0,0,0,0.1);
    }
    
    /* 2. 메인 컨텐츠 상단 여백 (상단바 공간 확보) */
    .main .block-container {
        padding-top: 4rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }

    /* 3. 텍스트 겹침 방지 (Press Enter 안내 숨김) */
    [data-testid="InputInstructions"] {
        display: none !important;
    }

    /* 4. 카드형 결과 UI */
    .result-card {
        background-color: #f8fafc;
        border-radius: 12px;
        padding: 15px;
        border: 1px solid #e2e8f0;
        margin-bottom: 10px;
    }
    
    .card-header {
        font-size: 0.85rem;
        color: #64748b;
        margin-bottom: 4px;
    }
    
    .card-title {
        font-size: 1rem;
        font-weight: 700;
        color: #1e293b;
    }

    /* 5. 버튼 스타일 유지 */
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        font-size: 0.95rem !important;
        background-color: #2563eb;
        color: white;
        border: none;
    }

    /* 6. 가로 구분선 스타일 */
    hr {
        margin: 1rem 0 !important;
    }
    </style>
    
    <div class="top-bar">🌊 금강수계 수질자동측정망 AI 챗봇</div>
    """, unsafe_allow_html=True)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 설정")
mode = st.sidebar.radio("작업 선택", ["🤖 조치법 검색", "📝 사례 등록", "🛠️ 데이터 관리"])
st.sidebar.markdown("---")
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)

# --- 기능 1: 조치법 검색 (카드형 UI로 전면 개편) ---
if mode == "🤖 조치법 검색":
    st.subheader("🔍 현장 상황 입력")
    
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("상황을 짧게 입력하세요", label_visibility="collapsed", placeholder="상황 입력 (예: HATP TP mv 0)")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        with st.spinner("최적의 노하우 분석 중..."):
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
                        context_data += f"### 사례 {i+1}\n- 제조사: {c['manufacturer']}\n- 모델명: {c['model_name']}\n- 항목: {c['measurement_item']}\n- 조치: {c['solution']}\n\n"
                        case_list.append(f"{c['manufacturer']} {c['model_name']}")

                    prompt = f"당신은 조성주 님의 지식 조수입니다. 질문에 되묻지 말고 데이터베이스에 기반하여 조치법을 설명하세요.\n\n[데이터]\n{context_data}\n\n[질문]\n{user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    st.markdown("---")
                    st.markdown("### 📚 참조 데이터 상세")
                    
                    # [V3 개선] 무너지는 표 대신 카드형 + 익스펜더 조합
                    for c in past_cases:
                        with st.container():
                            st.markdown(f"""
                            <div class="result-card">
                                <div class="card-header">{c['manufacturer']} | {c['measurement_item']}</div>
                                <div class="card-title">{c['model_name']}</div>
                                <div style="font-size: 0.85rem; color: #475569; margin-top:5px;"><b>현상:</b> {c['issue']}</div>
                            </div>
                            """, unsafe_allow_html=True)
                            with st.expander("🛠️ 상세 조치 방법 확인"):
                                st.write(c['solution'])
                                st.caption(f"유사도 점수: {c['similarity']:.4f}")
                else:
                    st.warning("⚠️ 유사 사례를 찾지 못했습니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 사례 등록 ---
elif mode == "📝 사례 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            mfr_options = ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직경 입력"]
            selected_mfr = st.selectbox("제조사", mfr_options)
            custom_mfr = st.text_input("제조사 직접 입력")
        with col2:
            model = st.text_input("모델명")
            item_options = ["TOC", "TP", "TN", "조류", "기타", "직접 입력"]
            selected_item = st.selectbox("측정항목", item_options)
            custom_item = st.text_input("측정항목 직접 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        reg_button = st.form_submit_button("✅ 지식 베이스 저장")
        
        if reg_button:
            final_mfr = custom_mfr if selected_mfr == "직접 입력" else selected_mfr
            final_item = custom_item if selected_item == "직접 입력" else selected_item
            if final_mfr and model and final_item and iss and sol:
                vec = get_embedding(f"제조사:{final_mfr} 모델:{model} 항목:{final_item} 현상:{iss} 조치:{sol}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": final_mfr, "model_name": model, "measurement_item": final_item,
                    "issue": iss, "solution": sol, "embedding": vec
                }).execute()
                st.success("데이터베이스 저장 완료")

# --- 기능 3: 데이터 관리 ---
elif mode == "🛠️ 데이터 관리":
    st.subheader("🛠️ 지식 리스트")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution").execute()
    if res.data:
        st.write(f"전체: {len(res.data)}건")
        st.dataframe(res.data, use_container_width=True)
    else:
        st.info("데이터가 없습니다.")
