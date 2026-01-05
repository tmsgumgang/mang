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

# 벡터 임베딩 생성 함수 (768차원)
def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- 모바일 최적화 UI 설정 ---
st.set_page_config(
    page_title="K-eco 조치봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 검증 지식 조치 가이드", "📝 새로운 사례 등록", "🛠️ 데이터 진단"])
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.2, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("조성주 님의 검증된 데이터를 최우선으로 하는 엄격한 가이드 모드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Strict Mode 적용) ---
if mode == "🤖 검증 지식 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("성주 님의 노하우를 검색 중..."):
            try:
                # 1. 질문 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 호출
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 3
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    # AI에게 줄 컨텍스트 구성
                    context = "\n".join([f"### [검증 사례]\n- 장비: {c['equipment']}\n- 현상: {c['issue']}\n- 조치: {c['solution']}\n" for i, c in enumerate(past_cases)])
                    
                    # [핵심 수정] 외부 지식 사용을 강력히 금지하는 프롬프트
                    prompt = f"""
                    당신은 수질 전문가입니다. 아래 제공된 [검증 사례]만을 바탕으로 답변하세요.
                    
                    [절대 규칙]
                    1. 답변은 반드시 "조성주 님의 검증된 사례를 바탕으로 안내드립니다."로 시작하세요.
                    2. [검증 사례]에 기재된 '조치' 내용만 구체적으로 설명하세요.
                    3. [검증 사례]에 없는 내용은 **절대로** 추측하거나 추가하지 마세요. 
                    4. 사례가 질문과 100% 일치하지 않더라도, 사례 내의 기술적 근거(예: 가스 유입 등)만 언급하세요.
                    5. 말투는 현장에서 읽기 좋게 짧은 개조식(1., 2., 3.)으로 작성하세요.

                    [검증 사례]
                    {context}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.info("💡 검증된 조치 사항")
                    st.write(response.text)
                    
                    with st.expander("📚 참조한 DB 데이터 상세"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 유사한 검증 지식이 DB에 없습니다. 감도를 낮추거나 새로운 사례를 등록해 주세요.")
                    # 지식이 없을 때만 일반적인 짧은 가이드 제공 (최소화)
                    st.write("현재 지식 베이스에 관련 내용이 없습니다. 정확한 조치를 위해 사례 등록이 필요합니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (저장 시 자동 벡터화 100% 보장) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 새로운 조치 노하우 등록")
    st.info("여기에 저장하면 AI가 즉시 '의미'를 학습하여 자동 벡터화됩니다.")
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "KORBI TN/TP", "기타"])
        iss = st.text_input("현상 (예: 측정값 헌팅)")
        sol = st.text_area("조치 내용 (구체적인 해결 방법)")
        
        if st.form_submit_button("지식 저장"):
            if eq and iss and sol:
                with st.spinner("AI 분석 및 자동 벡터화 중..."):
                    # 저장 시점에 임베딩을 생성하여 함께 저장 (자동화)
                    vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
                    supabase.table("knowledge_base").insert({
                        "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
                    }).execute()
                    st.success("✅ 등록 완료! 이제 '조치 가이드'에서 검색이 가능합니다.")

# --- 기능 3: 진단 및 복구 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태 진단")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"총 데이터: {len(res.data)}건")
        if missing:
            st.warning(f"벡터 데이터(지능)가 없는 과거 데이터: {len(missing)}건")
            if st.button("🔄 누락 데이터 일괄 복구"):
                for item in missing:
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.success("복구 완료!")
                st.rerun()
        else:
            st.success("✅ 모든 데이터가 정상적으로 벡터화되어 있습니다.")
