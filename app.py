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
    # 제어 문자 및 널 문자 제거 (PDF 파싱 오류 방지)
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

# [기능 유지] 게시판 지식 동기화 로직
def sync_qa_to_knowledge(q_id):
    try:
        q_res = supabase.table("qa_board").select("*").eq("id", q_id).execute()
        if not q_res.data: return
        q = q_res.data[0]
        a_res = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute()
        answers_text = "\n".join([f"[{a['author']}의 답변]: {a['content']}" for a in a_res.data])
        full_text = f"제목: {q['title']}\n내용: {q['content']}\n{answers_text}"
        vec = get_embedding(full_text)
        sync_data = {
            "category": "커뮤니티Q&A", "manufacturer": "게시판", "model_name": q['category'],
            "issue": f"QA_ID_{q_id}", "solution": full_text, "registered_by": q['author'],
            "source_type": "QA", "embedding": vec
        }
        existing = supabase.table("knowledge_base").select("id").eq("issue", f"QA_ID_{q_id}").execute()
        if existing.data: supabase.table("knowledge_base").update(sync_data).eq("id", existing.data[0]['id']).execute()
        else: supabase.table("knowledge_base").insert(sync_data).execute()
    except: pass

# --- UI 및 CSS 설정 ---
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
    .tag-qa { background-color: #f5f3ff; color: #5b21b6; }
    .doc-status-card { background-color: #f8fafc; border-radius: 8px; padding: 10px; border-left: 4px solid #92400e; margin-bottom: 8px; color: #1e293b !important; font-weight: 600; }
    .q-card { background-color: #ffffff; border: 1px solid #e2e8f0; border-radius: 10px; padding: 15px; margin-bottom: 10px; color: #1e293b; }
    .a-card { background-color: #f8fafc; border-radius: 8px; padding: 12px; margin-top: 8px; border-left: 3px solid #004a99; color: #334155; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
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
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 코비 TN 물이 넘침")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    if user_q and (search_clicked or user_q):
        with st.spinner("전문 지식 분석 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.15, "match_count": 10}).execute()
            if rpc_res.data:
                context = "\n".join([f"[{c['source_type']}/{c['manufacturer']}/{c['model_name']}]: {c['solution'] if c['source_type'] in ['MANUAL', 'QA'] else c['content']}\n" for c in rpc_res.data])
                ans_p = f"수질 전문가로서 3줄 이내 단답형 답변. 데이터 기반으로 정확히 조치법 제시. 데이터: {context} \n 질문: {user_q}"
                st.info(ai_model.generate_content(ans_p).text)
                st.markdown("---")
                for c in rpc_res.data:
                    is_man, is_qa = c['source_type'] == 'MANUAL', c['source_type'] == 'QA'
                    tag_cls = "tag-qa" if is_qa else ("tag-manual" if is_man else "tag-doc")
                    with st.expander(f"[{c.get('category', '기기점검')}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {tag_cls}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if (is_man or is_qa) else c['content'])
            else: st.warning("⚠️ 일치하는 지식이 없습니다.")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 및 팁 등록")
    with st.form("manual_reg", clear_on_submit=True):
        cat = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        c1, c2 = st.columns(2)
        with c1:
            mfr_choice = st.selectbox("제조사 선택", options=["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            manual_mfr = st.text_input("└ (직접 입력 시)")
        with c2:
            model, m_item = st.text_input("모델명(장소)"), st.text_input("측정항목")
        reg, iss, sol = st.text_input("등록자"), st.text_input("제목"), st.text_area("상세 내용")
        if st.form_submit_button("✅ 저장"):
            mfr = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr and iss and sol:
                vec = get_embedding(f"{cat} {mfr} {model} {m_item} {iss} {sol}")
                supabase.table("knowledge_base").insert({"category": cat, "manufacturer": clean_text_for_db(mfr), "model_name": clean_text_for_db(model), "measurement_item": clean_text_for_db(m_item), "issue": clean_text_for_db(iss), "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), "source_type": "MANUAL", "embedding": vec}).execute()
                st.success("🎉 저장 완료!")

# --- 3. 문서(매뉴얼) 등록 (완벽 개선 버전) ---
elif mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 지식 엔진 업그레이드 (V39)")
    st.info("💡 모바일은 우측 상단 '⋮' -> '다른 브라우저로 열기'를 권장합니다.")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type=["pdf"])
    
    if up_file and st.button("🚀 지식 정제 및 등록 시작"):
        with st.spinner("AI가 매뉴얼을 정밀 분석하고 지식을 구조화하고 있습니다..."):
            try:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                
                # [개선 1] 전체 텍스트 추출 및 1차 정제
                all_text = ""
                for page in pdf_reader.pages:
                    txt = page.extract_text()
                    if txt: all_text += txt + "\n"
                all_text = clean_text_for_db(all_text)
                
                # [개선 2] 문서 전체를 분석하여 정확한 제조사/모델 추출
                meta_p = f"다음 텍스트에서 장비 제조사와 모델명을 JSON으로 추출하세요: {all_text[:3000]}\n결과: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}"
                info_res = extract_json(ai_model.generate_content(meta_p).text)
                mfr = info_res.get("mfr", "기타") if info_res else "기타"
                model = info_res.get("model", "매뉴얼") if info_res else "매뉴얼"

                # [개선 3] 슬라이딩 윈도우 기반 지식 조각화 (Overlap 150자)
                chunk_size = 700
                overlap = 150
                chunks = []
                for i in range(0, len(all_text), chunk_size - overlap):
                    chunks.append(all_text[i:i + chunk_size])

                # [개선 4] AI 지식 정제 처리 (중구난방 텍스트 정리)
                for i, chunk in enumerate(chunks):
                    # AI에게 각 조각을 기술 문서 형태로 재정리 요청
                    clean_p = f"다음은 매뉴얼에서 추출된 날것의 텍스트입니다. 의미 없는 기호나 깨진 글자를 제거하고, 기술적으로 의미 있는 문장으로만 다시 작성하세요.\n\n원문: {chunk}"
                    refined_txt = ai_model.generate_content(clean_p).text
                    
                    vec = get_embedding(refined_txt)
                    supabase.table("knowledge_base").insert({
                        "category": "기기점검", "manufacturer": mfr, "model_name": model,
                        "issue": f"매뉴얼 분석 {i+1}번 조각", "solution": "원문 참조",
                        "content": refined_txt, "registered_by": up_file.name,
                        "source_type": "DOC", "embedding": vec
                    }).execute()
                
                st.success(f"✅ {len(chunks)}개의 고품질 지식 조각이 등록되었습니다!")
                st.rerun()
            except Exception as e: st.error(f"오류: {e}")
    
    st.markdown("---")
    doc_res = supabase.table("knowledge_base").select("registered_by").eq("source_type", "DOC").execute()
    if doc_res.data:
        for m in sorted(list(set([d['registered_by'] for d in doc_res.data]))):
            st.markdown(f'<div class="doc-status-card">📄 {m}</div>', unsafe_allow_html=True)

# --- 4. 데이터 전체 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    st.subheader("🛠️ 지식 데이터 상세 관리")
    m_search = st.text_input("🔍 전수 키워드 검색 (SSR 등)", placeholder="검색어를 입력하세요...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%,content.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            for row in res.data:
                with st.expander(f"[{row.get('category', '지식')}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(f"**제목/현상:** {row['issue']}")
                    st.info(row['solution'] if row['source_type'] in ['MANUAL', 'QA'] else row['content'])
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()

# --- 5. 질문 게시판 (기능 유지) ---
elif mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.selected_q_id:
        if st.button("⬅️ 목록으로 돌아가기"): st.session_state.selected_q_id = None; st.rerun()
        q_res = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute()
        if q_res.data:
            q = q_res.data[0]
            st.subheader(f"❓ {q['title']}")
            st.caption(f"👤 작성자: {q['author']} | 📅 등록일: {q['created_at'][:10]} | 🏷️ 분류: {q['category']}")
            st.markdown(f'<div class="q-card">{q["content"]}</div>', unsafe_allow_html=True)
            a_res = supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute()
            for a in a_res.data:
                st.markdown(f'<div class="a-card"><b>{a["author"]}</b> ({a["created_at"][5:16]}): {a["content"]}</div>', unsafe_allow_html=True)
            with st.form("ans_f", clear_on_submit=True):
                a_auth, a_cont = st.text_input("작성자 성함"), st.text_area("답변 내용")
                if st.form_submit_button("✅ 답변 등록") and a_auth and a_cont:
                    supabase.table("qa_answers").insert({"question_id": q['id'], "author": a_auth, "content": clean_text_for_db(a_cont)}).execute()
                    sync_qa_to_knowledge(q['id'])
                    st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 새로운 질문하기", use_container_width=True):
            with st.form("q_f", clear_on_submit=True):
                q_cat, q_auth, q_title, q_cont = st.selectbox("분류", ["기기이상", "일반문의"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("🚀 질문 올리기") and q_auth and q_title and q_cont:
                    res = supabase.table("qa_board").insert({"author": q_auth, "title": q_title, "content": clean_text_for_db(q_cont), "category": q_cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id'])
                    st.rerun()
        q_list = supabase.table("qa_board").select("*").order("created_at", desc=True).execute()
        for q in q_list.data:
            col1, col2 = st.columns([0.8, 0.2])
            col1.markdown(f"**[{q['category']}] {q['title']}**")
            col1.caption(f"👤 {q['author']} | 📅 {q['created_at'][:10]}")
            if col2.button("보기", key=f"q_{q['id']}"): st.session_state.selected_q_id = q['id']; st.rerun()
            st.write("---")
