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

# --- [V12] PDF 텍스트 추출 및 AI 구조화 로직 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 검색"
if 'extracted_data' not in st.session_state: st.session_state.extracted_data = []

# [CSS 주입] 상단바 및 카드 디자인
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
    .source-tag { font-size: 0.75rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 8px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
    .tag-doc { background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    .manage-card { background-color: #ffffff; border-radius: 12px; padding: 15px; border: 1px solid #e2e8f0; margin-bottom: 10px; }
    [data-testid="InputInstructions"] { display: none !important; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# --- 네비게이션 햄버거 메뉴 ---
with st.container():
    col_m, _ = st.columns([0.4, 0.6])
    with col_m:
        with st.popover("☰ 메뉴 선택"):
            if st.button("🔍 통합 지식 검색", use_container_width=True): st.session_state.page_mode = "🔍 검색"; st.rerun()
            if st.button("📝 현장 노하우 등록", use_container_width=True): st.session_state.page_mode = "📝 등록" ; st.rerun()
            if st.button("📂 문서 지식 추출", use_container_width=True): st.session_state.page_mode = "📂 문서 관리"; st.rerun()
            if st.button("🛠️ 데이터 전체 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="고장 상황을 입력하세요 (예: TN mv 0 발생)")
    if user_q:
        with st.spinner("경험과 이론을 결합하여 분석 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 3}).execute()
            cases = rpc_res.data
            if cases:
                prompt = f"당신은 수질 전문가입니다. 데이터를 바탕으로 짧게 조치법을 요약하세요.\n\n데이터: {cases}\n\n질문: {user_q}"
                st.info(ai_model.generate_content(prompt).text)
                for c in cases:
                    is_manual = c['source_type'] == 'MANUAL'
                    tag_class = "tag-manual" if is_manual else "tag-doc"
                    tag_text = f"👤 {c['registered_by']} 님의 실전 경험" if is_manual else f"📄 {c['registered_by']} 매뉴얼 발췌"
                    with st.expander(f"{c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {tag_class}">{tag_text}</span>', unsafe_allow_html=True)
                        st.write(f"**현상:** {c['issue']}\n\n**조치:** {c['solution']}")

# --- 2. 현장 노하우 등록 ---
elif mode == "📝 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("manual_reg", clear_on_submit=True):
        mfr = st.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "직접 입력"])
        reg = st.text_input("등록자 성함")
        model = st.text_input("모델명")
        item = st.text_input("측정항목")
        iss = st.text_input("발생 현상")
        sol = st.text_area("조치 내용")
        if st.form_submit_button("✅ 조치법 저장"):
            if mfr and model and iss and sol:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg}")
                supabase.table("knowledge_base").insert({"manufacturer": mfr, "model_name": model, "measurement_item": item, "issue": iss, "solution": sol, "registered_by": reg, "source_type": "MANUAL", "embedding": vec}).execute()
                st.success("🎉 노하우가 등록되었습니다!")

# --- 3. 문서 지식 관리 (PDF AI 추출 엔진) ---
elif mode == "📂 문서 관리":
    st.subheader("📂 매뉴얼 PDF 조치법 추출")
    up_file = st.file_uploader("매뉴얼 PDF 업로드", type="pdf")
    
    if up_file:
        if st.button("🚀 AI 분석 시작 (PDF 읽기)"):
            with st.spinner("AI가 매뉴얼의 텍스트를 분석하여 조치법을 추출하고 있습니다..."):
                # 1. PDF 텍스트 추출
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                full_text = ""
                for page in pdf_reader.pages[:10]: # 비용 및 속도를 위해 상위 10페이지만 분석
                    full_text += page.extract_text()
                
                # 2. Gemini에게 구조화된 데이터 요청
                prompt = f"""
                당신은 수질분석기 매뉴얼 분석가입니다. 다음 텍스트에서 '고장 증상'과 '해결 방법'을 찾아 JSON 형식으로 리스트를 만드세요.
                반드시 아래 키값을 가진 리스트로만 응답하세요:
                [
                  {{"manufacturer": "제조사명", "model_name": "모델명", "measurement_item": "측정항목", "issue": "고장현상", "solution": "조치내용"}}
                ]
                텍스트: {full_text}
                """
                response = ai_model.generate_content(prompt)
                try:
                    # JSON 문자열 추출 및 파싱
                    json_str = response.text.replace("```json", "").replace("```", "").strip()
                    st.session_state.extracted_data = json.loads(json_str)
                    st.success(f"✅ 문서에서 {len(st.session_state.extracted_data)}개의 조치법을 찾았습니다!")
                except:
                    st.error("AI가 데이터를 구조화하는 데 실패했습니다. 다시 시도해 주세요.")

    # 추출된 데이터가 있을 경우 리뷰 화면 표시
    if st.session_state.extracted_data:
        st.markdown("### 🔍 추출 결과 검토")
        for i, item in enumerate(st.session_state.extracted_data):
            with st.container():
                st.markdown(f'<div class="manage-card"><b>{item["manufacturer"]} {item["model_name"]}</b><br>{item["issue"]}</div>', unsafe_allow_html=True)
                st.caption(f"조치법: {item['solution']}")
        
        if st.button("💾 위 내용 모두 지식 베이스에 저장"):
            with st.spinner("DB 저장 및 벡터화 진행 중..."):
                for item in st.session_state.extracted_data:
                    vec = get_embedding(f"{item['manufacturer']} {item['model_name']} {item['measurement_item']} {item['issue']} {item['solution']}")
                    supabase.table("knowledge_base").insert({
                        "manufacturer": item['manufacturer'], "model_name": item['model_name'],
                        "measurement_item": item['measurement_item'], "issue": item['issue'],
                        "solution": item['solution'], "registered_by": up_file.name,
                        "source_type": "DOC", "embedding": vec
                    }).execute()
                st.session_state.extracted_data = []
                st.success("🎉 모든 이론 지식이 성공적으로 등록되었습니다!")
                st.rerun()

# --- 4. 통합 데이터 관리 ---
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 데이터 관리")
    res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        manage_q = st.text_input("목록 검색", placeholder="검색어를 입력하세요...")
        disp = df[df.apply(lambda r: manage_q.lower() in str(r).lower(), axis=1)] if manage_q else df
        for _, item in disp.iterrows():
            tag = "👤 경험" if item['source_type'] == 'MANUAL' else "📄 이론"
            st.markdown(f'<div class="manage-card"><small>{tag} | {item["registered_by"]}</small><br><b>{item["manufacturer"]} {item["model_name"]}</b><br>{item["issue"]}</div>', unsafe_allow_html=True)
            c1, c2 = st.columns(2)
            if c1.button("✏️ 수정", key=f"e_{item['id']}"): st.session_state.edit_id = item['id']; st.rerun()
            if c2.button("🗑️ 삭제", key=f"d_{item['id']}"): supabase.table("knowledge_base").delete().eq("id", item['id']).execute(); st.rerun()
