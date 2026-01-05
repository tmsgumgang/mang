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

# --- [V15] 스마트 키워드 추출 및 필터링 시스템 ---
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
            if st.button("🛠️ 데이터 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.session_state.edit_id = None; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (스마트 필터링) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="상황을 입력하세요 (예: 시마즈 TOC 펌프 점검)")
    if user_q:
        with st.spinner("질문을 분석하고 관련 지식을 매칭 중..."):
            # [추가] 질문에서 제조사와 모델명을 추출하는 사전 단계
            extraction_prompt = f"""
            다음 질문에서 '제조사'와 '모델명'을 추출하여 JSON으로 응답하세요. 
            언급이 없으면 null로 표시하세요.
            질문: {user_q}
            형식: {{"mfr": "제조사", "model": "모델명"}}
            """
            extraction_res = ai_model.generate_content(extraction_prompt)
            try:
                meta = json.loads(extraction_res.text.replace("```json", "").replace("```", "").strip())
                f_mfr = meta.get("mfr")
                f_model = meta.get("model")
            except:
                f_mfr, f_model = None, None

            query_vec = get_embedding(user_q)
            # 수정된 SQL 함수 호출 (필터 적용)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec, 
                "match_threshold": search_threshold, 
                "match_count": 5,
                "filter_mfr": f_mfr,
                "filter_model": f_model
            }).execute()
            
            cases = rpc_res.data
            if cases:
                context_text = ""
                for c in cases:
                    src = "경험" if c['source_type'] == 'MANUAL' else "이론"
                    context_text += f"[{src} - {c['manufacturer']} {c['model_name']}]: {c['solution'] if src=='경험' else c['content']}\n"
                
                prompt = f"""당신은 수질 전문가입니다. 데이터를 바탕으로 3줄 이내로 답변하세요.
                데이터: {context_text}
                질문: {user_q}"""
                st.info(ai_model.generate_content(prompt).text)
                
                st.markdown("---")
                st.markdown(f"### 📚 {'전체' if not f_mfr else f_mfr} 관련 지식 근거")
                for c in cases:
                    is_manual = c['source_type'] == 'MANUAL'
                    with st.expander(f"[{'👤경험' if is_manual else '📄이론'}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {"tag-manual" if is_manual else "tag-doc"}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if is_manual else c['content'])
            else:
                st.warning("⚠️ 일치하는 제조사나 모델의 사례가 없습니다. 검색 정밀도를 낮추거나 키워드를 조정해 보세요.")

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

# --- 3. 문서 전체 벡터화 (자동 분류 강화) ---
elif mode == "📂 문서 관리":
    st.subheader("📂 매뉴얼 전체 벡터화")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 전체 지식화 시작"):
            with st.spinner("매뉴얼 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                
                # [추가] 매뉴얼 전체에서 제조사와 모델명을 찾는 로직
                first_page_text = pdf_reader.pages[0].extract_text()
                info_prompt = f"다음 텍스트에서 분석기 '제조사'와 '모델명'을 추출하세요. 텍스트: {first_page_text[:1000]}"
                info_res = ai_model.generate_content(info_prompt)
                
                full_text = ""
                for page in pdf_reader.pages:
                    full_text += page.extract_text() + "\n"
                
                chunks = [full_text[i:i+600] for i in range(0, len(full_text), 600)]
                for chunk in chunks:
                    vec = get_embedding(chunk)
                    supabase.table("knowledge_base").insert({
                        "manufacturer": info_res.text.split('\n')[0][:50], # AI 추출값
                        "model_name": info_res.text.split('\n')[-1][:50], 
                        "measurement_item": "전체", "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chunk,
                        "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                    }).execute()
                st.success(f"✅ 분석 완료. {len(chunks)}개의 지식 조각이 분류되어 저장되었습니다.")

# --- 4. 데이터 관리 (상세 정보 확인 및 정정) ---
elif mode == "🛠️ 관리":
    if st.session_state.edit_id:
        # 수정 로직 (V14와 동일)
        res = supabase.table("knowledge_base").select("*").eq("id", st.session_state.edit_id).execute()
        if res.data:
            item = res.data[0]
            with st.form("edit_form"):
                e_mfr = st.text_input("제조사", value=item['manufacturer'])
                e_model = st.text_input("모델명", value=item['model_name'])
                e_sol = st.text_area("내용", value=item['solution'] if item['source_type']=='MANUAL' else item['content'])
                if st.form_submit_button("💾 저장"):
                    new_vec = get_embedding(f"{e_mfr} {e_model} {e_sol}")
                    supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_model, "solution": e_sol if item['source_type']=='MANUAL' else None, "content": e_sol if item['source_type']=='DOC' else None, "embedding": new_vec}).eq("id", item['id']).execute()
                    st.session_state.edit_id = None; st.rerun()
                if st.form_submit_button("❌ 취소"): st.session_state.edit_id = None; st.rerun()
    else:
        st.subheader("🛠️ 데이터 관리")
        res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).execute()
        if res.data:
            df = pd.DataFrame(res.data)
            for _, row in df.iterrows():
                with st.expander(f"[{row['source_type']}] {row['manufacturer']} | {row['model_name']}"):
                    st.write(row['issue'])
                    c1, c2 = st.columns(2)
                    if c1.button("✏️", key=f"e_{row['id']}"): st.session_state.edit_id = row['id']; st.rerun()
                    if c2.button("🗑️", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
