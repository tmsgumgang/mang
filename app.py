import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time

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
    text = text.replace("\u0000", "")
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def get_embedding(text):
    clean_txt = clean_text_for_db(text)
    if not clean_txt: return [0.0] * 768
    result = genai.embed_content(model="models/text-embedding-004", content=clean_txt, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# [V51 추가] 질문에서 제조사 키워드 추출
def detect_manufacturer(user_input):
    mfr_list = ["시마즈", "코비", "백년기술", "케이엔알", "YSI"]
    for mfr in mfr_list:
        if mfr in user_input: return mfr
    return "%" # 검색어에 없으면 전체 검색

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.8rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-exp { background-color: #e0f2fe; color: #0369a1; }
    .tag-man { background-color: #fef3c7; color: #92400e; }
    .doc-status-card { background-color: #f8fafc; border-radius: 8px; padding: 10px; border-left: 4px solid #92400e; margin-bottom: 8px; color: #1e293b !important; font-weight: 600; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (브랜드 필터링 강화) ---
if mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 시마즈 TOC 값이 높음")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("해당 브랜드 지식을 선별 중..."):
            # [V51 핵심] 제조사 키워드 감지
            detected_mfr = detect_manufacturer(user_q)
            query_vec = get_embedding(user_q)
            
            # SQL 함수 호출 시 target_mfr 파라미터 전달
            exp_res = supabase.rpc("match_experience", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 5, "target_mfr": f"%{detected_mfr}%" if detected_mfr != "%" else "%"}).execute()
            man_res = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 5, "target_mfr": f"%{detected_mfr}%" if detected_mfr != "%" else "%"}).execute()
            
            combined_data = (exp_res.data or []) + (man_res.data or [])
            
            if combined_data:
                context = "\n".join([f"[{'경험' if 'solution' in d else '매뉴얼'} / {d['manufacturer']} / {d['model_name']}]: {d['solution'] if 'solution' in d else d['content']}" for d in combined_data])
                
                # [V51 보강] AI에게 명시적으로 제조사 일치 여부 재확인 지시
                ans_p = f"""당신은 수질 장비 전문가입니다. 
                1. 질문에 제조사(예: {detected_mfr})가 명시되었다면 반드시 해당 제조사의 데이터만 참고하세요.
                2. 데이터에 질문과 다른 제조사 정보만 있다면 "해당 제조사의 구체적인 노하우가 없습니다"라고 답하세요.
                3. 답변은 3줄 이내 요약. 
                데이터: {context} \n 질문: {user_q}"""
                st.info(ai_model.generate_content(ans_p).text)
                
                st.markdown("---")
                for d in combined_data:
                    is_e = 'solution' in d
                    tag_cls = "tag-exp" if is_e else "tag-man"
                    with st.expander(f"[{'현장경험' if is_e else '매뉴얼'}] {d['manufacturer']} | {d['model_name']}"):
                        st.markdown(f'<span class="source-tag {tag_cls}">{d["registered_by"] if is_e else d.get("file_name", "매뉴얼")}</span>', unsafe_allow_html=True)
                        st.write(d['solution'] if is_e else d['content'])
            else: st.warning(f"⚠️ {detected_mfr if detected_mfr != '%' else ''} 관련 지식을 찾지 못했습니다.")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("exp_reg", clear_on_submit=True):
        cat = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        c1, c2 = st.columns(2)
        with c1:
            mfr_choice = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            manual_mfr = st.text_input("└ 직접 입력 시")
        with c2: model, m_item = st.text_input("모델명"), st.text_input("측정항목")
        reg, iss, sol = st.text_input("등록자"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("✅ 저장"):
            mfr = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr and iss and sol:
                vec = get_embedding(f"{cat} {mfr} {model} {m_item} {iss} {sol}")
                supabase.table("experience_base").insert({"category": cat, "manufacturer": clean_text_for_db(mfr), "model_name": clean_text_for_db(model), "measurement_item": clean_text_for_db(m_item), "issue": clean_text_for_db(iss), "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), "embedding": vec}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서(매뉴얼) 등록 ---
elif mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록 (768차원)")
    up_file = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_file:
        if 'sug_mfr' not in st.session_state:
            with st.spinner("정보 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                preview = "\n".join([p.extract_text() for p in pdf_reader.pages[:3] if p.extract_text()])
                info_res = extract_json(ai_model.generate_content(f"제조사/모델명 JSON 추출: {preview[:3000]}").text) or {}
                st.session_state.sug_mfr = info_res.get("mfr", "기타")
                st.session_state.sug_model = info_res.get("model", "매뉴얼")

        c1, c2 = st.columns(2)
        f_mfr = c1.text_input("🏢 제조사", value=st.session_state.sug_mfr)
        f_model = c2.text_input("🏷️ 모델명", value=st.session_state.sug_model)

        if st.button("🚀 저장 시작"):
            with st.status("📑 저장 중...") as status:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                all_text = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                chunks = [all_text[i:i+1000] for i in range(0, len(all_text), 800)]
                prog_bar = st.progress(0)
                for i, chunk in enumerate(chunks):
                    clean_chunk = clean_text_for_db(chunk)
                    if len(clean_chunk) < 10: continue
                    supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_model, "content": clean_chunk, "file_name": up_file.name, "page_num": (i//2)+1, "embedding": get_embedding(clean_chunk)}).execute()
                    prog_bar.progress((i+1)/len(chunks))
                st.success("✅ 등록 완료!"); time.sleep(1); del st.session_state.sug_mfr; st.rerun()

    st.markdown("---")
    doc_res = supabase.table("manual_base").select("file_name").execute()
    if doc_res.data:
        for m in sorted(list(set([d['file_name'] for d in doc_res.data]))):
            st.markdown(f'<div class="doc-status-card">📄 {m}</div>', unsafe_allow_html=True)

# --- 4. 데이터 전체 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    t1, t2 = st.tabs(["📝 경험", "📄 매뉴얼"])
    with t1:
        m_s = st.text_input("🔍 경험 검색")
        if m_s:
            res = supabase.table("experience_base").select("*").or_(f"manufacturer.ilike.%{m_s}%,issue.ilike.%{m_s}%,solution.ilike.%{m_s}%").execute()
            for r in res.data:
                with st.expander(f"{r['manufacturer']} | {r['issue']}"):
                    st.write(r['solution'])
                    if st.button("🗑️ 삭제", key=f"e_{r['id']}"): supabase.table("experience_base").delete().eq("id", r['id']).execute(); st.rerun()
    with t2:
        d_s = st.text_input("🔍 매뉴얼 검색")
        if d_s:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{d_s}%,content.ilike.%{d_s}%").execute()
            for r in res.data:
                with st.expander(f"{r['manufacturer']} | {r['model_name']}"):
                    st.write(r['content'][:300])
                    if st.button("🗑️ 삭제", key=f"m_{r['id']}"): supabase.table("manual_base").delete().eq("id", r['id']).execute(); st.rerun()

# --- 5. 질문 게시판 ---
elif mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q['title']}")
        st.caption(f"👤 {q['author']} | 📅 {q['created_at'][:10]}")
        st.info(q['content'])
        for a in supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute().data:
            st.write(f"**{a['author']}**: {a['content']}")
        with st.form("ans_f"):
            auth, cont = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("✅ 등록") and auth and cont:
                supabase.table("qa_answers").insert({"question_id": q['id'], "author": auth, "content": clean_text_for_db(cont)}).execute()
                sync_qa_to_experience(q['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기", use_container_width=True):
            with st.form("q_f"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("🚀 등록") and auth and tit and cont:
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_experience(res.data[0]['id'])
                    st.rerun()
        for q in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q['category']}] {q['title']}**\n\n👤 {q['author']} | 📅 {q['created_at'][:10]}")
            if c2.button("보기", key=f"q_{q['id']}"): st.session_state.selected_q_id = q['id']; st.rerun()
            st.write("---")
