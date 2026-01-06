import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re

# [보안] Streamlit Secrets 연동
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다.")
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

def clean_text_for_db(text):
    if not text: return ""
    return text.replace("\u0000", "").strip()

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# --- [V32] 다크모드 글자색 보정 및 UI 최종 안정화 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"
if 'edit_id' not in st.session_state: st.session_state.edit_id = None

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 12px 0; z-index: 999; text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.8rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; }
    .tag-doc { background-color: #fef3c7; color: #92400e; }
    .tag-tip { background-color: #f0fdf4; color: #166534; }
    /* [수정] 다크모드에서도 글자가 잘 보이도록 색상 강제 지정 */
    .doc-status-card { 
        background-color: #f8fafc; 
        border-radius: 8px; 
        padding: 10px; 
        border-left: 4px solid #92400e; 
        margin-bottom: 8px; 
        font-size: 0.85rem; 
        font-weight: 600;
        color: #1e293b !important; 
    }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션 (셀렉트박스 방식 유지)
with st.container():
    menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"]
    try:
        current_idx = menu_options.index(st.session_state.page_mode)
    except:
        current_idx = 0
    selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=current_idx, label_visibility="collapsed")
    if selected_mode != st.session_state.page_mode:
        st.session_state.page_mode = selected_mode
        st.session_state.edit_id = None
        st.rerun()

mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 ---
if mode == "🔍 통합 지식 검색":
    col_input, col_btn = st.columns([0.8, 0.2])
    with col_input:
        user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 코비 TN 물이 넘침")
    with col_btn:
        search_clicked = st.button("조회", use_container_width=True)

    if user_q and (search_clicked or user_q):
        with st.spinner("전문 지식 분석 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.15, "match_count": 10}).execute()
            cases = rpc_res.data
            
            if cases:
                context = "\n".join([f"[{c['source_type']}/{c['manufacturer']}/{c['model_name']}]: {c['solution'] if c['source_type']=='MANUAL' else c['content']}" for c in cases])
                ans_p = f"""수질 전문가로서 답변하세요. 
                1. 명칭이 달라도(TN <-> HATN-2000) 연관성이 높으면 적극 참고하세요.
                2. 해결책을 3줄 이내 단답형으로 제시하세요.
                데이터: {context} \n 질문: {user_q}"""
                st.info(ai_model.generate_content(ans_p).text)
                
                st.markdown("---")
                for c in cases:
                    is_man = c['source_type'] == 'MANUAL'
                    tag_cls = "tag-tip" if c.get('category') == '맛집/정보' else ("tag-manual" if is_man else "tag-doc")
                    with st.expander(f"[{c.get('category', '기기점검')}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {tag_cls}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if is_man else c['content'])
            else: st.warning("⚠️ 일치하는 지식이 없습니다.")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 및 팁 등록")
    with st.form("manual_reg", clear_on_submit=True):
        cat = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        c1, c2 = st.columns(2)
        with c1:
            mfr_choice = st.selectbox("제조사 선택", options=["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            manual_mfr = st.text_input("└ ('직접 입력' 시에만 입력)")
        with c2:
            model = st.text_input("모델명(장소)")
            m_item = st.text_input("측정항목(TOC, TN 등)")
        
        reg = st.text_input("등록자 성함")
        iss = st.text_input("제목(현상)")
        sol = st.text_area("상세 내용(조치)")
        
        if st.form_submit_button("✅ 지식 저장"):
            mfr_final = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr_final and iss and sol:
                vec = get_embedding(f"{cat} {mfr_final} {model} {m_item} {iss} {sol}")
                supabase.table("knowledge_base").insert({
                    "category": cat, "manufacturer": clean_text_for_db(mfr_final), "model_name": clean_text_for_db(model),
                    "measurement_item": clean_text_for_db(m_item), "issue": clean_text_for_db(iss), 
                    "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), 
                    "source_type": "MANUAL", "embedding": vec
                }).execute()
                st.success("🎉 지식이 성공적으로 등록되었습니다!")

# --- 3. 문서(매뉴얼) 등록 ---
elif mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 기반 지식 등록")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 매뉴얼 분석 시작"):
            with st.spinner("데이터 분석 중..."):
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                    first_pg = pdf_reader.pages[0].extract_text()
                    info_res = extract_json(ai_model.generate_content(f"텍스트: {first_pg[:1500]}\n제조사와 모델명을 JSON으로: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}").text)
                    
                    full_txt = ""
                    for pg in pdf_reader.pages:
                        txt = pg.extract_text()
                        if txt: full_txt += clean_text_for_db(txt) + "\n"
                    
                    chunks = [full_txt[i:i+600] for i in range(0, len(full_txt), 600)]
                    for chk in chunks:
                        vec = get_embedding(chk)
                        supabase.table("knowledge_base").insert({
                            "category": "기기점검", "manufacturer": info_res.get("mfr", "기타") if info_res else "기타", 
                            "model_name": info_res.get("model", "매뉴얼") if info_res else "매뉴얼", 
                            "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chk,
                            "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                        }).execute()
                    st.success("✅ 매뉴얼 등록 완료!")
                    st.rerun()
                except Exception as e: st.error(f"오류: {e}")

    st.markdown("---")
    st.markdown("### 📋 현재 등록된 매뉴얼 현황")
    doc_res = supabase.table("knowledge_base").select("registered_by").eq("source_type", "DOC").execute()
    if doc_res.data:
        for m in sorted(list(set([d['registered_by'] for d in doc_res.data]))):
            # [수정된 부분] 텍스트가 잘 보이도록 HTML 클래스 적용
            st.markdown(f'<div class="doc-status-card">📄 {m}</div>', unsafe_allow_html=True)

# --- 4. 데이터 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    st.subheader("🛠️ 지식 데이터 상세 관리")
    m_search = st.text_input("🔍 관리 대상 검색", placeholder="검색어를 입력하세요...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,category.ilike.%{m_search}%,issue.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            st.caption(f"검색 결과: {len(res.data)}건")
            for row in res.data:
                with st.expander(f"[{row.get('category', '기기점검')}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(f"**제목:** {row['issue']}")
                    st.info(row['solution'] if row['source_type']=='MANUAL' else row['content'][:200])
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"):
                        supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
