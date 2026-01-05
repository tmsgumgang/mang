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

# --- [V10] 인증 패스 및 관리 메뉴 검색 기능 통합 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

# 세션 상태 초기화
if 'page_mode' not in st.session_state:
    st.session_state.page_mode = "🔍 검색"
if 'edit_id' not in st.session_state:
    st.session_state.edit_id = None
if 'delete_confirm_id' not in st.session_state:
    st.session_state.delete_confirm_id = None

# [CSS 주입] 상단바 고정 및 UI 최적화
st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999;
        text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.05rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; padding-bottom: 2rem !important; }
    [data-testid="InputInstructions"] { display: none !important; }
    .manage-card {
        background-color: #ffffff; border-radius: 12px;
        padding: 15px; border: 1px solid #e2e8f0;
        margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.05);
    }
    .card-label { font-size: 0.75rem; color: #64748b; font-weight: 600; }
    .card-val { font-size: 0.95rem; color: #1e293b; margin-bottom: 8px; font-weight: 700; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# --- 상단 메뉴 (인증 없이 바로 노출) ---
with st.container():
    col_menu, col_empty = st.columns([0.4, 0.6])
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

# --- 1. 지식 검색 모드 ---
if mode == "🔍 검색":
    with st.form("search_form"):
        user_question = st.text_input("현장 상황", label_visibility="collapsed", placeholder="상황 입력 (예: TOC 값이 너무 높음)")
        if st.form_submit_button("💡 조치법 즉시 찾기") and user_question:
            with st.spinner("금강수계 통합 노하우 분석 중..."):
                query_vec = get_embedding(user_question)
                rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 2}).execute()
                past_cases = rpc_res.data
                if past_cases:
                    case_context = "\n".join([f"사례: {c['manufacturer']} {c['model_name']} - 조치: {c['solution']}" for c in past_cases])
                    prompt = f"당신은 수질 전문가입니다. 데이터를 바탕으로 짧게 답하세요.\n\n{case_context}\n\n질문: {user_question}"
                    response = ai_model.generate_content(prompt)
                    st.info(response.text)
                    st.markdown("---")
                    for c in past_cases:
                        with st.expander(f"📚 {c['manufacturer']} | {c['model_name']}"):
                            st.write(f"**현상:** {c['issue']}\n\n**조치:** {c['solution']}")
                            st.caption(f"등록자: {c.get('registered_by', '공동')}")
                else:
                    st.warning("⚠️ 일치하는 사례가 없습니다.")

# --- 2. 신규 등록 모드 ---
elif mode == "📝 등록":
    st.subheader("📝 신규 노하우 기록")
    with st.form("add_form", clear_on_submit=True):
        col_r1, col_r2 = st.columns(2)
        with col_r1:
            mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            if mfr == "직접 입력": mfr = st.text_input("제조사명 입력")
            reg_name = st.text_input("등록자 성함", placeholder="성함 입력")
        with col_r2:
            model = st.text_input("모델명")
            item = st.selectbox("측정항목", ["TOC", "TP", "TN", "조류", "기타", "직접 입력"])
            if item == "직접 입력": item = st.text_input("측정항목명 입력")
        
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        if st.form_submit_button("✅ 저장"):
            if mfr and model and iss and sol:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg_name}")
                supabase.table("knowledge_base").insert({"manufacturer": mfr, "model_name": model, "measurement_item": item, "issue": iss, "solution": sol, "registered_by": reg_name, "embedding": vec}).execute()
                st.success("🎉 노하우가 공유되었습니다!")
            else:
                st.warning("⚠️ 모든 항목을 입력해 주세요.")

# --- 3. 지식 관리 모드 (내부 검색 기능 추가) ---
elif mode == "🛠️ 관리":
    if st.session_state.edit_id:
        # [수정 폼]
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
                
                c_e1, c_e2 = st.columns(2)
                if c_e1.form_submit_button("💾 저장"):
                    new_vec = get_embedding(f"{e_mfr} {e_model} {e_item} {e_iss} {e_sol} {e_reg}")
                    supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_model, "measurement_item": e_item, "issue": e_iss, "solution": e_sol, "registered_by": e_reg, "embedding": new_vec}).eq("id", st.session_state.edit_id).execute()
                    st.session_state.edit_id = None; st.success("수정 완료!"); st.rerun()
                if c_e2.form_submit_button("❌ 취소"): st.session_state.edit_id = None; st.rerun()
    else:
        # [리스트 모드 + 검색창]
        st.subheader("🛠️ 지식 데이터 관리")
        
        # 관리 메뉴용 검색바
        manage_search = st.text_input("관리 데이터 내 검색", placeholder="제조사, 모델, 항목 등으로 검색...")
        
        res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            
            # 검색어 필터링 로직
            if manage_search:
                mask = df.apply(lambda row: row.astype(str).str.contains(manage_search, case=False).any(), axis=1)
                display_data = df[mask].to_dict('records')
            else:
                display_data = res.data
            
            st.caption(f"검색 결과: {len(display_data)}건")
            
            for item in display_data:
                st.markdown(f"""
                <div class="manage-card">
                    <div class="card-label">{item['manufacturer']} | {item['measurement_item']}</div>
                    <div class="card-val">{item['model_name']}</div>
                    <div style="font-size: 0.85rem; color: #475569;"><b>현상:</b> {item['issue']}</div>
                </div>
                """, unsafe_allow_html=True)
                
                mc1, mc2 = st.columns(2)
                if mc1.button("✏️ 수정", key=f"edit_{item['id']}", use_container_width=True):
                    st.session_state.edit_id = item['id']; st.rerun()
                
                if st.session_state.delete_confirm_id == item['id']:
                    st.error("❗ 삭제하시겠습니까?")
                    mdc1, mdc2 = st.columns(2)
                    if mdc1.button("🔥 승인", key=f"del_ok_{item['id']}", use_container_width=True):
                        supabase.table("knowledge_base").delete().eq("id", item['id']).execute()
                        st.session_state.delete_confirm_id = None; st.rerun()
                    if mdc2.button("🚫 취소", key=f"del_no_{item['id']}", use_container_width=True):
                        st.session_state.delete_confirm_id = None; st.rerun()
                else:
                    if mc2.button("🗑️ 삭제", key=f"del_btn_{item['id']}", use_container_width=True):
                        st.session_state.delete_confirm_id = item['id']; st.rerun()
                st.markdown("---")
        else:
            st.info("데이터가 없습니다.")
