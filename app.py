import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Settings > Secrets에 정보를 입력해 주세요.")
    st.stop()

@st.cache_resource
def init_clients():
    # Supabase 클라이언트 초기화
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # Gemini API 설정
    genai.configure(api_key=GEMINI_API_KEY)
    # 대화 및 요약용 모델 설정 (Gemini 2.0 Flash)
    chat_model = genai.GenerativeModel('gemini-2.0-flash') 
    return supabase_client, chat_model

try:
    supabase, ai_model = init_clients()
except Exception as e:
    st.error(f"시스템 연결 실패: {e}")

# 벡터 임베딩 생성 함수 (768차원 text-embedding-004 사용)
def get_embedding(text):
    result = genai.embed_content(
        model="models/text-embedding-004",
        content=text,
        task_type="retrieval_document"
    )
    return result['embedding']

# --- 모바일 및 웹 최적화 UI 설정 ---
st.set_page_config(
    page_title="K-eco 현장 조치 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 검증 지식 조치 가이드", "📝 새로운 사례 등록", "🛠️ 데이터 진단"])
st.sidebar.markdown("---")
# 검색 정밀도: 기본 0.35 정도로 설정하여 적절한 유연성을 확보합니다.
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("조성주 님의 검증된 노하우를 기반으로 한 현장 맞춤형 가이드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Balanced Mode) ---
if mode == "🤖 검증 지식 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: 시마즈 TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("DB에서 성주 님의 노하우를 분석 중..."):
            try:
                # 1. 상황 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 (상위 2개 사례를 참조하여 답변의 풍부함 확보)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    # AI에게 줄 컨텍스트 및 출처 구성
                    context_data = ""
                    source_names = []
                    for i, c in enumerate(past_cases):
                        context_data += f"### 사례 {i+1}\n- 장비명: {c['equipment']}\n- 발생현상: {c['issue']}\n- 해결방법: {c['solution']}\n\n"
                        source_names.append(f"{c['equipment']} (ID: {c.get('id', 'N/A')})")

                    # [균형 프롬프트] 성주 님의 데이터에 충실하되, 읽기 좋게 설명하도록 지시
                    prompt = f"""
                    당신은 수질 전문가이자 조성주 님의 지식 조수입니다. 
                    아래 [제공된 데이터]에 적힌 내용을 바탕으로 현장 직원에게 친절하고 전문적으로 설명하십시오.

                    [작성 수칙]
                    1. 첫 문장은 반드시 "조성주 님의 {', '.join(source_names)} 사례를 바탕으로 안내드립니다."로 시작하십시오.
                    2. [제공된 데이터]의 '해결방법'을 바탕으로 구체적인 조치 단계를 설명하십시오.
                    3. 데이터에 없는 내용(NDIR 점검 등 작성되지 않은 기술 지식)은 섞지 마십시오.
                    4. 현장에서 보기 편하도록 번호를 매겨 명확하게 작성하십시오.
                    5. 데이터가 부족하다면 "데이터에는 [내용]이라고만 기록되어 있으니 이를 우선 확인하십시오."라고 조언하십시오.

                    [제공된 데이터]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    
                    st.markdown("### 💡 권장 조치 사항")
                    # AI가 다듬은 답변 출력
                    st.info(response.text)
                    
                    with st.expander("📚 참조한 실제 DB 원본 텍스트 보기"):
                        for c in past_cases:
                            st.write(f"**[{c['equipment']}]** : {c['solution']}")
                else:
                    st.warning("⚠️ 현재 DB에 유사한 검증 사례가 없습니다. 검색 감도를 조절해 보세요.")
            except Exception as e:
                st.error(f"검색 과정 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (자동 벡터화 포함) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 신규 현장 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "KORBI TN/TP", "기타"])
        iss = st.text_input("현상 (예: 측정값 헌팅)")
        sol = st.text_area("조치 내용 (성주 님만의 해결 방법)")
        
        if st.form_submit_button("지식 베이스 저장"):
            if eq and iss and sol:
                with st.spinner("자동 벡터화 진행 중..."):
                    vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
                    supabase.table("knowledge_base").insert({
                        "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
                    }).execute()
                    st.success("✅ 등록 완료! 이제 즉시 검색에 반영됩니다.")

# --- 기능 3: 데이터 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태 진단")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"전체 지식 수: {len(res.data)}건")
        if missing:
            st.warning(f"벡터 지능 누락 데이터: {len(missing)}건")
            if st.button("🔄 일괄 복구"):
                for item in missing:
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.rerun()
        else:
            st.success("✅ 모든 데이터가 정상적으로 벡터화되어 있습니다.")
