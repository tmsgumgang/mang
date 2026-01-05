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

# --- [V14] 검색 요약 강화 및 관리 상호작용 UI ---
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
    
    /* 출처 태그 */
    .source-tag { font-size: 0.75rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 8px; display: inline-block; }
    .tag-manual { background-color: #e0f2fe; color: #0369a1; border: 1px solid #bae6fd; }
    .tag-doc { background-color: #fef3c7; color: #92400e; border: 1px solid #fde68a; }
    
    /* 관리 카드 스타일 */
    .manage-item { border-left: 5px solid #004a99; padding-left: 10px; margin-bottom: 5px; }
    [data-testid="InputInstructions"] { display: none !important; }
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
            if st.button("🛠️ 데이터 전체 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.session_state.edit_id = None; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (간결한 답변 최적화) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="상황을 입력하세요 (예: TN 값이 0으로 나옴)")
    if user_q:
        with st.spinner("최적의 조치법 요약 중..."):
            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 5}).execute()
            cases = rpc_res.data
            
            if cases:
                # [개선] 짧고 간결한 답변을 위한 프롬프트 강화
                context_text = ""
                for c in cases:
                    if c['source_type'] == 'MANUAL':
                        context_text += f"[실전경험]: {c['solution']}\n"
                    else:
                        context_text += f"[매뉴얼 이론]: {c['content']}\n"
                
                prompt = f"""
                당신은 수질 전문가입니다. 제공된 데이터를 바탕으로 질문에 답하세요.
                [규칙]
                1. 핵심 조치법을 3줄 이내의 단답형 리스트로 가장 먼저 제시하세요.
                2. 불필요한 인사말이나 긴 설명은 생략하세요.
                
                데이터: {context_text}
                질문: {user_q}
                """
                response = ai_model.generate_content(prompt)
                
                # 결과 출력
                st.subheader("💡 핵심 조치 요약")
                st.success(response.text)
                
                st.markdown("---")
                st.markdown("### 📚 상세 근거 (클릭하여 확인)")
                for c in cases:
                    is_manual = c['source_type'] == 'MANUAL'
                    tag_class = "tag-manual" if is_manual else "tag-doc"
                    tag_text = f"👤 {c['registered_by']} 님의 경험" if is_manual else f"📄 {c['registered_by']} 매뉴얼 발췌"
                    
                    with st.expander(f"{c['manufacturer']} | {c['model_name']} ({'경험' if is_manual else '이론'})"):
                        st.markdown(f'<span class="source-tag {tag_class}">{tag_text}</span>', unsafe_allow_html=True)
                        if is_manual:
                            st.write(f"**상황:** {c['issue']}")
                            st.info(f"**해결:** {c['solution']}")
                        else:
                            st.write(f"**매뉴얼 내용:**\n{c['content']}")
            else:
                st.warning("⚠️ 일치하는 사례가 없습니다.")

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
        if st.form_submit_button("✅ 저장"):
            if mfr and model and iss and sol:
                vec = get_embedding(f"{mfr} {model} {item} {iss} {sol} {reg}")
                supabase.table("knowledge_base").insert({"manufacturer": mfr, "model_name": model, "measurement_item": item, "issue": iss, "solution": sol, "registered_by": reg, "source_type": "MANUAL", "embedding": vec}).execute()
                st.success("🎉 실전 지식이 등록되었습니다!")

# --- 3. 문서 전체 벡터화 ---
elif mode == "📂 문서 관리":
    st.subheader("📂 매뉴얼 전체 벡터화")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 전체 지식화 시작"):
            with st.spinner("매뉴얼 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                full_text = ""
                for page in pdf_reader.pages:
                    full_text += page.extract_text() + "\n"
                
                chunks = [full_text[i:i+600] for i in range(0, len(full_text), 600)]
                for chunk in chunks:
                    vec = get_embedding(chunk)
                    supabase.table("knowledge_base").insert({
                        "manufacturer": "제조사 미상", "model_name": "매뉴얼 참조", "measurement_item": "전체",
                        "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chunk,
                        "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                    }).execute()
                st.success(f"✅ {len(chunks)}개의 지식 조각 저장 완료!")

# --- 4. 데이터 전체 관리 (상호작용 강화) ---
elif mode == "🛠️ 관리":
    if st.session_state.edit_id:
        # [수정 모드]
        res = supabase.table("knowledge_base").select("*").eq("id", st.session_state.edit_id).execute()
        if res.data:
            item = res.data[0]
            with st.form("edit_form"):
                st.write(f"📍 데이터 수정 (출처: {item['source_type']})")
                e_mfr = st.text_input("제조사", value=item['manufacturer'])
                e_model = st.text_input("모델명", value=item['model_name'])
                e_iss = st.text_input("현상", value=item['issue'])
                e_sol = st.text_area("조치/내용", value=item['solution'] if item['source_type'] == 'MANUAL' else item['content'])
                
                c1, c2 = st.columns(2)
                if c1.form_submit_button("💾 저장"):
                    new_vec = get_embedding(f"{e_mfr} {e_model} {e_iss} {e_sol}")
                    update_data = {"manufacturer": e_mfr, "model_name": e_model, "issue": e_iss, "embedding": new_vec}
                    if item['source_type'] == 'MANUAL': update_data["solution"] = e_sol
                    else: update_data["content"] = e_sol
                    
                    supabase.table("knowledge_base").update(update_data).eq("id", item['id']).execute()
                    st.session_state.edit_id = None; st.rerun()
                if c2.form_submit_button("❌ 취소"):
                    st.session_state.edit_id = None; st.rerun()
    else:
        # [리스트 모드]
        st.subheader("🛠️ 데이터 상세 관리")
        manage_search = st.text_input("항목 검색", placeholder="모델명, 등록자, 내용 검색...")
        res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            display_data = df[df.apply(lambda r: manage_search.lower() in str(r).lower(), axis=1)] if manage_search else df
            
            for _, row in display_data.iterrows():
                # [개선] expnader를 사용하여 클릭 시 상세 내용을 볼 수 있도록 수정
                title = f"[{'👤경험' if row['source_type']=='MANUAL' else '📄이론'}] {row['manufacturer']} | {row['model_name']}"
                with st.expander(title):
                    st.write(f"**출처:** {row['registered_by']}")
                    st.write(f"**현상:** {row['issue']}")
                    if row['source_type'] == 'MANUAL':
                        st.info(f"**조치 내용:**\n{row['solution']}")
                    else:
                        st.warning(f"**매뉴얼 원문:**\n{row['content']}")
                    
                    btn_col1, btn_col2 = st.columns(2)
                    if btn_col1.button("✏️ 수정", key=f"edit_{row['id']}"):
                        st.session_state.edit_id = row['id']; st.rerun()
                    if btn_col2.button("🗑️ 삭제", key=f"del_{row['id']}"):
                        supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
