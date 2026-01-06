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

# --- [V34] 질문 게시판(Q&A) 기능 통합 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"
if 'selected_q_id' not in st.session_state: st.session_state.selected_q_id = None

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%;
        background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center;
        box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.8rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; }
    .tag-doc { background-color: #fef3c7; color: #92400e; }
    .tag-tip { background-color: #f0fdf4; color: #166534; }
    .doc-status-card { 
        background-color: #f8fafc; border-radius: 8px; padding: 10px; border-left: 4px solid #92400e; margin-bottom: 8px; 
        font-size: 0.85rem; font-weight: 600; color: #1e293b !important; 
    }
    /* 게시판 카드 스타일 */
    .q-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 10px; color: #1e293b; }
    .a-card { background-color: #f1f5f9; border-radius: 8px; padding: 12px; margin-top: 8px; border-left: 3px solid #004a99; color: #334155; font-size: 0.9rem; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
with st.container():
    menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
    try: current_idx = menu_options.index(st.session_state.page_mode)
    except: current_idx = 0
    selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=current_idx, label_visibility="collapsed")
    if selected_mode != st.session_state.page_mode:
        st.session_state.page_mode = selected_mode
        st.session_state.selected_q_id = None
        st.rerun()

mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 ---
if mode == "🔍 통합 지식 검색":
    col_input, col_btn = st.columns([0.8, 0.2])
    with col_input: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 코비 TN 물이 넘침")
    with col_btn: search_clicked = st.button("조회", use_container_width=True)

    if user_q and (search_clicked or user_q):
        with st.spinner("지식 분석 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.15, "match_count": 10}).execute()
            if rpc_res.data:
                context = "\n".join([f"[{c['source_type']}/{c['manufacturer']}/{c['model_name']}]: {c['solution'] if c['source_type']=='MANUAL' else c['content']}" for c in rpc_res.data])
                ans_p = f"수질 전문가로서 3줄 이내 단답형 답변. 약칭 적극 참고. 데이터: {context} \n 질문: {user_q}"
                st.info(ai_model.generate_content(ans_p).text)
                st.markdown("---")
                for c in rpc_res.data:
                    is_man = c['source_type'] == 'MANUAL'
                    with st.expander(f"[{c.get('category', '기기점검')}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {"tag-manual" if is_man else "tag-doc"}">{c["registered_by"]}</span>', unsafe_allow_html=True)
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
            manual_mfr = st.text_input("└ (직접 입력 시 입력)")
        with c2:
            model = st.text_input("모델명(장소)")
            m_item = st.text_input("측정항목")
        reg, iss, sol = st.text_input("등록자"), st.text_input("제목(현상)"), st.text_area("상세 내용")
        if st.form_submit_button("✅ 저장"):
            mfr = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr and iss and sol:
                vec = get_embedding(f"{cat} {mfr} {model} {m_item} {iss} {sol}")
                supabase.table("knowledge_base").insert({"category": cat, "manufacturer": clean_text_for_db(mfr), "model_name": clean_text_for_db(model), "measurement_item": clean_text_for_db(m_item), "issue": clean_text_for_db(iss), "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), "source_type": "MANUAL", "embedding": vec}).execute()
                st.success("🎉 지식이 등록되었습니다!")

# --- 3. 문서(매뉴얼) 등록 ---
elif mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 기반 지식 등록")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 매뉴얼 분석 시작"):
            with st.spinner("분석 중..."):
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                    info_res = extract_json(ai_model.generate_content(f"텍스트: {pdf_reader.pages[0].extract_text()[:1500]}\n제조사와 모델명을 JSON으로: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}").text)
                    full_txt = ""
                    for pg in pdf_reader.pages:
                        txt = pg.extract_text()
                        if txt: full_txt += clean_text_for_db(txt) + "\n"
                    chunks = [full_txt[i:i+600] for i in range(0, len(full_txt), 600)]
                    for chk in chunks:
                        vec = get_embedding(chk)
                        supabase.table("knowledge_base").insert({"category": "기기점검", "manufacturer": info_res.get("mfr", "기타") if info_res else "기타", "model_name": info_res.get("model", "매뉴얼") if info_res else "매뉴얼", "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chk, "registered_by": up_file.name, "source_type": "DOC", "embedding": vec}).execute()
                    st.success("✅ 등록 완료!"); st.rerun()
                except Exception as e: st.error(f"오류: {e}")
    st.markdown("---")
    doc_res = supabase.table("knowledge_base").select("registered_by").eq("source_type", "DOC").execute()
    if doc_res.data:
        for m in sorted(list(set([d['registered_by'] for d in doc_res.data]))):
            st.markdown(f'<div class="doc-status-card">📄 {m}</div>', unsafe_allow_html=True)

# --- 4. 데이터 전체 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    st.subheader("🛠️ 지식 데이터 상세 관리")
    m_search = st.text_input("🔍 데이터 통합 검색", placeholder="검색어를 입력하세요...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%,content.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            for row in res.data:
                with st.expander(f"[{row.get('category', '기기점검')}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(f"**제목/현상:** {row['issue']}")
                    st.info(row['solution'] if row['source_type']=='MANUAL' else row['content'][:300])
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()

# --- 5. 질문 게시판 (Q&A) 신설 ---
elif mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.selected_q_id:
        # [상세 보기 모드]
        if st.button("⬅️ 목록으로 돌아가기"): st.session_state.selected_q_id = None; st.rerun()
        
        q_res = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute()
        if q_res.data:
            q = q_res.data[0]
            st.subheader(f"❓ {q['title']}")
            st.caption(f"작성자: {q['author']} | 등록일: {q['created_at'][:10]} | 분류: {q['category']}")
            st.markdown(f'<div class="q-card">{q["content"]}</div>', unsafe_allow_html=True)
            
            st.write("---")
            st.write("💬 **답변 목록**")
            a_res = supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute()
            if a_res.data:
                for a in a_res.data:
                    st.markdown(f'<div class="a_author"><b>{a["author"]}</b> ({a["created_at"][5:16]})</div>', unsafe_allow_html=True)
                    st.markdown(f'<div class="a-card">{a["content"]}</div>', unsafe_allow_html=True)
            else: st.info("아직 등록된 답변이 없습니다. 아시는 분은 답변을 남겨주세요!")
            
            with st.form("ans_form", clear_on_submit=True):
                st.write("🙋‍♂️ **답변 달기**")
                a_auth = st.text_input("작성자 성함")
                a_cont = st.text_area("답변 내용을 입력하세요")
                if st.form_submit_button("✅ 답변 등록"):
                    if a_auth and a_cont:
                        supabase.table("qa_answers").insert({"question_id": q['id'], "author": a_auth, "content": clean_text_for_db(a_cont)}).execute()
                        st.success("답변이 등록되었습니다!"); st.rerun()
    else:
        # [목록 모드]
        st.subheader("💬 질문 게시판")
        st.caption("AI 답변으로 해결되지 않는 문제는 동료들에게 직접 물어보세요!")
        
        with st.popover("➕ 새로운 질문하기", use_container_width=True):
            with st.form("q_form", clear_on_submit=True):
                q_cat = st.selectbox("질문 분류", ["기기이상", "시스템오류", "일반문의", "기타"])
                q_auth = st.text_input("작성자 성함")
                q_title = st.text_input("질문 제목")
                q_cont = st.text_area("상세 내용")
                if st.form_submit_button("🚀 질문 올리기"):
                    if q_auth and q_title and q_cont:
                        supabase.table("qa_board").insert({"author": q_auth, "title": q_title, "content": clean_text_for_db(q_cont), "category": q_cat}).execute()
                        st.success("질문이 등록되었습니다!"); st.rerun()
        
        st.write("---")
        q_list = supabase.table("qa_board").select("*").order("created_at", desc=True).execute()
        if q_list.data:
            for q in q_list.data:
                with st.container():
                    st.markdown(f"**[{q['category']}] {q['title']}**")
                    col1, col2 = st.columns([0.7, 0.3])
                    col1.caption(f"👤 {q['author']} | 📅 {q['created_at'][:10]}")
                    if col2.button("상세보기", key=f"q_{q['id']}"):
                        st.session_state.selected_q_id = q['id']; st.rerun()
                st.write("---")
        else: st.info("아직 등록된 질문이 없습니다.")
