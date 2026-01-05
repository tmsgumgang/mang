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

# --- 모바일 최적화 UI ---
st.set_page_config(
    page_title="K-eco 지식베이스 V2", 
    layout="centered", 
    initial_sidebar_state="collapsed",
    page_icon="🌊"
)

# 사이드바 설정
st.sidebar.title("⚙️ 시스템 관리")
mode = st.sidebar.radio("작업 선택", ["🤖 정밀 조치 가이드", "📝 세부 사례 등록", "🛠️ 데이터 진단"])
search_threshold = st.sidebar.slider("검색 정밀도 (Threshold)", 0.0, 1.0, 0.35, 0.05)

st.title("🌊 K-eco 현장 조치 데이터베이스")
st.caption("제조사/모델/항목별 세분화 모드 (성주 님 검증 노하우)")
st.markdown("---")

# --- 기능 1: 정밀 조치 가이드 (답변 강제화 로직 반영) ---
if mode == "🤖 정밀 조치 가이드":
    st.subheader("📱 현장 상황 설명")
    user_question = st.text_input("", placeholder="예: 시마즈 toc 값이 갑자기 올라갔어")
    
    if user_question:
        with st.spinner("DB에서 조치법을 즉시 추출 중..."):
            try:
                query_vec = get_embedding(user_question)
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
                        context_data += f"- 조치내용: {c['solution']}\n\n"
                        source_info.append(f"{c['manufacturer']} {c['model_name']} ({c['measurement_item']})")

                    # [핵심] 되묻지 말고 바로 답하게 만드는 프롬프트
                    prompt = f"""
                    당신은 수질 전문가이자 조성주 님의 지식 조수입니다. 
                    사용자에게 다시 질문하거나 무엇을 알고 싶냐고 되묻지 마십시오.
                    제공된 [데이터베이스 사례]에 있는 '조치내용'을 즉시 설명하십시오.

                    [작성 수칙]
                    1. 첫 문장은 "조성주 님의 {', '.join(source_info)} 사례를 바탕으로 안내드립니다."로 시작하십시오.
                    2. 사용자의 질문과 관련된 조치 단계를 번호를 매겨 명확하게 작성하십시오.
                    3. 데이터베이스에 있는 텍스트를 최대한 활용하고, 외부 지식은 섞지 마십시오.
                    4. 만약 데이터가 질문과 맞지 않는다면 "유사 사례가 있으나 조치법이 상이합니다."라고 짧게 말하십시오.

                    [데이터베이스 사례]
                    {context_data}
                    
                    [사용자 질문]
                    {user_question}
                    """
                    
                    response = ai_model.generate_content(prompt)
                    st.markdown("### 💡 권장 조치 사항")
                    st.info(response.text)
                    
                    with st.expander("📚 참조한 실제 DB 원본 텍스트 보기"):
                        st.table(past_cases)
                else:
                    st.warning("⚠️ 일치하는 사례가 없습니다. 검색 정밀도를 조절해 보세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 기능 2: 세부 사례 등록 (제조사 & 측정항목 직접 입력) ---
elif mode == "📝 세부 사례 등록":
    st.subheader("📝 신규 노하우 등록 (5대 필드)")
    with st.form("add_form", clear_on_submit=True):
        col1, col2, col3 = st.columns(3)
        
        with col1:
            mfr_options = ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]
            selected_mfr = st.selectbox("제조사", mfr_options)
            custom_mfr = st.text_input("제조사 직접 입력 (필요시)")
            
        with col2:
            model = st.text_input("모델명", placeholder="예: TOC-4200")
            
        with col3:
            item_options = ["TOC", "TP", "TN", "조류", "기타", "직접 입력"]
            selected_item = st.selectbox("측정항목", item_options)
            custom_item = st.text_input("측정항목 직접 입력 (필요시)")
        
        iss = st.text_input("발생 현상", placeholder="예: TOC 값이 갑자기 높아짐")
        sol = st.text_area("조치 내용", placeholder="현장에서 바로 따라 할 수 있는 해결 방법을 적어주세요.")
        
        if st.form_submit_button("지식 베이스 저장"):
            # 직접 입력값 우선 처리 로직
            final_mfr = custom_mfr if selected_mfr == "직접 입력" else selected_mfr
            final_item = custom_item if selected_item == "직접 입력" else selected_item
            
            if final_mfr and model and final_item and iss and sol:
                with st.spinner("자동 벡터화 진행 중..."):
                    combined_text = f"제조사:{final_mfr} 모델:{model} 항목:{final_item} 현상:{iss} 조치:{sol}"
                    vec = get_embedding(combined_text)
                    
                    try:
                        supabase.table("knowledge_base").insert({
                            "manufacturer": final_mfr,
                            "model_name": model,
                            "measurement_item": final_item,
                            "issue": iss,
                            "solution": sol,
                            "embedding": vec
                        }).execute()
                        st.success(f"✅ [{final_mfr}] 사례가 성공적으로 등록되었습니다!")
                    except Exception as e:
                        st.error(f"DB 저장 오류: {e}")
            else:
                st.warning("모든 필드를 입력해 주세요.")

# --- 기능 3: 데이터 관리 ---
elif mode == "🛠️ 데이터 진단":
    st.subheader("🛠️ 데이터 관리")
    res = supabase.table("knowledge_base").select("id, manufacturer, model_name, measurement_item, issue").execute()
    if res.data:
        st.write(f"현재 등록된 지식: {len(res.data)}건")
        st.dataframe(res.data) 
    else:
        st.info("현재 저장된 지식이 없습니다.")
