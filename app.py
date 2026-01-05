import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Settings > Secrets를 확인해 주세요.")
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

# 벡터 임베딩 생성 함수 (5개 필드를 조합하여 의미 추출)
def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- 모바일 최적화 UI 설정 ---
st.set_page_config(
    page_title="K-eco 지식베이스", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 정밀 조치 가이드", "📝 세부 사례 등록", "🛠️ 데이터 진단"])
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 데이터베이스")
st.caption("제조사/모델/항목별로 세분화된 성주 님의 검증 노하우")
st.markdown("---")

# --- 기능 1: 정밀 조치 가이드 (5개 필드 기반) ---
if mode == "🤖 정밀 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: HATP-2000 TP mv 0 발생")
    
    if user_question:
        with st.spinner("세분화된 데이터를 검색 중..."):
            try:
                query_vec = get_embedding(user_question)
                
                # 벡터 검색 (유사도 순 1~2개 사례 참조)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    context_data = ""
                    source_names = []
                    for i, c in enumerate(past_cases):
                        # 5개 필드 정보를 조합하여 AI에게 전달
                        context_data += f"### 사례 {i+1}\n"
                        context_data += f"- 제조사: {c.get('manufacturer', 'N/A')}\n"
                        context_data += f"- 모델명: {c.get('model_name', 'N/A')}\n"
                        context_data += f"- 측정항목: {c.get('measurement_item', 'N/A')}\n"
                        context_data += f"- 발생현상: {c['issue']}\n"
                        context_data += f"- 해결방법: {c['solution']}\n\n"
                        source_names.append(f"{c.get('model_name', '장비')} ({c.get('measurement_item', '항목')})")

                    prompt = f"""
                    당신은 수질 분석 전문가이자 조성주 님의 지식 조수입니다. 
                    제공된 [데이터베이스 사례]를 바탕으로 현장 직원에게 조치법을 설명하세요.

                    [작성 수칙]
                    1. 첫 문장은 "조성주 님의 {', '.join(source_names)} 사례를 바탕으로 안내드립니다."로 시작하세요.
                    2. 사용자의 질문과 [데이터베이스 사례]의 '측정항목'이나 '모델명'이 일치하는지 먼저 확인하고 답변하세요.
                    3. '해결방법'에 적힌 내용을 단계별로 친절하게 설명하세요.
                    4. 데이터에 없는 외부 지식은 절대 섞지 마세요.

                    [데이터베이스 사례]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    with st.expander("📚 참조한 원본 데이터 상세"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 일치하는 사례가 없습니다. 검색 정밀도를 낮추거나 사례를 등록해 주세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 세부 사례 등록 (5개 필드 확장) ---
elif mode == "📝 세부 사례 등록":
    st.subheader("📝 신규 노하우 등록 (세분화)")
    with st.form("add_form", clear_on_submit=True):
        col1, col2 = st.columns(2)
        with col1:
            mfr = st.selectbox("제조사", ["시마즈(Shimadzu)", "로보켐(Robochem)", "HATP", "코비(KORBI)", "기타"])
            item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타"])
        with col2:
            model = st.text_input("모델명", placeholder="예: TOC-4200")
        
        iss = st.text_input("발생 현상", placeholder="예: TP mv 값 0 확인")
        sol = st.text_area("조치 내용", placeholder="성주 님만의 상세 해결 방법을 적어주세요.")
        
        if st.form_submit_button("지식 베이스 저장"):
            if mfr and model and iss and sol:
                with st.spinner("자동 벡터화 진행 중..."):
                    # 5개 필드를 결합하여 임베딩 생성 (검색 성능 최적화)
                    combined_text = f"제조사:{mfr} 모델:{model} 항목:{item} 현상:{iss} 조치:{sol}"
                    vec = get_embedding(combined_text)
                    
                    supabase.table("knowledge_base").insert({
                        "manufacturer": mfr,
                        "model_name": model,
                        "measurement_item": item,
                        "issue": iss,
                        "solution": sol,
                        "embedding": vec
                    }).execute()
                    st.success("✅ 세분화된 지식이 등록되었습니다!")

# --- 기능 3: 데이터 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태")
    res = supabase.table("knowledge_base").select("*").execute()
    if res.data:
        st.write(f"전체 지식 수: {len(res.data)}건")
        st.dataframe(res.data) # 전체 표 확인
