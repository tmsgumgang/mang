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

# [V35 추가] 게시판 질문/답변을 AI 검색용 지식으로 변환하여 동기화하는 함수
def sync_qa_to_knowledge(q_id):
    try:
        # 질문 정보 가져오기
        q_res = supabase.table("qa_board").select("*").eq("id", q_id).execute()
        if not q_res.data: return
        q = q_res.data[0]
        
        # 해당 질문에 달린 모든 답변 가져오기
        a_res = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute()
        answers_text = "\n".join([f"[{a['author']}의 답변]: {a['content']}" for a in a_res.data])
        
        # AI 검색용 통합 텍스트 생성
        full_knowledge_text = f"제목: {q['title']}\n질문내용: {q['content']}\n{answers_text}"
        vec = get_embedding(full_knowledge_text)
        
        # knowledge_base 테이블에 QA 타입으로 저장 (이미 있으면 업데이트)
        # issue 필드에 q_id를 넣어 추적 가능하게 함
        sync_data = {
            "category": "커뮤니티Q&A",
            "manufacturer": "게시판",
            "model_name": q['category'],
            "issue": f"QA_ID_{q_id}",
            "solution": full_knowledge_text,
            "registered_by": q['author'],
            "source_type": "QA",
            "embedding": vec
        }
        
        # 기존에 동기화된 데이터가 있는지 확인
        existing = supabase.table("knowledge_base").select("id").eq("issue", f"QA_ID_{q_id}").execute()
        if existing.data:
            supabase.table("knowledge_base").update(sync_data).eq("id", existing.data[0]['id']).execute()
        else:
            supabase.table("knowledge_base").insert(sync_data).execute()
    except Exception as e:
        print(f"지식 동기화 오류: {e}")

# --- UI 설정 ---
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
    .tag-qa { background-color: #f5f3ff; color: #5b21b6; } /* QA용 보라색 태그 */
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

# --- 1. 통합 지식 검색 (QA 데이터 포함) ---
if mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="예: 코비 TN 물이 넘침")
    with col_b: search_clicked = st.button("조회", use_container_width=True)

    if user_q and (search_clicked or user_q):
        with st.spinner("게시판 답변을 포함하여 지식 분석 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.15, "match_count": 10}).execute()
            if rpc_res.data:
                # QA 데이터인 경우 출처 표시를 다르게 구성
                context = ""
                for c in rpc_res.data:
                    prefix = f"[{c['source_type']}/{c['manufacturer']}/{c['model_name']}]"
                    context += f"{prefix}: {c['solution'] if c['source_type'] in ['MANUAL', 'QA'] else c['content']}\n"
                
                ans_p = f"수질 전문가로서 3줄 이내 단답형 답변. 게시판(QA) 답변도 적극 참고. 데이터: {context} \n 질문: {user_q}"
                st.info(ai_model.generate_content(ans_p).text)
                st.markdown("---")
                for c in rpc_res.data:
                    is_man = c['source_type'] == 'MANUAL'
                    is_qa = c['source_type'] == 'QA'
                    tag_cls = "tag-qa" if is_qa else ("tag-tip" if c.get('category') == '맛집/정보' else ("tag-manual" if is_man else "tag-doc"))
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
                    info_res = extract_json(ai_model.generate_content(f"텍스트: {pdf_reader.pages[0].extract_text()[:1500]}\n제조사와 모델명을 JSON: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}").text)
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
    m_search = st.text_input("🔍 데이터 통합 검색 (예: SSR, 펌프, QA)", placeholder="검색어를 입력하세요...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%,content.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            for row in res.data:
                with st.expander(f"[{row.get('category', '기기점검')}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(f"**제목/내용:** {row['issue']}")
                    st.info(row['solution'] if row['source_type'] in ['MANUAL', 'QA'] else row['content'][:300])
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()

# --- 5. 질문 게시판 (지물 자동 동기화 적용) ---
elif mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.selected_q_id:
        if st.button("⬅️ 목록으로 돌아가기"): st.session_state.selected_q_id = None; st.rerun()
        q_res = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute()
        if q_res.data:
            q = q_res.data[0]
            st.subheader(f"❓ {q['title']}")
            st.markdown(f'<div class="q-card">{q["content"]}</div>', unsafe_allow_html=True)
            a_res = supabase.table("qa_answers").select("*").eq("question_id", q['id']).order("created_at").execute()
            for a in a_res.data:
                st.markdown(f'<div class="a-card"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
            
            with st.form("ans_f", clear_on_submit=True):
                a_auth, a_cont = st.text_input("작성자"), st.text_area("답변 내용")
                if st.form_submit_button("✅ 답변 등록"):
                    if a_auth and a_cont:
                        supabase.table("qa_answers").insert({"question_id": q['id'], "author": a_auth, "content": clean_text_for_db(a_cont)}).execute()
                        # [핵심] 답변 등록 시 AI 검색 지식으로 즉시 동기화
                        sync_qa_to_knowledge(q['id'])
                        st.success("답변이 등록되었습니다!"); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 새로운 질문하기", use_container_width=True):
            with st.form("q_f", clear_on_submit=True):
                q_cat, q_auth, q_title, q_cont = st.selectbox("분류", ["기기이상", "일반문의"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("🚀 질문 올리기"):
                    if q_auth and q_title and q_cont:
                        res = supabase.table("qa_board").insert({"author": q_auth, "title": q_title, "content": clean_text_for_db(q_cont), "category": q_cat}).execute()
                        if res.data:
                            # [핵심] 질문 등록 시 AI 검색 지식으로 즉시 동기화
                            sync_qa_to_knowledge(res.data[0]['id'])
                        st.success("질문이 등록되었습니다!"); st.rerun()
        q_list = supabase.table("qa_board").select("*").order("created_at", desc=True).execute()
        for q in q_list.data:
            col1, col2 = st.columns([0.8, 0.2])
            col1.markdown(f"**[{q['category']}] {q['title']}**")
            if col2.button("보기", key=f"q_{q['id']}"): st.session_state.selected_q_id = q['id']; st.rerun()
            st.write("---")
