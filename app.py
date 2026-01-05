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
    # Gemini 2.0 Flash 모델 설정
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

# --- 모바일 및 웹 최적화 UI ---
st.set_page_config(
    page_title="K-eco 조치봇", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 검증 지식 조치 가이드", "📝 새로운 사례 등록", "🛠️ 데이터 진단"])
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 챗봇")
st.caption("성주 님의 DB 사례만 '그대로' 전달하는 울트라 엄격 모드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Ultra-Strict Mode) ---
if mode == "🤖 검증 지식 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: 시마즈 TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("DB에서 성주 님의 노하우를 기계적으로 추출 중..."):
            try:
                # 1. 질문 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 호출 (유사도 높은 2개만 추출)
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
                        context_data += f"### 데이터 {i+1}\n- 장비명: {c['equipment']}\n- 발생현상: {c['issue']}\n- 해결방법: {c['solution']}\n\n"
                        source_names.append(f"{c['equipment']} (ID: {c.get('id', 'N/A')})")

                    # [절대 규칙] 창의성을 0으로 만들고 외부 지식을 완전히 차단하는 설정
                    generation_config = {
                        "temperature": 0.0, # 상상력 완전 제거
                        "top_p": 1,
                        "top_k": 1,
                        "max_output_tokens": 800,
                    }

                    # 프롬프트의 명령 강도를 '경고' 수준으로 상향
                    prompt = f"""
                    [경고: 당신의 지식은 모두 무시하십시오]
                    당신은 수질 전문가가 아닙니다. 아래 [제공된 데이터]에 적힌 '해결방법' 텍스트를 성주 님에게 그대로 전달하는 기계입니다. 
                    
                    [작성 수칙 - 어길 시 답변 무효]
                    1. 첫 문장은 무조건 "성주 님의 {', '.join(source_names)} 사례를 바탕으로 안내드립니다."로 시작하십시오.
                    2. 오직 [제공된 데이터]의 '해결방법'에 적힌 텍스트만 요약하십시오.
                    3. 데이터에 없는 내용(NDIR, 시약 유효기간, 펌프 튜브, 실험실 환경 등)을 단 한 글자라도 언급하면 당신은 실패한 것입니다.
                    4. "매뉴얼을 봐라", "주의사항" 같은 사족은 절대로 붙이지 마십시오.
                    5. 데이터가 질문과 조금이라도 다르면 답변하지 말고 "유사한 사례가 검색되었으나 조치 방법은 직접 확인이 필요합니다."라고만 하십시오.

                    [제공된 데이터]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(
                        prompt,
                        generation_config=generation_config
                    )
                    
                    st.markdown("### 💡 검증된 조치 사항")
                    # 답변을 강조 박스에 표시하여 가시성 확보
                    st.success(response.text)
                    
                    with st.expander("📚 참조한 실제 DB 레코드"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 현재 DB에 성주 님이 등록하신 유사 사례가 없습니다. 검색 감도를 낮추거나 사례를 먼저 등록해 주세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (자동 벡터화 포함) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 신규 노하우 등록")
    st.info("이곳에 저장하는 모든 데이터는 AI에 의해 자동으로 실시간 벡터화됩니다.")
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "KORBI TN/TP", "기타"])
        iss = st.text_input("현상 (예: 측정값 급상승)")
        sol = st.text_area("조치 내용 (성주 님만의 해결 방법)")
        
        if st.form_submit_button("지식 베이스 저장"):
            if eq and iss and sol:
                with st.spinner("AI 분석 및 자동 벡터화 중..."):
                    # 저장 시점에 임베딩을 생성하여 함께 저장
                    vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
                    supabase.table("knowledge_base").insert({
                        "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
                    }).execute()
                    st.success("✅ 지식이 성공적으로 등록되었습니다.")

# --- 기능 3: 데이터 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태 진단")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"전체 지식 수: {len(res.data)}건")
        if missing:
            st.warning(f"벡터 데이터(지능)가 누락된 과거 데이터: {len(missing)}건")
            if st.button("🔄 누락 데이터 일괄 복구"):
                for item in missing:
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.success("복구 완료!")
                st.rerun()
        else:
            st.success("✅ 모든 데이터가 정상적으로 벡터화되어 있습니다.")
