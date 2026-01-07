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

# [V62] 브랜드 및 측정항목 감지 로직 고도화
def parse_device_info(text):
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술", "로보켐": "백년기술", "shimadzu": "시마즈"}
    items = ["TOC", "TN", "TP", "VOC", "유기물", "질소", "인"]
    
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    found_item = next((i for i in items if i.lower() in text.lower()), None)
    return found_mfr, found_item

# [기능 유지] 게시판 지식을 'knowledge_base'로 정밀 동기화
def sync_qa_to_knowledge(q_id):
    try:
        q_data = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        a_data = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '전문가답변'}] {a['author']} (👍{a.get('likes', 0)}): {a['content']}" for a in a_data]
        full_sync_txt = f"현상: {q_data['content']}\n\n조치 노하우:\n" + "\n".join(ans_list)
        mfr, _ = parse_device_info(q_data['title'] + q_data['content'])
        
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "게시판답변", "manufacturer": mfr if mfr else "커뮤니티",
            "model_name": q_data['category'], "issue": q_data['title'], "solution": full_sync_txt,
            "registered_by": q_data['author'], "embedding": get_embedding(f"{mfr} {q_data['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 및 CSS ---
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
    .tag-qa { background-color: #f5f3ff; color: #5b21b6; }
    .q-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 10px; color: #1e293b; }
    .a-card { background-color: #f8fafc; border-radius: 8px; padding: 12px; margin-top: 8px; border-left: 3px solid #004a99; color: #334155; }
    .reply-card { background-color: #f1f5f9; border-radius: 8px; padding: 10px; margin-left: 30px; border-left: 3px solid #64748b; font-size: 0.9rem; color: #334155; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
selected_mode = st.selectbox("☰ 메뉴 이동", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V62: 3트랙 정밀 엔진) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 시마즈 TOC 값이 올라가")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("3트랙 지식 필터링 중..."):
            try:
                target_mfr, target_item = parse_device_info(user_q)
                query_vec = get_embedding(user_q)
                
                # 후보군 넉넉히 추출
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 25}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 15}).execute().data or []
                
                # [V62 핵심] 3트랙 분류 로직
                t1_field, t2_manual, t3_qa = [], [], []

                for d in exp_cands:
                    is_qa = d.get('qa_id') is not None
                    mfr_match = (not target_mfr) or (target_mfr in d['manufacturer'])
                    
                    if is_qa: # Track 3: 질문게시판 (내용 연관성 중심 + 브랜드 오염 차단)
                        if mfr_match or d['manufacturer'] == "커뮤니티": t3_qa.append(d)
                    else: # Track 1: 현장경험 (브랜드 엄격 일치)
                        if mfr_match: t1_field.append(d)

                for d in man_cands: # Track 2: 매뉴얼 (브랜드 일치 혹은 '기타' 허용)
                    if (not target_mfr) or (target_mfr in d['manufacturer']) or (d['manufacturer'] == "기타"):
                        t2_manual.append(d)

                final_results = t1_field[:5] + t3_qa[:5] + t2_manual[:5]
                
                if final_results:
                    context = ""
                    for d in final_results:
                        src = "질문게시판" if d.get('qa_id') else ("매뉴얼" if 'content' in d else "현장경험")
                        context += f"[{src}/{d['manufacturer']}]: {d.get('solution', d.get('content'))}\n"
                    
                    ans_p = f"""수질 전문가로서 답변하세요.
                    [중요 규칙]
                    1. 질문의 제조사({target_mfr if target_mfr else '전체'})와 일치하지 않는 브랜드의 정보는 **절대** 참고하지 마세요.
                    2. 시마즈를 물었는데 백년기술 데이터만 있다면 "해당 브랜드에 대한 조치 정보가 부족합니다"라고 답하세요.
                    3. 3줄 요약 답변. 데이터: {context} \n 질문: {user_q}"""
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    st.markdown("---")
                    for d in final_results:
                        is_q, is_m = d.get('qa_id') is not None, 'content' in d
                        tag_cls = "tag-qa" if is_q else ("tag-man" if is_m else "tag-exp")
                        tag_name = "질문게시판" if is_q else ("매뉴얼" if is_m else "현장경험")
                        with st.expander(f"[{tag_name}] {d['manufacturer']} | {d['model_name']}"):
                            st.write(d.get('solution', d.get('content')))
                else: st.warning("⚠️ 일치하는 지식을 찾지 못했습니다.")
            except Exception as e: st.error(f"조회 실패: {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("exp_reg", clear_on_submit=True):
        cat = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        c1, c2 = st.columns(2)
        with c1: mfr_choice = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]); manual_mfr = st.text_input("└ 직접 입력")
        with c2: model, m_item = st.text_input("모델명"), st.text_input("측정항목")
        reg, iss, sol = st.text_input("등록자 성함"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("✅ 저장"):
            mfr = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr and iss and sol:
                supabase.table("knowledge_base").insert({"category": cat, "manufacturer": clean_text_for_db(mfr), "model_name": clean_text_for_db(model), "measurement_item": clean_text_for_db(m_item), "issue": clean_text_for_db(iss), "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), "embedding": get_embedding(f"{mfr} {model} {iss} {sol}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서(매뉴얼) 등록 ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록 (768차원)")
    up_file = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_file:
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_file.name:
            with st.spinner("정보 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                preview = "\n".join([p.extract_text() for p in pdf_reader.pages[:3] if p.extract_text()])
                info_res = extract_json(ai_model.generate_content(f"제조사/모델명 JSON 추출: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info_res.get("mfr", "기타"), info_res.get("model", "매뉴얼"), up_file.name
        c1, c2 = st.columns(2)
        f_mfr, f_model = c1.text_input("🏢 제조사", value=st.session_state.s_m), c2.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 매뉴얼 저장 시작"):
            with st.status("📑 저장 중...") as status:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                all_text = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                chunks = [all_text[i:i+1000] for i in range(0, len(all_text), 800)]
                prog_bar = st.progress(0)
                for i, chunk in enumerate(chunks):
                    supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_file.name, "page_num": (i//2)+1, "embedding": get_embedding(chunk)}).execute()
                    prog_bar.progress((i+1)/len(chunks))
                st.success("✅ 등록 완료!"); st.rerun()

# --- 4. 데이터 전체 관리 ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    if st.button("🔄 게시판 전체 지식 재동기화 (브랜드 태깅)"):
        qa_list = supabase.table("qa_board").select("id").execute().data
        for qa in qa_list: sync_qa_to_knowledge(qa['id'])
        st.success("✅ 동기화 완료!")
    st.markdown("---")
    t1, t2 = st.tabs(["📝 경험 관리", "📄 매뉴얼 관리"])
    with t1:
        m_s = st.text_input("🔍 경험 검색 (SSR 등)", key="e_search")
        if m_s:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_s}%,issue.ilike.%{m_s}%,solution.ilike.%{m_s}%").execute()
            for r in res.data:
                with st.expander(f"[{r['manufacturer']}] {r['issue']} ({'Q&A' if r.get('qa_id') else '경험'})"):
                    st.write(r['solution'])
                    if st.button("🗑️ 삭제", key=f"e_{r['id']}"): supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()
    with t2:
        d_s = st.text_input("🔍 매뉴얼 검색")
        if d_s:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{d_s}%,content.ilike.%{d_s}%,file_name.ilike.%{d_s}%").execute()
            for r in res.data:
                with st.expander(f"[{r['manufacturer']}] {r['file_name']}"):
                    st.write(r['content'][:300])
                    if st.button("🗑️ 삭제", key=f"m_{r['id']}"): supabase.table("manual_base").delete().eq("id", r['id']).execute(); st.rerun()

# --- 5. 질문 게시판 ---
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q_data = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q_data['title']}"); st.caption(f"👤 {q_data['author']} | 📅 {q_data['created_at'][:10]}")
        if st.button(f"👍 {q_data.get('likes', 0)}", key="q_lk"):
            supabase.table("qa_board").update({"likes": q_data.get('likes', 0) + 1}).eq("id", q_data['id']).execute()
            sync_qa_to_knowledge(q_data['id']); st.rerun()
        st.info(q_data['content'])
        ans_data = supabase.table("qa_answers").select("*").eq("question_id", q_data['id']).order("created_at").execute().data
        for a in [x for x in ans_data if not x.get('parent_id')]:
            st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
            col_a, col_b = st.columns([0.2, 0.2])
            if col_a.button(f"👍 {a.get('likes', 0)}", key=f"al_{a['id']}"):
                supabase.table("qa_answers").update({"likes": a.get('likes', 0) + 1}).eq("id", a['id']).execute()
                sync_qa_to_knowledge(q_data['id']); st.rerun()
            if col_b.button("💬 답글", key=f"ar_{a['id']}"): st.session_state.reply_target_id = a['id']; st.rerun()
            for r in [x for x in ans_data if x.get('parent_id') == a['id']]:
                st.markdown(f'<div class="reply-card">↳ <b>{r["author"]}</b>: {r["content"]}</div>', unsafe_allow_html=True)
            if st.session_state.get('reply_target_id') == a['id']:
                with st.form(f"f_{a['id']}"):
                    r_auth, r_cont = st.text_input("작성자"), st.text_area("내용")
                    if st.form_submit_button("등록"):
                        supabase.table("qa_answers").insert({"question_id": q_data['id'], "author": r_auth, "content": clean_text_for_db(r_cont), "parent_id": a['id']}).execute()
                        sync_qa_to_knowledge(q_data['id']); st.session_state.reply_target_id = None; st.rerun()
        st.write("---")
        with st.form("new_ans"):
            a_auth, a_cont = st.text_input("작성자"), st.text_area("내용")
            if st.form_submit_button("답변 등록"):
                supabase.table("qa_answers").insert({"question_id": q_data['id'], "author": a_auth, "content": clean_text_for_db(a_cont)}).execute()
                sync_qa_to_knowledge(q_data['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기", use_container_width=True):
            with st.form("q_f"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id']); st.rerun()
        for q in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q['category']}] {q['title']}** (👍 {q.get('likes', 0)})\n👤 {q['author']} | 📅 {q['created_at'][:10]}")
            if c2.button("보기", key=f"q_{q['id']}"): st.session_state.selected_q_id = q['id']; st.rerun()
            st.write("---")
