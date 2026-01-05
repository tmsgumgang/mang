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
    result = genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")
    return result['embedding']

# --- [V11] 이원화 지식 관리 및 UI 최적화 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 검색"
if 'edit_id' not in st.session_state: st.session_state.edit_id = None
if 'delete_confirm_id' not in st.session_state: st.session_state.delete_confirm_id = None

# [CSS 주입] 
st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.05rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    
    /* 출처 태그 스타일 */
    .source-tag { font-size: 0.75rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 8px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; } /* 👤 경험 */
    .tag-doc { background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }    /* 📄 이론 */
    
    .manage-card { background-color: #ffffff; border-radius: 12px; padding: 15px; border: 1px solid #e2e8f0; margin-bottom: 10px; }
    [data-testid="InputInstructions"] { display: none !important; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# --- 상단 햄버거 메뉴 ---
with st.container():
    col_menu, _ = st.columns([0.4, 0.6])
    with col_menu:
        with st.popover("☰ 메뉴 선택"):
            if st.button("🔍 통합 지식 검색", use_container_width=True): st.session_state.page_mode = "🔍 검색"; st.rerun()
            if st.button("📝 현장 노하우 등록", use_container_width=True): st.session_state.page_mode = "📝 등록"; st.rerun()
            if st.button("📂 문서 지식 추출", use_container_width=True): st.session_state.page_mode = "📂 문서 관리"; st.rerun()
            if st.button("🛠️ 데이터 전체 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (이원화 결과 노출) ---
if mode == "🔍 검색":
    with st.form("search_form"):
        user_q = st.text_input("현장 상황", label_visibility="collapsed", placeholder="상황 입력 (예: TOC 값 이상 상승)")
        if st.form_submit_button("💡 해결책 찾기") and user_q:
            with st.spinner("경험과 이론을 통합 분석 중..."):
                query_vec = get_embedding(user_q)
                rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 3}).execute()
                cases = rpc_res.data
                if cases:
                    prompt = f"당신은 수질 전문가입니다. 데이터를 바탕으로 답변하세요.\n\n데이터: {cases}\n\n질문: {user_q}"
                    st.info(ai_model.generate_content(prompt).text)
                    st.markdown("---")
                    for c in cases:
                        is_manual = c['source_type'] == 'MANUAL'
                        tag_class = "tag-manual" if is_manual else "tag-doc"
                        tag_icon = "👤" if is_manual else "📄"
                        tag_text = f"{tag_icon} {c['registered_by']} 님의 경험" if is_manual else f"{tag_icon} {c['registered_by']} 매뉴얼 이론"
                        
                        with st.expander(f"{c['manufacturer']} | {c['model_name']}"):
                            st.markdown(f'<span class="source-tag {tag_class}">{tag_text}</span>', unsafe_allow_html=True)
                            st.write(f"**현상:** {c['issue']}\n\n**조치:** {c['solution']}")
                else:
                    st.warning("⚠️ 검색된 사례가 없습니다.")

# --- 2. 현장 노하우 등록 (경험 지식) ---
elif mode == "📝 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("manual_reg", clear_on_submit=True):
        col_m1, col_m2 = st.columns(2)
        with col_m1:
            mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            if mfr == "직접 입력": mfr = st.text_input("제조사 직접입력")
            reg = st.text_input("등록자 성명")
        with col_m2:
            model = st.text_input("모델명")
            item = st.text_input("측정항목")
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        if st.form_submit_button("✅ 경험 지식 저장"):
            vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg}")
            supabase.table("knowledge_base").insert({"manufacturer": mfr, "model_name": model, "measurement_item": item, "issue": iss, "solution": sol, "registered_by": reg, "source_type": "MANUAL", "embedding": vec}).execute()
            st.success("🎉 동료들과 지식이 공유되었습니다!")

# --- 3. 문서 지식 관리 (이론 지식 추출용) ---
elif mode == "📂 문서 관리":
    st.subheader("📂 매뉴얼 기반 지식 추출")
    st.info("PDF를 업로드하면 AI가 조치법을 자동 추출하여 이론 지식으로 등록합니다.")
    up_file = st.file_uploader("매뉴얼 PDF 업로드", type="pdf")
    if up_file:
        st.warning("🚀 [개발 참고] 실제 PDF 파싱을 위해서는 'PyPDF2' 등의 라이브러리 연동이 필요합니다. 현재는 구조적 프레임워크만 준비되었습니다.")
        if st.button("🔍 문서 분석 시작"):
            st.write(f"파일명: {up_file.name} 분석 준비 완료")

# --- 4. 통합 데이터 관리 ---
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 전체 데이터 관리")
    sq = st.text_input("검색 필터", placeholder="제조사, 등록자 등 검색...")
    res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        disp = df[df.apply(lambda r: sq.lower() in str(r).lower(), axis=1)] if sq else df
        for _, item in disp.iterrows():
            is_manual = item['source_type'] == 'MANUAL'
            tag_text = "👤 경험" if is_manual else "📄 이론"
            st.markdown(f'<div class="manage-card"><small>{tag_text} | {item["registered_by"]}</small><br><b>{item["manufacturer"]} {item["model_name"]}</b><br>{item["issue"]}</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("✏️ 수정", key=f"edit_{item['id']}"): st.session_state.edit_id = item['id']; st.rerun()
            if c2.button("🗑️ 삭제", key=f"del_{item['id']}"): supabase.table("knowledge_base").delete().eq("id", item['id']).execute(); st.rerun()
