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
    # Supabase 클라이언트 초기화
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # Gemini API 설정
    genai.configure(api_key=GEMINI_API_KEY)
    # 대화 및 가이드 생성용 모델 (Gemini 2.0 Flash)
    chat_model = genai.GenerativeModel('gemini-2.0-flash') 
    return supabase_client, chat_model

try:
    supabase, ai_model = init_clients()
except Exception as e:
    st.error(f"시스템 연결 실패: {e}")

# 벡터 임베딩 생성 함수 (5개 핵심 필드 결합)
def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- 모바일 UI/UX 최적화 설정 ---
st.set_page_config(
    page_title="K-eco 현장 조치 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 모바일 화면에서 더 깔끔하게 보이도록 커스텀 CSS 적용
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        border-radius: 10px;
        height: 3em;
        background-color: #007BFF;
        color: white;
        font-weight: bold;
    }
    .stTextInput>div>div>input {
        border-radius: 10px;
    }
    .main .block-container {
        padding-top: 2rem;
        padding-bottom: 5rem;
    }
    </style>
    """, unsafe_allow_html=True)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 설정")
mode = st.sidebar.radio("작업 선택", ["🤖 조치법 검색", "📝 사례 등록", "🛠️ 데이터 관리"])
st.sidebar.markdown("---")
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("성주 님의 노하우를 현장에서 가장 빠르게 확인하세요.")
st.markdown("---")

# --- 기능 1: 정밀 조치 가이드 (버튼 UI 및 검색 개선) ---
if mode == "🤖 조치법 검색":
    st.subheader("🔍 현장 상황 입력")
    
    # 모바일에서 직관적인 검색을 위해 폼(Form) 사용
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("상황을 짧게 입력하세요", placeholder="예: HATP TP mv 0 발생")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if submit_button and user_question:
        with st.spinner("DB에서 최적의 해결책을 찾는 중..."):
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
                        case_list.append(f"{c['manufacturer']} {c['model_name']} ({c['measurement_item']})")

                    prompt = f"""
                    당신은 수질 전문가이자 조성주 님의 지식 조수입니다. 
                    사용자에게 되묻지 말고 [데이터베이스 사례]에 기반하여 조치법을 설명하세요.

                    [작성 수칙]
                    1. 첫 문장은 "조성주 님의 {', '.join(case_list)} 사례를 바탕으로 안내드립니다."로 시작.
                    2. 번호를 매겨 단계별로 명확하게 설명.
                    3. 데이터에 없는 내용은 절대 언급 금지.

                    [데이터베이스 사례]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    with st.expander("📚 참조한 원본 데이터"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 유사한 사례가 없습니다. 질문을 바꾸거나 정밀도를 낮춰보세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 세부 사례 등록 (입력 UI 최적화) ---
elif mode == "📝 사례 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        mfr_options = ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]
        selected_mfr = st.selectbox("제조사", mfr_options)
        custom_mfr = st.text_input("제조사 직접 입력 (필요시)")
        
        model = st.text_input("모델명 (예: TOC-4200)")
        
        item_options = ["TOC", "TP", "TN", "조류", "기타", "직접 입력"]
        selected_item = st.selectbox("측정항목", item_options)
        custom_item = st.text_input("측정항목 직접 입력 (필요시)")
        
        iss = st.text_input("발생 현상 (예: 값 급상승)")
        sol = st.text_area("조치 내용 (구체적인 해결법)")
        
        reg_button = st.form_submit_button("✅ 지식 베이스에 저장")
        
        if reg_button:
            final_mfr = custom_mfr if selected_mfr == "직접 입력" else selected_mfr
            final_item = custom_item if selected_item == "직접 입력" else selected_item
            
            if final_mfr and model and final_item and iss and sol:
                with st.spinner("자동 벡터화 진행 중..."):
                    combined_text = f"제조사:{final_mfr} 모델:{model} 항목:{final_item} 현상:{iss} 조치:{sol}"
                    vec = get_embedding(combined_text)
                    try:
                        supabase.table("knowledge_base").insert({
                            "manufacturer": final_mfr, "model_name": model, "measurement_item": final_item,
                            "issue": iss, "solution": sol, "embedding": vec
                        }).execute()
                        st.success(f"✅ {final_mfr} 사례 등록 성공!")
                    except Exception as e:
                        st.error(f"저장 실패: {e}")
            else:
                st.warning("⚠️ 모든 칸을 채워주세요.")

# --- 기능 3: 데이터 관리 (조치 방안 포함 노출) ---
elif mode == "🛠️ 데이터 관리":
    st.subheader("🛠️ 저장된 지식 리스트")
    # 조치 방안(solution)을 포함하여 데이터 셀렉트
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue, solution").execute()
    if res.data:
        st.write(f"전체 지식 수: {len(res.data)}건")
        # 모바일 가독성을 위해 데이터프레임 높이 조절
        st.dataframe(res.data, use_container_width=True, height=400)
    else:
        st.info("현재 저장된 데이터가 없습니다.")
