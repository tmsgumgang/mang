import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안 개선] Streamlit Cloud의 Secrets 기능을 사용하여 정보를 가져옵니다.
# 로컬에서 테스트할 때는 .streamlit/secrets.toml 파일이 필요합니다.
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("Secrets 설정이 누락되었습니다. Streamlit Cloud 설정에서 키를 입력해 주세요.")
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

# --- 모바일 최적화 UI ---
st.set_page_config(
    page_title="K-eco 조치봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 조치 가이드", "📝 사례 등록", "🛠️ 진단"])
search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.2, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("현장에서 실시간으로 확인하는 성주 님의 검증 노하우")
st.markdown("---")

if mode == "🤖 조치 가이드":
    user_question = st.text_input("상황 설명", placeholder="예: 시마즈 장비 헌팅 발생")
    if user_question:
        with st.spinner("과거 노하우 분석 중..."):
            query_vec = get_embedding(user_question)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec,
                "match_threshold": search_threshold,
                "match_count": 3
            }).execute()
            
            past_cases = rpc_res.data
            if past_cases:
                context = "\n".join([f"### [사례]\n- 장비: {c['equipment']}\n- 현상: {c['issue']}\n- 조치: {c['solution']}\n" for c in past_cases])
                prompt = f"수질 전문가로서 아래 사례를 바탕으로 답변하세요.\n\n[참고 사례]\n{context}\n\n질문: {user_question}"
                st.info("💡 권장 조치 사항")
                st.write(ai_model.generate_content(prompt).text)
            else:
                st.warning("유사 지식 없음. 감도를 낮춰보세요.")

elif mode == "📝 사례 등록":
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "기타"])
        iss = st.text_input("현상")
        sol = st.text_area("조치")
        if st.form_submit_button("저장"):
            vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
            supabase.table("knowledge_base").insert({
                "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
            }).execute()
            st.success("✅ 등록 완료!")

elif mode == "🛠️ 진단":
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"총 데이터: {len(res.data)}건")
        if missing and st.button("복구"):
            for item in missing:
                vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
            st.rerun()