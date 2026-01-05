import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다. Streamlit Cloud 설정에서 정보를 입력해 주세요.")
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

# --- [V8] 모바일 최적화 햄버거 메뉴 및 카드 편집 시스템 ---
st.set_page_config(
    page_title="금강수계 AI 챗봇", 
    layout="centered", 
    initial_sidebar_state="collapsed"
)

# 세션 상태 초기화
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🔍 검색"
if 'edit_id' not in st.session_state:
    st.session_state.edit_id = None
if 'delete_confirm_id' not in st.session_state:
    st.session_state.delete_confirm_id = None

# [CSS 주입] 상단바 고정 및 UI 노이즈 제거
st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
        display: flex; align-items: center; justify-content: center;
    }
    .header-title { font-size: 1.05rem; font-weight: 800; }
    
    .main .block-container {
        padding-top: 4.5rem !important;
        padding-bottom: 2rem !important;
        padding-left: 1rem !important;
        padding-right: 1rem !important;
    }
    [data-testid="InputInstructions"] { display: none !important; }

    /* 카드형 UI 스타일 */
    .manage-card {
        background-color: #ffffff; border-radius: 12px;
        padding: 15px; border: 1px solid #e2e8f0;
        margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .card-label { font-size: 0.75rem; color: #64748b; font-weight: 600; }
    .card-val { font-size: 0.95rem; color: #1e293b; margin-bottom: 8px; font-weight: 700; }
    </style>
    """, unsafe_allow_html=True)

# --- 상단 메인 헤더 & 네비게이션 버튼 ---
st.markdown('<div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>', unsafe_allow_html=True)

# 헤더 좌측에 햄버거 메뉴 역할을 하는 popover 배치
with st.container():
    col_menu, col_empty = st.columns([0.3, 0.7])
    with col_menu:
        with st.popover("☰ 메뉴"):
            if st.button("🔍 지식 검색", use_container_width=True):
                st.session_state.page_mode = "🔍 검색"
                st.session_state.edit_id = None
                st.rerun()
            if st.button("📝 신규 등록", use_container_width=True):
                st.session_state.page_mode = "📝 등록"
                st.rerun()
            if st.button("🛠️ 지식 관리", use_container_width=True):
                st.session_state.page_mode = "🛠️ 관리"
                st.session_state.edit_id = None
                st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 지식 검색 (홈 화면 기본) ---
if mode == "🔍 검색":
    with st.form("search_form", clear_on_submit=False):
        user_question = st.text_input("현장 상황", label_visibility="collapsed", placeholder="상황 입력 (예: HATP TP mv 0)")
        submit_button = st.form_submit_button("💡 조치법 즉시 찾기")
    
    if (submit_button or user_question) and user_question:
        with st.spinner("금강수계 통합 노하우 분석 중..."):
            try:
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {
                    "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 2 
                }).execute()
                
                past_cases = rpc_res.data
                if past_cases:
                    case_context = "\n".join([f"사례: {c['manufacturer']} {c['model_name']} - 등록자: {c.get('registered_by', '공동')} - 조치: {c['solution']}" for c in past_cases])
                    prompt = f"당신은 금강수계 수질 전문가입니다. 다음 데이터를 바탕으로 질문에 짧고 명확하게 답하세요.\n\n{case_context}\n\n질문: {user_question}"
                    response = ai_model.generate_content(prompt)
                    
                    st.info(response.text)
                    st.markdown("---")
                    for c in past_cases:
                        with st.expander(f"📚 {c['manufacturer']} | {c['model_name']} 상세"):
                            st.write(f"**현상:** {c['issue']}")
                            st.success(f"**조치:** {c['solution']}")
                            st.caption(f"등록자: {c.get('registered_by', '공동')} | 일치도: {c['similarity']*100:.1f}%")
                else:
                    st.warning("⚠️ 일치하는 사례가 없습니다. 동료들을 위해 지식을 등록해 주세요.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

# --- 2. 신규 사례 등록 ---
elif mode == "📝 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
        if mfr == "직접 입력": mfr = st.text_input("제조사명 입력")
        reg_name = st.text_input("등록자 성명", placeholder="성함 입력")
        
        model = st.text_input("모델명")
        item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타", "직접 입력"])
        if item == "직접 입력": item = st.text_input("측정항목명 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        
        if st.form_submit_button("✅ 저장"):
            if mfr and model and item and iss and sol and reg_name:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg_name}")
                supabase.table("knowledge_base").insert({
                    "manufacturer": mfr, "model_name": model, "measurement_item": item,
                    "issue": iss, "solution": sol, "registered_by": reg_name, "embedding": vec
                }).execute()
                st.success("🎉 노하우가 공유되었습니다!")
            else:
                st.warning("⚠️ 모든 항목을 입력해 주세요.")

# --- 3. 지식 관리 (모바일 최적화 수정/삭제 시스템) ---
elif mode == "🛠️ 관리":
    # A. 수정 모드인 경우 (수정 폼 출력)
    if st.session_state.edit_id:
        st.subheader("✏️ 지식 수정하기")
        res = supabase.table("knowledge_base").select("*").eq("id", st.session_state.edit_id).execute()
        if res.data:
            orig = res.data[0]
            with st.form("edit_form"):
                e_mfr = st.text_input("제조사", value=orig['manufacturer'])
                e_model = st.text_input("모델명", value=orig['model_name'])
                e_item = st.text_input("측정항목", value=orig['measurement_item'])
                e_iss = st.text_input("발생 현상", value=orig['issue'])
                e_sol = st.text_area("조치 내용", value=orig['solution'])
                e_reg = st.text_input("등록자", value=orig.get('registered_by', ''))
                
                col_e1, col_e2 = st.columns(2)
                if col_e1.form_submit_button("💾 수정사항 저장"):
                    new_vec = get_embedding(f"{e_mfr} {e_model} {e_item} {e_iss} {e_sol} {e_reg}")
                    supabase.table("knowledge_base").update({
                        "manufacturer": e_mfr, "model_name": e_model, "measurement_item": e_item,
                        "issue": e_iss, "solution": e_sol, "registered_by": e_reg, "embedding": new_vec
                    }).eq("id", st.session_state.edit_id).execute()
                    st.session_state.edit_id = None
                    st.success("수정 완료!")
                    st.rerun()
                if col_e2.form_submit_button("❌ 취소"):
                    st.session_state.edit_id = None
                    st.rerun()
    
    # B. 리스트 모드 (카드형 리스트 출력)
    else:
        st.subheader("🛠️ 지식 데이터 관리")
        res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
        
        if res.data:
            for item in res.data:
                with st.container():
                    st.markdown(f"""
                    <div class="manage-card">
                        <div class="card-label">{item['manufacturer']} | {item['measurement_item']}</div>
                        <div class="card-val">{item['model_name']}</div>
                        <div style="font-size: 0.85rem; color: #475569;"><b>현상:</b> {item['issue']}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    c1, c2 = st.columns(2)
                    # 수정 버튼
                    if c1.button("✏️ 수정", key=f"edit_{item['id']}", use_container_width=True):
                        st.session_state.edit_id = item[ 'id']
                        st.rerun()
                    
                    # 삭제 로직 (안전장치)
                    if st.session_state.delete_confirm_id == item['id']:
                        st.error("❗ 정말 삭제하시겠습니까?")
                        dc1, dc2 = st.columns(2)
                        if dc1.button("🔥 삭제승인", key=f"del_ok_{item['id']}", use_container_width=True):
                            supabase.table("knowledge_base").delete().eq("id", item['id']).execute()
                            st.session_state.delete_confirm_id = None
                            st.success("삭제되었습니다.")
                            st.rerun()
                        if dc2.button("🚫 취소", key=f"del_no_{item['id']}", use_container_width=True):
                            st.session_state.delete_confirm_id = None
                            st.rerun()
                    else:
                        if c2.button("🗑️ 삭제", key=f"del_btn_{item['id']}", use_container_width=True):
                            st.session_state.delete_confirm_id = item['id']
                            st.rerun()
                    st.markdown("---")
        else:
            st.info("저장된 데이터가 없습니다.")
