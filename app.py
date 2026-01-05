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

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=text, task_type="retrieval_document")
    return result['embedding']

# --- [V20] 입력 오류 수정 및 PDF 분석 안정화 버전 ---
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
    .doc-status-card { background-color: #f8fafc; border-radius: 8px; padding: 10px; border-left: 4px solid #92400e; margin-bottom: 8px; font-size: 0.85rem; }
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

search_threshold = st.sidebar.slider("검색 정밀도", 0.0, 1.0, 0.35, 0.05)
mode = st.session_state.page_mode

# --- 1. 통합 지식 검색 (정밀 필터링) ---
if mode == "🔍 검색":
    user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="상황 입력 (예: TN-2060 동작불량)")
    if user_q:
        with st.spinner("최적의 정보를 정밀 검색 중..."):
            ext_p = f"질문: {user_q} \n 위 질문에서 장비 제조사와 모델명을 추출하여 JSON(mfr, model)으로만 답하세요. 없으면 null."
            try:
                ext_res = ai_model.generate_content(ext_p)
                meta = json.loads(ext_res.text.replace("```json", "").replace("```", "").strip())
                f_mfr, f_model = meta.get("mfr"), meta.get("model")
            except: f_mfr, f_model = None, None

            query_vec = get_embedding(user_q)
            rpc_res = supabase.rpc("match_knowledge", {
                "query_embedding": query_vec, "match_threshold": search_threshold, "match_count": 5, "filter_mfr": f_mfr, "filter_model": f_model
            }).execute()
            
            if rpc_res.data:
                cases = rpc_res.data
                if f_model: # 모델명 명시 시 엉뚱한 기종 필터링
                    cases = [c for c in cases if f_model.lower() in str(c['model_name']).lower() or c['model_name'] == "매뉴얼 참조"]
                
                context = "\n".join([f"[{c['source_type']}] {c['manufacturer']} {c['model_name']}: {c['solution'] if c['source_type']=='MANUAL' else c['content']}" for c in cases])
                ans_p = f"데이터: {context}\n질문: {user_q}\n위 데이터를 바탕으로 핵심 조치법을 3줄 이내 단답형으로 답변하세요."
                st.info(ai_model.generate_content(ans_p).text)
                st.markdown("---")
                for c in cases:
                    is_man = c['source_type'] == 'MANUAL'
                    with st.expander(f"[{'👤경험' if is_man else '📄이론'}] {c['manufacturer']} | {c['model_name']}"):
                        st.markdown(f'<span class="source-tag {"tag-manual" if is_man else "tag-doc"}">{c["registered_by"]}</span>', unsafe_allow_html=True)
                        st.write(c['solution'] if is_man else c['content'])
            else: st.warning("⚠️ 검색 결과가 없습니다.")

# --- 2. 현장 노하우 등록 (직접 입력 UI 완전 개편) ---
elif mode == "📝 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("manual_reg", clear_on_submit=True):
        st.write("📍 **장비 정보 입력**")
        mfr_choice = st.selectbox("1. 제조사 선택", options=["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
        
        # [수정] 직접 입력 선택 시에만 입력하는 칸임을 명확히 함
        manual_mfr = st.text_input("└ (위에서 '직접 입력' 선택 시에만 작성)")
        
        model = st.text_input("2. 모델명", placeholder="예: TN-2060")
        item = st.text_input("3. 측정항목", placeholder="예: TN")
        reg = st.text_input("4. 등록자 성함")
        
        st.write("---")
        st.write("📍 **상세 조치 내용**")
        iss = st.text_input("발생 현상", placeholder="어떤 문제가 있나요?")
        sol = st.text_area("조치 내용", placeholder="어떻게 해결하셨나요?")
        
        if st.form_submit_button("✅ 지식 베이스 저장"):
            # 최종 제조사 값 결정
            mfr_to_save = manual_mfr if mfr_choice == "직접 입력" else mfr_choice
            
            if mfr_to_save and model and iss and sol:
                try:
                    vec = get_embedding(f"{mfr_to_save} {model} {item} {iss} {sol} {reg}")
                    supabase.table("knowledge_base").insert({
                        "manufacturer": mfr_to_save, "model_name": model, "measurement_item": item, 
                        "issue": iss, "solution": sol, "registered_by": reg, 
                        "source_type": "MANUAL", "embedding": vec
                    }).execute()
                    st.success(f"🎉 {mfr_to_save} 장비 노하우가 성공적으로 공유되었습니다!")
                except Exception as e:
                    st.error(f"저장 중 오류 발생: {e}")
            else:
                st.warning("⚠️ 필수 항목(제조사, 모델, 현상, 조치)을 모두 입력해 주세요.")

# --- 3. 문서(매뉴얼) 등록 및 현황 리스트업 ---
elif mode == "📂 문서 관리":
    st.subheader("📄 문서(매뉴얼) 기반 지식 등록")
    st.caption("PDF를 업로드하면 AI가 내용을 쪼개어 지식 베이스에 통합합니다.")
    up_file = st.file_uploader("PDF 매뉴얼 업로드", type="pdf")
    
    if up_file:
        if st.button("🚀 매뉴얼 분석 및 등록 시작"):
            with st.spinner("매뉴얼을 읽고 지식 조각을 생성 중..."):
                try:
                    pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_file.read()))
                    
                    # [강화] 첫 페이지에서 제조사와 모델명을 JSON으로 안전하게 추출
                    first_pg = pdf_reader.pages[0].extract_text()
                    info_p = f"텍스트: {first_pg[:1500]}\n위 텍스트에서 제조사와 모델명을 찾아 JSON으로 답하세요: {{\"mfr\":\"제조사\", \"model\":\"모델명\"}}"
                    info_res = ai_model.generate_content(info_p).text.replace("```json", "").replace("```", "").strip()
                    meta = json.loads(info_res)
                    
                    full_txt = ""
                    for pg in pdf_reader.pages: full_txt += pg.extract_text() + "\n"
                    
                    # 600자 단위 청킹
                    chunks = [full_txt[i:i+600] for i in range(0, len(full_txt), 600)]
                    
                    # DB 저장 루프
                    for chk in chunks:
                        vec = get_embedding(chk)
                        supabase.table("knowledge_base").insert({
                            "manufacturer": meta.get("mfr", "기타")[:50], 
                            "model_name": meta.get("model", "매뉴얼")[:50], 
                            "issue": "매뉴얼 본문", "solution": "원문 참조", "content": chk,
                            "registered_by": up_file.name, "source_type": "DOC", "embedding": vec
                        }).execute()
                    
                    st.success(f"✅ '{up_file.name}' 매뉴얼에서 {len(chunks)}개의 지식을 추출했습니다!")
                    st.rerun()
                except Exception as e:
                    st.error(f"분석 중 오류 발생: {e}. PDF 형식이 너무 복잡하거나 보안 설정이 되어있을 수 있습니다.")

    st.markdown("---")
    st.markdown("### 📋 현재 등록된 매뉴얼 현황")
    try:
        doc_res = supabase.table("knowledge_base").select("registered_by").eq("source_type", "DOC").execute()
        if doc_res.data:
            manual_list = sorted(list(set([d['registered_by'] for d in doc_res.data])))
            for m_name in manual_list:
                st.markdown(f'<div class="doc-status-card">📄 {m_name}</div>', unsafe_allow_html=True)
        else: st.info("등록된 매뉴얼이 없습니다.")
    except: st.error("데이터를 불러오는 중 오류가 발생했습니다.")

# --- 4. 데이터 관리 (검색 기반 노출) ---
elif mode == "🛠️ 관리":
    if st.session_state.edit_id:
        res = supabase.table("knowledge_base").select("*").eq("id", st.session_state.edit_id).execute()
        if res.data:
            it = res.data[0]
            with st.form("edit_f"):
                e_mfr = st.text_input("제조사", value=it['manufacturer'])
                e_model = st.text_input("모델명", value=it['model_name'])
                e_sol = st.text_area("내용 정정", value=it['solution'] if it['source_type']=='MANUAL' else it['content'])
                if st.form_submit_button("💾 저장"):
                    new_v = get_embedding(f"{e_mfr} {e_model} {e_sol}")
                    supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_model, "solution": e_sol if it['source_type']=='MANUAL' else None, "content": e_sol if it['source_type']=='DOC' else None, "embedding": new_v}).eq("id", it['id']).execute()
                    st.session_state.edit_id = None; st.rerun()
                if st.form_submit_button("❌ 취소"): st.session_state.edit_id = None; st.rerun()
    else:
        st.subheader("🛠️ 지식 데이터 상세 관리")
        m_search = st.text_input("🔍 관리 대상 검색", placeholder="모델명, 제조사 등 검색 시 리스트가 노출됩니다.")
        
        if m_search:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{m_search}%,model_name.ilike.%{m_search}%,issue.ilike.%{m_search}%,solution.ilike.%{m_search}%,content.ilike.%{m_search}%").order("created_at", desc=True).execute()
            if res.data:
                st.caption(f"검색 결과: {len(res.data)}건")
                for row in res.data:
                    is_man = row['source_type'] == 'MANUAL'
                    with st.expander(f"[{'👤경험' if is_man else '📄이론'}] {row['manufacturer']} | {row['model_name']}"):
                        if is_man:
                            st.markdown(f"**⚠️ 현상:** {row['issue']}\n\n**🛠️ 조치:** {row['solution']}")
                        else:
                            st.info(row['content'])
                        
                        c1, c2 = st.columns(2)
                        if c1.button("✏️", key=f"e_{row['id']}"): st.session_state.edit_id = row['id']; st.rerun()
                        if c2.button("🗑️", key=f"d_{row['id']}"): supabase.table("knowledge_base").delete().eq("id", row['id']).execute(); st.rerun()
            else: st.warning("일치하는 데이터가 없습니다.")
        else:
            st.write("---")
            st.caption("위 검색창을 사용하여 관리할 항목을 불러오세요.")
