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
    if not clean_txt: return [0.0] * 1536
    result = genai.embed_content(model="models/text-embedding-004", content=clean_txt, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# [이원화] 게시판 지식을 'experience_base'로 동기화
def sync_qa_to_experience(q_id):
    try:
        q_res = supabase.table("qa_board").select("*").eq("id", q_id).execute()
        if not q_res.data: return
        q = q_res.data[0]
        a_res = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute()
        ans_txt = "\n".join([f"[{a['author']}의 답변]: {a['content']}" for a in a_res.data])
        full_txt = f"제목: {q['title']}\n내용: {q['content']}\n{ans_txt}"
        vec = get_embedding(full_txt)
        
        sync_data = {
            "category": "Q&A", "manufacturer": "커뮤니티", "model_name": q['category'],
            "issue": q['title'], "solution": full_txt, "registered_by": q['author'],
            "embedding": vec
        }
        existing = supabase.table("experience_base").select("id").eq("issue", q['title']).execute()
        if existing.data: supabase.table("experience_base").update(sync_data).eq("id", existing.data[0]['id']).execute()
        else: supabase.table("experience_base").insert(sync_data).execute()
    except: pass

# --- UI 설정 및 CSS ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"
if 'selected_q_id' not in st.session_state: st.session_state.selected_q_id = None

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
    .q-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 10px; color: #1e293b; }
    .a-card { background-color: #f8fafc; border-radius: 8px; padding: 12px; margin-top: 8px; border-left: 3px solid #004a99; color: #334155; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.session_state.selected_q_id = None
    st.rerun()

mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 ---
if mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 코비 TN 물이 넘침")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("지식을 정밀 분석 중..."):
            query_vec = get_embedding(user_q)
            exp_res = supabase.rpc("match_experience", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 5}).execute()
            man_res = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 5}).execute()
            combined_data = (exp_res.data or []) + (man_res.data or [])
            
            if combined_data:
                context = "\n".join([f"[{'경험' if 'solution' in d else '매뉴얼'} / {d['manufacturer']} / {d['model_name']}]: {d['solution'] if 'solution' in d else d['content']}" for d in combined_data])
                ans_p = f"수질 전문가 답변. 3줄 요약.\n데이터: {context} \n 질문: {user_q}"
                st.info(ai_model.generate_content(ans_p).text)
                st.markdown("---")
                for d in combined_data:
                    is_e = 'solution' in d
                    tag_cls = "tag-exp" if is_e else "tag-man"
                    with st.expander(f"[{'경험' if is_e else '매뉴얼'}] {d['manufacturer']} | {d['model_name']}"):
                        st.markdown(f'<span class="source-tag {tag_cls}">{d["registered_by"] if is_e else d.get("file_name", "매뉴얼")}</span>', unsafe_allow_html=True)
                        st.write(d['solution'] if is_e else d['content'])
            else: st.warning("⚠️ 일치하는 지식이 없습니다.")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록 (경험 지식)")
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
                st.success("🎉 경험 지식이 등록되었습니다!")

# --- 3. 문서(매뉴얼) 등록 (NoneType 오류 방지 보강) ---
elif mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록 (원문 지식)")
    st.warning("💡 대용량 PDF는 초기 분석에 시간이 걸립니다. 버튼 클릭 후 잠시만 기다려 주세요.")
    up_file = st.file_uploader("PDF 업로드", type=["pdf"])
    
    if up_file and st.button("🚀 매뉴얼 저장 시작"):
        with st.status("📑 매뉴얼 분석 중...", expanded=True) as status:
            try:
                status.write("1. PDF 텍스트 추출 중...")
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                all_text = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                
                if not all_text.strip():
                    st.error("텍스트를 추출할 수 없는 PDF입니다."); st.stop()
                
                status.write("2. 장비 메타데이터 분석 중...")
                info_res = extract_json(ai_model.generate_content(f"제조사와 모델명 추출(JSON): {all_text[:3000]}").text)
                
                # [오류 방어] NoneType object has no attribute 'get' 방지
                if info_res is None: info_res = {}
                mfr = info_res.get("mfr", "기타")
                model = info_res.get("model", "매뉴얼")

                status.write("3. 지식 저장 중...")
                chunks = [all_text[i:i+1000] for i in range(0, len(all_text), 800)]
                prog_bar, success_count = st.progress(0), 0

                for i, chunk in enumerate(chunks):
                    clean_chunk = clean_text_for_db(chunk)
                    if len(clean_chunk) < 10: continue
                    vec = get_embedding(clean_chunk)
                    res = supabase.table("manual_base").insert({
                        "manufacturer": mfr, "model_name": model, "content": clean_chunk, 
                        "file_name": up_file.name, "page_num": (i//2)+1, "embedding": vec
                    }).execute()
                    if res.data: success_count += 1
                    prog_bar.progress((i+1)/len(chunks))
                
                status.update(label="✅ 저장 완료!", state="complete", expanded=False)
                st.success(f"🎉 {success_count}개의 지식이 등록되었습니다!"); time.sleep(1); st.rerun()
            except Exception as e: st.error(f"❌ 처리 중 오류 발생: {e}")

    st.markdown("---")
    doc_res = supabase.table("manual_base").select("file_name").execute()
    if doc_res.data:
        st.markdown("### 📋 등록된 매뉴얼 현황")
        for m in sorted(list(set([d['file_name'] for d in doc_res.data]))):
            st.markdown(f'<div class="doc-status-card">📄 {m}</div>', unsafe_allow_html=True)

# --- 4. 데이터 전체 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    tab1, tab2 = st.tabs(["📝 경험 관리", "📄 매뉴얼 관리"])
    with tab1:
        m_search = st.text_input("🔍 경험 검색 (SSR 등)", key="e_s")
        if m_search:
            res = supabase.table("experience_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%").execute()
            for r in res.data:
                with st.expander(f"{r['manufacturer']} | {r['issue']}"):
                    st.write(r['solution'])
                    if st.button("🗑️ 삭제", key=f"e_{r['id']}"): supabase.table("experience_base").delete().eq("id", r['id']).execute(); st.rerun()
    with tab2:
        d_search = st.text_input("🔍 매뉴얼 검색", key="m_s")
        if d_search:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{d_search}%,content.ilike.%{d_search}%").execute()
            for r in res.data:
                with st.expander(f"{r['manufacturer']} | {r['model_name']} (일부)"):
                    st.write(r['content'][:300])
                    if st.button("🗑️ 삭제", key=f"m_{r['id']}"): supabase.table("manual_base").delete().eq("id", r['id']).execute(); st.rerun()

# --- 5. 질문 게시판 ---
elif mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.selected_q_id:
        if st.button("⬅️ 목록으로 돌아가기"): st.session_state.selected_q_id = None; st.rerun()
        q_res = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute()
        if q_res.data:
            q = q_res.data[0]
            st.subheader(f"❓ {q['title']}")
            st.caption(f"👤 작성자: {q['author']} | 📅 등록일: {q['created_at'][:10]}")
            st.markdown(f'<div class="q-card">{q["content"]}</div>', unsafe_allow_html=True)
            a_res = supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute()
            for a in a_res.data:
                st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
            with st.form("ans_f", clear_on_submit=True):
                a_auth, a_cont = st.text_input("작성자"), st.text_area("답변")
                if st.form_submit_button("✅ 답변 등록") and a_auth and a_cont:
                    supabase.table("qa_answers").insert({"question_id": q['id'], "author": a_auth, "content": clean_text_for_db(a_cont)}).execute()
                    sync_qa_to_experience(q['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 새로운 질문하기", use_container_width=True):
            with st.form("q_f", clear_on_submit=True):
                q_cat, q_auth, q_title, q_cont = st.selectbox("분류", ["기기이상", "일반문의"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("🚀 질문 올리기") and q_auth and q_title and q_cont:
                    res = supabase.table("qa_board").insert({"author": q_auth, "title": q_title, "content": clean_text_for_db(q_cont), "category": q_cat}).execute()
                    if res.data: sync_qa_to_experience(res.data[0]['id'])
                    st.success("질문이 등록되었습니다!"); st.rerun()
        q_list = supabase.table("qa_board").select("*").order("created_at", desc=True).execute()
        for q in q_list.data:
            col1, col2 = st.columns([0.8, 0.2])
            col1.markdown(f"**[{q['category']}] {q['title']}**")
            col1.caption(f"👤 {q['author']} | 📅 {q['created_at'][:10]}")
            if col2.button("보기", key=f"q_{q['id']}"): st.session_state.selected_q_id = q['id']; st.rerun()
            st.write("---")
