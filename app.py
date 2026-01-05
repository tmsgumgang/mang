import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json

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

# --- [V23] 카테고리 분류 시스템 통합 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 검색"
if 'edit_id' not in st.session_state: st.session_state.edit_id = None

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
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; }
    .tag-doc { background-color: #fef3c7; color: #92400e; }
    .tag-tip { background-color: #f0fdf4; color: #166534; } /* 맛집/정보용 초록색 태그 */
    .manage-card { background-color: #ffffff; border-radius: 12px; padding: 15px; border: 1px solid #e2e8f0; margin-bottom: 10px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 통합 지식뱅크</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
with st.container():
    col_menu, _ = st.columns([0.4, 0.6])
    with col_menu:
        with st.popover("☰ 메뉴 선택"):
            if st.button("🔍 통합 지식 검색", use_container_width=True): st.session_state.page_mode = "🔍 검색"; st.rerun()
            if st.button("📝 현장 노하우 등록", use_container_width=True): st.session_state.page_mode = "📝 등록" ; st.rerun()
            if st.button("📄 문서(매뉴얼) 등록", use_container_width=True): st.session_state.page_mode = "📂 문서 관리"; st.rerun()
            if st.button("🛠️ 데이터 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.session_state.edit_id = None; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (카테고리 인지형) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="장비 문제나 현장 정보를 물어보세요")
    if user_q:
        with st.spinner("지식 베이스 탐색 중..."):
            # 의도 및 키워드 추출
            intent_p = f"질문: {user_q} \n 위 질문의 성격(기기수리/생활정보), 제조사, 모델명을 JSON으로 답하세요. 형식: {{\"type\":\"기기수리/생활정보\", \"mfr\":\"제조사\", \"model\":\"모델명\"}}"
            try:
                intent_res = ai_model.generate_content(intent_p)
                meta = json.loads(intent_res.text.replace("```json", "").replace("```", "").strip())
                q_type, f_mfr, f_model = meta.get("type"), meta.get("mfr"), meta.get("model")
            except: q_type, f_mfr, f_model = "기기수리", None, None

            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 5, "filter_mfr": f_mfr, "filter_model": f_model
            }).execute()
            
            if rpc_res.data:
                cases = rpc_res.data
                # 질문 성격과 데이터 카테고리 일치 여부 확인 (노이즈 제거)
                if q_type == "기기수리":
                    cases = [c for c in cases if c.get('category') != '맛집/정보']
                
                if cases:
                    context = "\n".join([f"[{c.get('category', '지식')}] {c['manufacturer']} {c['model_name']}: {c['solution'] if c['source_type']=='MANUAL' else c['content']}" for c in cases])
                    ans_p = f"데이터: {context}\n질문: {user_q}\n위 데이터를 바탕으로 질문에 맞는 핵심 내용을 3줄 이내로 답변하세요."
                    st.info(ai_model.generate_content(ans_p).text)
                    st.markdown("---")
                    for c in cases:
                        is_man = c['source_type'] == 'MANUAL'
                        tag_cls = "tag-tip" if c.get('category') == '맛집/정보' else ("tag-manual" if is_man else "tag-doc")
                        with st.expander(f"[{c.get('category', '지식')}] {c['manufacturer']} | {c['model_name']}"):
                            st.markdown(f'<span class="source-tag {tag_cls}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                            st.write(c['solution'] if is_man else c['content'])
                else: st.warning("⚠️ 관련 정보를 찾을 수 없습니다.")

# --- 2. 현장 노하우 등록 (카테고리 선택 추가) ---
elif mode == "📝 등록":
    st.subheader("📝 현장 노하우 및 팁 등록")
    with st.form("manual_reg", clear_on_submit=True):
        cat = st.selectbox("1. 분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        col1, col2 = st.columns(2)
        with col1:
            mfr_choice = st.selectbox("2. 제조사(지역)", options=["시마즈", "코비", "백년기술", "케이엔알", "직접 입력"])
            manual_mfr = st.text_input("└ ('직접 입력' 시 입력)")
        with col2:
            model = st.text_input("3. 모델명(장소)", placeholder="예: APK2950W / 옥천센터")
        
        reg = st.text_input("4. 등록자 성함")
        iss = st.text_input("5. 제목(현상)", placeholder="예: 시료 도입 펌프 소음 / 영동 점심 추천")
        sol = st.text_area("6. 상세 내용(조치)", placeholder="노하우를 상세히 적어주세요.")
        
        if st.form_submit_button("✅ 지식 저장"):
            mfr_final = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr_final and iss and sol:
                vec = get_embedding(f"{cat} {mfr_final} {model} {iss} {sol}")
                supabase.table("knowledge_base").insert({
                    "category": cat, "manufacturer": clean_text_for_db(mfr_final), 
                    "model_name": clean_text_for_db(model), "issue": clean_text_for_db(iss), 
                    "solution": clean_text_for_db(sol), "registered_by": clean_text_for_db(reg), 
                    "source_type": "MANUAL", "embedding": vec
                }).execute()
                st.success(f"🎉 [{cat}] 지식이 성공적으로 등록되었습니다!")

# --- 3. 문서(매뉴얼) 등록 (기본 카테고리 '기기점검') ---
elif mode == "📂 문서 관리":
    st.subheader("📄 문서(매뉴얼) 기반 지식 등록")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 매뉴얼 분석 및 등록"):
            with st.spinner("매뉴얼 분석 중..."):
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                    first_pg = pdf_reader.pages[0].extract_text()
                    info_res = json.loads(ai_model.generate_content(f"텍스트: {first_pg[:1500]}\n제조사와 모델명을 JSON으로: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}").text.replace("```json", "").replace("```", "").strip())
                    
                    full_txt = ""
                    for pg in pdf_reader.pages:
                        txt = pg.extract_text()
                        if txt: full_txt += clean_text_for_db(txt) + "\n"
                    
                    chunks = [full_txt[i:i+600] for i in range(0, len(full_txt), 600)]
                    for chk in chunks:
                        vec = get_embedding(chk)
                        supabase.table("knowledge_base").insert({
                            "category": "기기점검", "manufacturer": info_res.get("mfr", "기타"), 
                            "model_name": info_res.get("model", "매뉴얼"), 
                            "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chk,
                            "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                        }).execute()
                    st.success(f"✅ 매뉴얼 등록 완료!")
                    st.rerun()
                except Exception as e: st.error(f"오류: {e}")

# --- 4. 데이터 관리 (카테고리 표시) ---
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 지식 데이터 상세 관리")
    m_search = st.text_input("🔍 관리 대상 검색", placeholder="모델명, 제조사, 카테고리 등 검색...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,category.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            for row in res.data:
                with st.expander(f"[{row.get('category', '미분류')}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(f"**현상/제목:** {row['issue']}")
                    if row['source_type'] == 'MANUAL': st.info(row['solution'])
                    else: st.info(row['content'][:200] + "...")
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"):
                        supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
