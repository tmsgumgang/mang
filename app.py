import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io

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

# --- [V13] 매뉴얼 벡터 탐색(RAG) 엔진 통합 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")

if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 검색"

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
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

# 네비게이션
with st.container():
    col_m, _ = st.columns([0.4, 0.6])
    with col_m:
        with st.popover("☰ 메뉴 선택"):
            if st.button("🔍 통합 지식 검색", use_container_width=True): st.session_state.page_mode = "🔍 검색"; st.rerun()
            if st.button("📝 현장 노하우 등록", use_container_width=True): st.session_state.page_mode = "📝 등록" ; st.rerun()
            if st.button("📂 문서 전체 벡터화", use_container_width=True): st.session_state.page_mode = "📂 문서 관리"; st.rerun()
            if st.button("🛠️ 데이터 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (경험 + 매뉴얼 전체 탐색) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="고장 상황을 상세히 입력하세요")
    if user_q:
        with st.spinner("경험 지식과 매뉴얼 이론을 통합 검색 중..."):
            try:
                query_vec = get_embedding(user_q)
                # 상위 5개를 가져와서 더 풍부한 답변 재료로 사용
                rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 5}).execute()
                cases = rpc_res.data
                
                if cases:
                    # AI 프롬프트 구성 (경험과 매뉴얼 원문을 구분하여 전달)
                    context_text = ""
                    for c in cases:
                        if c['source_type'] == 'MANUAL':
                            context_text += f"[실전경험 - 등록자 {c['registered_by']}]: {c['solution']}\n"
                        else:
                            context_text += f"[매뉴얼 이론 - 출처 {c['registered_by']}]: {c['content']}\n"
                    
                    prompt = f"""
                    당신은 수질 전문가입니다. 제공된 [참조 데이터]를 바탕으로 사용자의 질문에 답변하세요.
                    동료의 실전 경험과 매뉴얼의 이론적 근거를 균형 있게 설명하세요.
                    
                    [참조 데이터]
                    {context_text}
                    
                    질문: {user_q}
                    """
                    response = ai_model.generate_content(prompt)
                    st.info(response.text)
                    
                    st.markdown("---")
                    st.markdown("### 📚 상세 참조 데이터")
                    for c in cases:
                        is_manual = c['source_type'] == 'MANUAL'
                        tag_class = "tag-manual" if is_manual else "tag-doc"
                        tag_text = f"👤 {c['registered_by']} 님의 경험" if is_manual else f"📄 {c['registered_by']} 매뉴얼 발췌"
                        
                        with st.expander(f"{c['manufacturer']} | {c['model_name']} ({tag_text})"):
                            st.markdown(f'<span class="source-tag {tag_class}">{tag_text}</span>', unsafe_allow_html=True)
                            if is_manual:
                                st.write(f"**현상:** {c['issue']}\n\n**조치:** {c['solution']}")
                            else:
                                st.write(f"**매뉴얼 원문:**\n{c['content']}")
                else:
                    st.warning("⚠️ 일치하는 사례나 매뉴얼 내용이 없습니다.")
            except Exception as e:
                st.error(f"검색 오류: {e}")

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
        if st.form_submit_button("✅ 노하우 저장"):
            if mfr and model and iss and sol:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg}")
                supabase.table("knowledge_base").insert({"manufacturer": mfr, "model_name": model, "measurement_item": item, "issue": iss, "solution": sol, "registered_by": reg, "source_type": "MANUAL", "embedding": vec}).execute()
                st.success("🎉 실전 지식이 등록되었습니다!")

# --- 3. 문서 관리 (매뉴얼 전체 벡터화 로직) ---
elif mode == "📂 문서 관리":
    st.subheader("📂 매뉴얼 전체 벡터화 (RAG)")
    st.write("30페이지 이상의 대형 매뉴얼도 전체를 쪼개어 학습시킵니다.")
    up_file = st.file_uploader("매뉴얼 PDF 업로드", type="pdf")
    
    if up_file:
        if st.button("🚀 매뉴얼 전체 지식화 시작"):
            with st.spinner("매뉴얼 텍스트를 정밀하게 쪼개고 벡터화하는 중..."):
                try:
                    # 1. PDF 텍스트 전체 추출
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                    full_text = ""
                    for page in pdf_reader.pages:
                        full_text += page.extract_text() + "\n"
                    
                    # 2. 텍스트 청킹 (약 500자 단위로 쪼갬)
                    chunk_size = 500
                    chunks = [full_text[i:i+chunk_size] for i in range(0, len(full_text), chunk_size)]
                    
                    # 3. 각 청크별로 벡터 생성 및 저장
                    for i, chunk in enumerate(chunks):
                        vec = get_embedding(chunk)
                        supabase.table("knowledge_base").insert({
                            "manufacturer": "제조사 미상", # 매뉴얼에서 추출하도록 개선 가능
                            "model_name": "매뉴얼 참조",
                            "measurement_item": "전체",
                            "issue": "매뉴얼 본문",
                            "solution": "매뉴얼 원문 참조",
                            "content": chunk, # 원문 저장
                            "registered_by": up_file.name,
                            "source_type": "DOC",
                            "embedding": vec
                        }).execute()
                        
                    st.success(f"✅ 매뉴얼을 {len(chunks)}개의 지식 조각으로 분해하여 저장 완료!")
                except Exception as e:
                    st.error(f"처리 중 오류 발생: {e}")

# --- 4. 데이터 관리 ---
elif mode == "🛠️ 관리":
    st.subheader("🛠️ 데이터 관리")
    res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
    if res.data:
        df = pd.DataFrame(res.data)
        manage_q = st.text_input("목록 검색", placeholder="검색어를 입력하세요...")
        disp = df[df.apply(lambda r: manage_q.lower() in str(r).lower(), axis=1)] if manage_q else df
        for _, item in disp.iterrows():
            tag = "👤 경험" if item['source_type'] == 'MANUAL' else "📄 이론"
            st.markdown(f'<div class="manage-card"><small>{tag} | {item["registered_by"]}</small><br><b>{item["manufacturer"]} {item["model_name"]}</b></div>', unsafe_allow_html=True)
            if st.button("🗑️ 삭제", key=f"d_{item['id']}"):
                supabase.table("knowledge_base").delete().eq("id", item['id']).execute()
                st.rerun()
