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

# --- [V29] 헤더 고정 및 AI 답변 확신 로직 강화 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 검색"
if 'edit_id' not in st.session_state: st.session_state.edit_id = None

# [헤더 고정]
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
    .main .block-container { padding-top: 4.5rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; }
    .tag-doc { background-color: #fef3c7; color: #92400e; }
    .tag-tip { background-color: #f0fdf4; color: #166534; }
    .doc-status-card { background-color: #f8fafc; border-radius: 8px; padding: 10px; border-left: 4px solid #92400e; margin-bottom: 8px; font-size: 0.85rem; font-weight: 600; color: #334155; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
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

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.15, 0.05) # 더 넓게 검색하도록 기본값 하향
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (지능형 유연 답변 강화) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="상황을 입력하세요 (예: TN 물이 넘침)")
    if user_q:
        with st.spinner("전문 지식을 분석하여 최적의 해결책을 도출 중..."):
            query_vec = get_embedding(user_q)
            
            # 넓은 후보군 확보 (10개)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 10
            }).execute()
            
            cases = rpc_res.data
            if cases:
                context = ""
                for c in cases:
                    src = "경험" if c['source_type'] == 'MANUAL' else "매뉴얼"
                    context += f"[{src} / 제조사:{c['manufacturer']} / 모델:{c['model_name']} / 항목:{c.get('measurement_item','-')}]: {c['solution'] if src=='경험' else c['content']}\n"
                
                # [핵심] 답변의 확신을 높이는 프롬프트 개편
                ans_p = f"""
                당신은 수질 측정 장비 전문가입니다. 제공된 [참조 데이터]를 바탕으로 질문에 답하세요.
                
                [답변 지침 - 절대 준수]
                1. '직접적인 정보가 없다'는 말은 웬만하면 피하세요. 유사한 제조사, 모델, 측정항목이 있다면 그것을 정답으로 간주하고 조치법을 설명하세요.
                2. 예를 들어 사용자가 'TN'에 대해 물었는데 데이터에 'HATN-2000'이 있다면, 같은 장비로 인식하고 조치법을 알려주세요.
                3. 질문의 '현상(예: 물이 넘침)'과 데이터의 '현상'이 일치하면, 제조사가 다르더라도 "유사 사례인 [제조사]의 조치법을 참고하면..."이라며 답변을 제공하세요.
                4. 답변은 3줄 이내, 단답형 리스트로 명확하게 하세요.
                
                [참조 데이터]
                {context}
                
                질문: {user_q}
                """
                response = ai_model.generate_content(ans_p)
                st.info(response.text)
                
                st.markdown("---")
                st.markdown("### 📚 상세 근거 데이터 (유사도순)")
                for c in cases:
                    is_man = c['source_type'] == 'MANUAL'
                    tag_cls = "tag-tip" if c.get('category') == '맛집/정보' else ("tag-manual" if is_man else "tag-doc")
                    with st.expander(f"[{c.get('category', '기기점검')}] {c['manufacturer']} | {c['model_name']} ({c.get('measurement_item','전체')})"):
                        st.markdown(f'<span class="source-tag {tag_cls}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if is_man else c['content'])
            else:
                st.warning("⚠️ 관련 지식을 찾을 수 없습니다. 키워드를 더 단순하게 입력해 보세요.")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 등록":
    st.subheader("📝 현장 노하우 및 팁 등록")
    with st.form("manual_reg", clear_on_submit=True):
        cat = st.selectbox("1. 분류", ["기기점검", "현장꿀팁", "맛집/정보"])
        col_i1, col_i2 = st.columns(2)
        with col_i1:
            mfr_choice = st.selectbox("2. 제조사(지역)", options=["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            manual_mfr = st.text_input("└ ('직접 입력' 시 입력)")
        with col_i2:
            model = st.text_input("3. 모델명(장소)", placeholder="예: APK2950W")
            m_item = st.text_input("4. 측정항목", placeholder="예: TOC, TN 등")
        
        reg = st.text_input("5. 등록자 성함")
        st.write("---")
        iss = st.text_input("6. 제목(현상)")
        sol = st.text_area("7. 상세 내용(조치)")
        
        if st.form_submit_button("✅ 지식 저장"):
            mfr_final = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            if mfr_final and iss and sol:
                vec = get_embedding(f"{cat} {mfr_final} {model} {m_item} {iss} {sol}")
                supabase.table("knowledge_base").insert({
                    "category": cat, "manufacturer": clean_text_for_db(mfr_final), 
                    "model_name": clean_text_for_db(model), "measurement_item": clean_text_for_db(m_item),
                    "issue": clean_text_for_db(iss), "solution": clean_text_for_db(sol), 
                    "registered_by": clean_text_for_db(reg), "source_type": "MANUAL", "embedding": vec
                }).execute()
                st.success(f"🎉 지식이 등록되었습니다!")

# --- 3. 문서(매뉴얼) 등록 ---
elif mode == "📂 문서 관리":
    st.subheader("📄 문서(매뉴얼) 기반 지식 등록")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 매뉴얼 분석 및 등록 시작"):
            with st.spinner("매뉴얼 내용을 지식 조각으로 분해 중..."):
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
                    st.success(f"✅ 매뉴얼 등록 완료!")
                    st.rerun()
                except Exception as e: st.error(f"오류: {e}")

    st.markdown("---")
    st.markdown("### 📋 현재 등록된 매뉴얼 현황")
    doc_res = supabase.table("knowledge_base").select("registered_by").eq("source_type", "DOC").execute()
    if doc_res.data:
        manual_list = sorted(list(set([d['registered_by'] for d in doc_res.data])))
        for m_name in manual_list:
            st.markdown(f'<div class="doc-status-card">📄 {m_name}</div>', unsafe_allow_html=True)

# --- 4. 데이터 관리 ---
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 지식 데이터 상세 관리")
    m_search = st.text_input("🔍 관리 대상 검색", placeholder="모델명, 제조사, 카테고리 등 검색...")
    if m_search:
        res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,category.ilike.%{m_search}%,issue.ilike.%{m_search}%").order("created_at", desc=True).execute()
        if res.data:
            st.caption(f"검색 결과: {len(res.data)}건")
            for row in res.data:
                with st.expander(f"[{row.get('category', '기기점검')}] {row['manufacturer']} | {row['model_name']} ({row.get('measurement_item', '전체')})"):
                    st.write(f"**현상/제목:** {row['issue']}")
                    if row['source_type'] == 'MANUAL': st.info(row['solution'])
                    else: st.info(row['content'][:200] + "...")
                    if st.button("🗑️ 삭제", key=f"d_{row['id']}"):
                        supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
