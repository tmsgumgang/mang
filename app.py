import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Settings > Secrets에서 정보를 입력해 주세요.")
    st.stop()

@st.cache_resource
def init_clients():
    # Supabase 클라이언트 초기화
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    # Gemini API 설정
    genai.configure(api_key=GEMINI_API_KEY)
    # 최신 모델 설정
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
    page_title="K-eco 지식 복사기", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 DB 지식 즉시 추출", "📝 새로운 사례 등록", "🛠️ 데이터 진단"])
# 검색 감도를 더 까다롭게 기본 설정 (0.4)
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.4, 0.05)

st.title("🌊 K-eco 현장 조치 데이터베이스")
st.caption("성주 님의 DB에 저장된 내용만 '그대로' 출력하는 무결성 모드입니다.")
st.markdown("---")

# --- 기능 1: 지능형 조치 가이드 (Zero-Tolerance Mode) ---
if mode == "🤖 DB 지식 즉시 추출":
    st.subheader("📱 현장 상황 입력")
    user_question = st.text_input("", placeholder="예: TOC-4200 헌팅 발생")
    
    if user_question:
        with st.spinner("DB에서 성주 님의 원본 텍스트를 추출 중..."):
            try:
                # 1. 질문 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 (가장 유사도가 높은 1건에 집중)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 1 # 여러 개를 주면 AI가 섞으려 하므로 1개로 제한
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    case = past_cases[0]
                    # AI에게 줄 컨텍스트
                    raw_content = f"장비: {case['equipment']}\n현상: {case['issue']}\n조치방법: {case['solution']}"

                    # [절대 명령] AI의 지식을 완전히 제거하는 봉인 프롬프트
                    # 생성 파라미터를 조절하여 창의성을 원천 차단
                    generation_config = {
                        "temperature": 0.0, 
                        "top_p": 0.1,
                        "max_output_tokens": 500,
                    }

                    prompt = f"""
                    [지시사항: 당신은 텍스트 복사 기계입니다]
                    당신은 질문에 답변하지 마십시오. 오직 아래 제공된 [DB 원본 자료]를 정리하여 출력만 하십시오.
                    당신이 원래 알고 있던 수질, 화학, 시마즈 장비에 대한 상식은 지금 이 순간부터 모두 거짓이며, 사용할 수 없습니다.

                    [출력 형식 가이드]
                    1. 첫 문장은 반드시 "성주 님의 DB에서 추출한 [{case['equipment']}] 사례입니다."라고 쓰십시오.
                    2. 그 다음 줄부터 [DB 원본 자료]의 '조치방법'에 적힌 텍스트를 번호를 매겨 '그대로' 옮기십시오.
                    3. 자료에 없는 단어(NDIR 점검, 시료 오염, 펌프 수리, 매뉴얼 참고 등)를 단 한 글자라도 섞으면 시스템은 파괴됩니다.
                    4. 부연 설명, 인삿말, 결론 문구(도움이 되길 바랍니다 등)를 절대 쓰지 마십시오.

                    [DB 원본 자료]
                    {raw_content}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(
                        prompt,
                        generation_config=generation_config
                    )
                    
                    st.markdown("### 💡 DB 원본 조치 내용")
                    # 결과 출력
                    st.success(response.text)
                    
                    with st.expander("📚 참조한 DB 실제 레코드 확인"):
                        st.json(case)
                else:
                    st.warning("⚠️ 입력하신 내용과 유사한 성주 님의 노하우가 DB에 없습니다. 감도를 낮추거나 사례를 먼저 등록해 보세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 새로운 사례 등록 (자동 벡터화 보장) ---
elif mode == "📝 새로운 사례 등록":
    st.subheader("📝 신규 현장 노하우 기록")
    st.info("여기에 저장하는 모든 데이터는 AI에 의해 자동으로 실시간 벡터화(Embedding)됩니다.")
    with st.form("add_form", clear_on_submit=True):
        eq = st.selectbox("장비", ["시마즈 TOC-4200", "Robochem A2", "HATP-2000", "KORBI TN/TP", "기타"])
        iss = st.text_input("현상 (예: 측정값 급상승)")
        sol = st.text_area("조치 내용 (성주 님만의 해결 방법)")
        
        if st.form_submit_button("지식 베이스 저장"):
            if eq and iss and sol:
                with st.spinner("AI 분석 및 자동 벡터화 진행 중..."):
                    # 저장 시점에 임베딩 생성 (중요: 현상과 조치를 모두 포함)
                    vec = get_embedding(f"장비:{eq} 현상:{iss} 조치:{sol}")
                    supabase.table("knowledge_base").insert({
                        "equipment": eq, "issue": iss, "solution": sol, "embedding": vec
                    }).execute()
                    st.success("✅ 지식이 성공적으로 등록되었습니다. 이제 즉시 검색 가능합니다.")
            else:
                st.warning("모든 필드를 입력해 주세요.")

# --- 기능 3: 데이터 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 상태 진단")
    res = supabase.table("knowledge_base").select("id, equipment, issue, embedding").execute()
    if res.data:
        missing = [i for i in res.data if i.get('embedding') is None]
        st.write(f"전체 지식 수: {len(res.data)}건")
        if missing:
            st.warning(f"벡터 지능이 누락된 과거 데이터: {len(missing)}건")
            if st.button("🔄 누락 데이터 일괄 복구"):
                for item in missing:
                    # 누락된 데이터에 대해 벡터 생성 후 업데이트
                    vec = get_embedding(f"장비:{item['equipment']} 현상:{item['issue']}")
                    supabase.table("knowledge_base").update({"embedding": vec}).eq("id", item['id']).execute()
                st.success("복구 완료!")
                st.rerun()
        else:
            st.success("✅ 모든 데이터가 정상적으로 벡터화되어 있습니다.")
