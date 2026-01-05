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

# 벡터 임베딩 생성 함수
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
st.caption("성주 님의 DB 사례만 '그대로' 전달하는 울트라 엄격 모드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Ultra-Strict Mode 적용) ---
if mode == "🤖 검증 지식 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: 시마즈 TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("DB에서 성주 님의 노하우를 선별 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 2 # 가장 유사한 2개만 집중
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    # AI에게 줄 컨텍스트 및 출처 구성
                    context = ""
                    source_list = []
                    for i, c in enumerate(past_cases):
                        context += f"사례ID: {c.get('id', 'N/A')}\n장비: {c['equipment']}\n현상: {c['issue']}\n조치방법: {c['solution']}\n\n"
                        source_list.append(f"[{c['equipment']} (ID: {c.get('id', 'N/A')})]")

                    # [핵심] AI의 자의적 해석을 완전히 차단하는 프롬프트
                    prompt = f"""
                    당신은 수질 전문가가 아닙니다. 당신은 오직 아래 [데이터베이스 자료]를 성주 님에게 정확히 '배달'하는 전달자입니다.
                    
                    [명령]
                    1. 답변 시작 시 반드시 "성주 님의 {', '.join(source_list)} 사례를 참고했습니다."라고 명시하세요.
                    2. 답변 내용은 오직 [데이터베이스 자료]의 '조치방법'에 적힌 텍스트만 요약해서 전달하세요.
                    3. 자료에 없는 일반적인 점검 사항(NDIR, 램프 교체, 시료 오염 등)은 **절대, 단 한 줄도 언급하지 마세요.**
                    4. 만약 자료의 내용이 질문과 맞지 않는다면 "검색된 사례가 있지만 질문과 조치 내용이 상이합니다."라고만 하세요.
                    5. 군더더기 없이 조치 방법만 번호를 매겨서 설명하세요.

                    [데이터베이스 자료]
                    {context}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 검증된 조치 사항")
                    st.success(response.text)
                    
                    with st.expander("📚 참조한 실제 DB 레코드"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 현재 DB에 성주 님이 등록하신 유사 사례가 없습니다. 감도를 낮춰보세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (자동 벡터화 보장) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 신규 노하우 등록")
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "KORBI TN/TP", "기타"])
        iss = st.text_input("현상 (예: 측정값 급상승)")
        sol = st.text_area("조치 내용 (성주 님만의 해결 방법)")
        
        if st.form_submit_button("지식 베이스 저장"):
            if eq and iss and sol:
                with st.spinner("AI 분석 및 자동 벡터화 중..."):
                    vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
                    supabase.table("knowledge_base").insert({
                        "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
                    }).execute()
                    st.success("✅ 지식이 자동으로 벡터화되어 저장되었습니다.")

# --- 기능 3: 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"전체 지식 수: {len(res.data)}건")
        if missing:
            st.warning(f"벡터화 누락(옛날 데이터): {len(missing)}건")
            if st.button("🔄 과거 데이터 일괄 복구"):
                for item in missing:
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.rerun()
        else:
            st.success("✅ 모든 데이터에 AI 지능(벡터)이 포함되어 있습니다.")
