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

# --- 모바일 및 웹 최적화 UI 설정 ---
st.set_page_config(
    page_title="K-eco 지식베이스 V2", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 정밀 조치 가이드", "📝 세부 사례 등록", "🛠️ 데이터 진단"])
st.sidebar.markdown("---")
# 검색 정밀도 (기본 0.35)
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 데이터베이스")
st.caption("제조사/모델/항목별로 세분화된 성주 님의 2세대 검증 노하우")
st.markdown("---")

# --- 기능 1: 정밀 조치 가이드 (5개 필드 기반) ---
if mode == "🤖 정밀 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: HATP-2000 TP mv 0 발생")
    
    if user_question:
        with st.spinner("세분화된 데이터를 검색 중..."):
            try:
                # 1. 상황 벡터화
                query_vec = get_embedding(user_question)
                
                # 2. 벡터 검색 (가장 유사한 1건을 우선으로 하되 최대 2개 참조)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec,
                    "match_threshold": search_threshold,
                    "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                
                if past_cases:
                    context_data = ""
                    source_info = []
                    for i, c in enumerate(past_cases):
                        context_data += f"### 사례 {i+1}\n"
                        context_data += f"- 제조사: {c['manufacturer']}\n"
                        context_data += f"- 모델명: {c['model_name']}\n"
                        context_data += f"- 측정항목: {c['measurement_item']}\n"
                        context_data += f"- 현상: {c['issue']}\n"
                        context_data += f"- 조치: {c['solution']}\n\n"
                        source_info.append(f"{c['manufacturer']} {c['model_name']} ({c['measurement_item']})")

                    # AI 프롬프트
                    prompt = f"""
                    당신은 수질 분석 전문가이자 조성주 님의 지식 조수입니다. 
                    제공된 [데이터베이스 사례]를 바탕으로 현장 직원에게 조치법을 설명하세요.

                    [작성 수칙]
                    1. 첫 문장은 "조성주 님의 {', '.join(source_info)} 사례를 바탕으로 안내드립니다."로 시작하세요.
                    2. 사용자의 질문과 [데이터베이스 사례]의 '제조사' 및 '측정항목'이 일치하는지 반드시 확인하고 답변하세요.
                    3. '조치'에 적힌 내용을 바탕으로 단계별 가이드를 작성하세요.
                    4. 데이터에 없는 외부 지식은 절대 섞지 마세요. 

                    [데이터베이스 사례]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    with st.expander("📚 참조한 원본 데이터 상세 보기"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 일치하는 성주 님의 검증 사례가 없습니다. 검색 정밀도를 조절하거나 사례를 먼저 등록해 주세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 세부 사례 등록 (제조사 직접 입력 기능 추가) ---
elif mode == "📝 세부 사례 등록":
    st.subheader("📝 신규 노하우 등록 (5대 필드)")
    with st.form("add_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            # 제조사 선택 리스트 업데이트
            mfr_options = ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]
            selected_mfr = st.selectbox("제조사", mfr_options)
            
            # "직접 입력" 선택 시 텍스트 입력창 활성화 (폼 내부이므로 변수로 관리)
            final_mfr = ""
            if selected_mfr == "직접 입력":
                input_mfr = st.text_input("제조사명 입력", placeholder="제조사 이름을 직접 쓰세요")
                final_mfr = input_mfr
            else:
                final_mfr = selected_mfr
                
        with col2:
            model = st.text_input("모델명", placeholder="예: TOC-4200")
        with col3:
            item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타"])
        
        iss = st.text_input("발생 현상", placeholder="예: TP mv 값 0 확인")
        sol = st.text_area("조치 내용", placeholder="성주 님만의 상세 해결 방법을 기록해 주세요.")
        
        if st.form_submit_button("지식 베이스 저장"):
            # 제조사 정보가 비어있는지 체크
            if final_mfr and model and iss and sol:
                with st.spinner("AI 분석 및 자동 벡터화 진행 중..."):
                    # 5개 필드를 모두 결합하여 강력한 의미 벡터 생성
                    combined_text = f"제조사:{final_mfr} 모델:{model} 항목:{item} 현상:{iss} 조치:{sol}"
                    vec = get_embedding(combined_text)
                    
                    try:
                        supabase.table("knowledge_base").insert({
                            "manufacturer": final_mfr,
                            "model_name": model,
                            "measurement_item": item,
                            "issue": iss,
                            "solution": sol,
                            "embedding": vec
                        }).execute()
                        st.success(f"✅ [{final_mfr}] 데이터가 성공적으로 등록되었습니다!")
                    except Exception as e:
                        st.error(f"DB 저장 오류: {e}")
            else:
                st.warning("모든 필드를 입력해 주세요. (제조사 포함)")

# --- 기능 3: 데이터 진단 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 관리")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue").execute()
    if res.data:
        st.write(f"현재 등록된 지식: {len(res.data)}건")
        st.dataframe(res.data) 
    else:
        st.info("현재 저장된 지식이 없습니다. '세부 사례 등록'을 이용해 주세요.")
