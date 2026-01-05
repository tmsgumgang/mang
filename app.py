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
    # 최신 모델 사용
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

# --- 모바일 및 웹 최적화 UI ---
st.set_page_config(
    page_title="K-eco 조치봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정 (관리용)
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 검증 지식 조치 가이드", "📝 새로운 사례 등록", "🛠️ 데이터 진단"])
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.25, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("조성주 님의 DB 사례만 '그대로' 전달하는 울트라 엄격 모드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Ultra-Strict Mode) ---
if mode == "🤖 검증 지식 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: 시마즈 TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("DB에서 성주 님의 노하우를 선별 중..."):
            try:
                # 1. 질문 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 호출 (상위 2개만 집중)
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
                        context_data += f"### 사례 {i+1}\n- 장비: {c['equipment']}\n- 상황: {c['issue']}\n- 조치: {c['solution']}\n\n"
                        source_names.append(f"{c['equipment']} (ID: {c.get('id', 'N/A')})")

                    # [핵심] AI의 외부 지식을 원천 차단하는 '봉인' 프롬프트
                    prompt = f"""
                    [엄격 명령: 당신은 지식 배달 기계입니다]
                    당신은 아래 제공된 [성주 님의 DB 자료]에 적힌 텍스트만 사용하여 답변해야 합니다. 
                    당신이 원래 알고 있던 수질, 화학, 장비 지식은 모두 무시하십시오. 

                    [답변 규칙]
                    1. 반드시 "조성주 님의 {', '.join(source_names)} 사례를 바탕으로 안내드립니다."로 시작하십시오.
                    2. 오직 [성주 님의 DB 자료]의 '조치' 항목에 적힌 내용만 번호를 매겨 요약하십시오.
                    3. 자료에 없는 단어(예: NDIR, 필터 누출, 시료 오염 등 성주 님이 쓰지 않은 단어)가 답변에 포함되면 안 됩니다.
                    4. 자료에 없는 '일반적인 주의사항'이나 '제조사 문의' 같은 사족을 절대 붙이지 마십시오.
                    5. 자료가 질문과 맞지 않는다면 "관련 사례가 있으나 조치 내용이 상이합니다."라고만 말하십시오.

                    [성주 님의 DB 자료]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 검증된 조치 사항")
                    # 결과를 박스 안에 넣어 가독성 높임
                    st.success(response.text)
                    
                    with st.expander("📚 참조한 실제 DB 원본 보기"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 현재 DB에 성주 님이 등록하신 유사 사례가 없습니다. 감도를 낮추거나 사례를 먼저 등록해 주세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (자동 벡터화 포함) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 신규 노하우 등록")
    st.info("여기에 저장하면 AI가 자동으로 벡터 데이터를 생성합니다.")
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
                    st.success("✅ 지식이 성공적으로 등록되었습니다.")

# --- 기능 3: 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태 진단")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"전체 지식 수: {len(res.data)}건")
        if missing:
            st.warning(f"벡터 데이터가 누락된 과거 데이터: {len(missing)}건")
            if st.button("🔄 누락 데이터 일괄 복구"):
                for item in missing:
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.success("복구 완료!")
                st.rerun()
        else:
            st.success("✅ 모든 데이터가 정상적으로 벡터화되어 있습니다.")
