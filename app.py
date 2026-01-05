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

# --- [V17] 검색 로직 엄격화 및 관리 화면 검색 필터 강제 ---
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
            if st.button("📄 문서(매뉴얼) 등록", use_container_width=True): st.session_state.page_mode = "📂 문서 관리"; st.rerun()
            if st.button("🛠️ 데이터 관리", use_container_width=True): st.session_state.page_mode = "🛠️ 관리"; st.session_state.edit_id = None; st.rerun()

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (엄격한 기종 매칭) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="상황을 입력하세요 (예: TN 2060 동작불량)")
    if user_q:
        with st.spinner("해당 장비의 관련 지식을 정밀 검색 중..."):
            # 질문에서 기종 정보를 추출하여 필터로 활용
            ext_p = f"질문: {user_q} \n 위 질문에서 장비 제조사와 모델명을 추출하여 JSON(mfr, model)으로만 답하세요. 없으면 null."
            try:
                ext_res = ai_model.generate_content(ext_p)
                meta = json.loads(ext_res.text.replace("```json", "").replace("```", "").strip())
                f_mfr, f_model = meta.get("mfr"), meta.get("model")
            except:
                f_mfr, f_model = None, None

            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec, "match_threshold": search_threshold, 
                "match_count": 5, "filter_mfr": f_mfr, "filter_model": f_model
            }).execute()
            
            cases = rpc_res.data
            if cases:
                # [강화] 추출된 메타가 있다면, 실제 결과에서도 한 번 더 검증 (엉뚱한 장비 배제)
                filtered_cases = []
                for c in cases:
                    if f_model and f_model.lower() not in c['model_name'].lower() and c['model_name'] != "매뉴얼 참조":
                        continue
                    filtered_cases.append(c)
                
                if not filtered_cases: filtered_cases = cases # 필터링 결과가 아예 없으면 기본 검색 유지

                context = "\n".join([f"[{c['source_type']}] {c['manufacturer']} {c['model_name']}: {c['solution'] if c['source_type']=='MANUAL' else c['content']}" for c in filtered_cases])
                ans_p = f"데이터: {context}\n질문: {user_q}\n위 데이터를 바탕으로 3줄 이내로 단답형 조치법을 알려주세요."
                st.info(ai_model.generate_content(ans_p).text)
                
                st.markdown("---")
                for c in filtered_cases:
                    is_man = c['source_type'] == 'MANUAL'
                    with st.expander(f"[{'👤경험' if is_man else '📄이론'}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {"tag-manual" if is_man else "tag-doc"}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if is_man else c['content'])
            else:
                st.warning("⚠️ 관련 사례가 없습니다.")

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
                st.success("🎉 노하우가 공유되었습니다!")

# --- 3. 문서 관리 (명칭 변경: 문서(매뉴얼) 등록) ---
elif mode == "📂 문서 관리":
    st.subheader("📄 문서(매뉴얼) 기반 지식 등록")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    if up_file:
        if st.button("🚀 매뉴얼 지식화 시작"):
            with st.spinner("매뉴얼의 내용을 분석하여 지식 베이스에 통합 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                first_pg = pdf_reader.pages[0].extract_text()
                info_p = f"텍스트: {first_pg[:1000]}\n위 텍스트에서 제조사와 모델명을 찾아 2줄로 답하세요."
                info_res = ai_model.generate_content(info_p).text.split('\n')
                
                full_txt = ""
                for pg in pdf_reader.pages: full_txt += pg.extract_text() + "\n"
                chunks = [full_txt[i:i+600] for i in range(0, len(full_txt), 600)]
                for chk in chunks:
                    vec = get_embedding(chk)
                    supabase.table("knowledge_base").insert({
                        "manufacturer": info_res[0][:50], "model_name": info_res[-1][:50], 
                        "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chk,
                        "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                    }).execute()
                st.success(f"✅ {len(chunks)}개의 지식 조각이 등록되었습니다.")

# --- 4. 데이터 관리 (검색 후 노출 방식으로 개편) ---
elif mode == "🛠️ 관리":
    if st.session_state.edit_id:
        # [수정 모드]
        res = supabase.table("knowledge_base").select("*").eq("id", st.session_state.edit_id).execute()
        if res.data:
            it = res.data[0]
            with st.form("edit_f"):
                e_mfr = st.text_input("제조사", value=it['manufacturer'])
                e_model = st.text_input("모델명", value=it['model_name'])
                e_sol = st.text_area("내용", value=it['solution'] if it['source_type']=='MANUAL' else it['content'])
                if st.form_submit_button("💾 저장"):
                    new_v = get_embedding(f"{e_mfr} {e_model} {e_sol}")
                    supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_model, "solution": e_sol if it['source_type']=='MANUAL' else None, "content": e_sol if it['source_type']=='DOC' else None, "embedding": new_v}).eq("id", it['id']).execute()
                    st.session_state.edit_id = None; st.rerun()
                if st.form_submit_button("❌ 취소"): st.session_state.edit_id = None; st.rerun()
    else:
        # [리스트 모드: 검색창 필수]
        st.subheader("🛠️ 지식 데이터 관리")
        st.info("관리할 데이터를 아래 검색창에 입력해 주세요 (모델명, 제조사 등).")
        m_search = st.text_input("🔍 데이터 검색", placeholder="검색어를 입력하면 리스트가 나타납니다...")
        
        if m_search:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%,content.ilike.%{m_search}%").order("created_at", desc=True).execute()
            if res.data:
                st.caption(f"검색 결과: {len(res.data)}건")
                for row in res.data:
                    is_man = row['source_type'] == 'MANUAL'
                    with st.expander(f"[{'👤경험' if is_man else '📄이론'}] {row['manufacturer']} | {row['model_name']}"):
                        if is_man:
                            st.markdown(f"**⚠️ 현상:** {row['issue']}")
                            st.markdown(f"**🛠️ 조치:** {row['solution']}")
                        else:
                            st.markdown(f"**📄 매뉴얼 내용:**")
                            st.info(row['content'])
                        c1, c2 = st.columns(2)
                        if c1.button("✏️", key=f"e_{row['id']}"): st.session_state.edit_id = row['id']; st.rerun()
                        if c2.button("🗑️", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
            else:
                st.warning("검색 결과가 없습니다.")
        else:
            st.write("---")
            st.caption("위 검색창을 이용하여 수정 또는 삭제할 데이터를 찾아주세요.")
