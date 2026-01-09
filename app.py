import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

# [보안] Streamlit Secrets
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_system():
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI Layout ---
st.set_page_config(page_title="금강수계 AI V139", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.1); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .edit-box { background-color: #fffaf0; border: 1px dashed #ed8936; padding: 15px; border-radius: 8px; margin-top: 10px; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V139</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

# --- 1. 통합 검색 (V139 라벨 수정 기능 탑재) ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        u_threshold = st.slider("정밀도(임계값) 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="TOC-4200 고장 원인 등", label_visibility="collapsed")
        search_btn = st.button("🔍 지능형 검색 실행", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("지식의 맥락을 분석하고 장비 정보를 필터링 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
            m_res = db.match_filtered_db("match_manual", q_vec, u_threshold, intent)
            k_res = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent)
            
            final = []
            for d in (m_res + k_res):
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if not d.get('review_required') and d.get('semantic_version') == 1:
                    score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.08)
                    if d.get('is_verified'): score += 0.15
                    final.append({**d, 'final_score': score, 'u_key': u_key})
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                if final:
                    st.subheader("🤖 AI 전문가 분석 요약")
                    st.info(generate_relevant_summary(ai_model, user_q, final[:10]))
                    for d in final[:8]:
                        with st.expander(f"[{d.get('model_name','공통')}] 상세 지식 원문"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            
                            # [V139 핵심] 라벨 수정 폼 (도움됨/무관함 대신 사용)
                            with st.form(key=f"edit_label_{d['u_key']}"):
                                st.markdown("🔧 **장비 정보 교정 (검색 품질 개선)**")
                                c1, c2, c3 = st.columns(3)
                                e_mfr = c1.text_input("제조사", value=d.get('manufacturer','미지정'), key=f"mfr_in_{d['u_key']}")
                                e_mod = c2.text_input("모델명", value=d.get('model_name','공통'), key=f"mod_in_{d['u_key']}")
                                e_itm = c3.text_input("측정항목", value=d.get('measurement_item','공통'), key=f"itm_in_{d['u_key']}")
                                if st.form_submit_button("💾 정보 교정 및 저장"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm):
                                        st.toast("지식 라벨이 전문가에 의해 교정되었습니다!", icon="✅")
                                        time.sleep(0.5); st.rerun()
                else: st.warning("🔍 검색 결과가 없습니다.")

# --- 4. 데이터 전체 관리 (모든 기능 유지) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[3]: # 라벨 승인
            staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
            if staging:
                for r in staging:
                    with st.form(key=f"apprv_{r['id']}"):
                        st.write(f"ID {r['id']}: {r.get('content')[:300]}...")
                        c1, c2, c3 = st.columns(3)
                        if st.form_submit_button("✅ 승인"):
                            db.supabase.table("manual_base").update({"manufacturer": c1.text_input("제조사", value=r.get('manufacturer','')), "model_name": c2.text_input("모델명", value=r.get('model_name','')), "measurement_item": c3.text_input("항목", value=r.get('measurement_item','')), "semantic_version": 1}).eq("id", r['id']).execute()
                            st.rerun()

# --- 3. 문서 등록 및 2. 지식 등록 (심층 라벨링 유지) ---
elif mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 지능형 학습 시작", use_container_width=True):
        pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
        chunks = semantic_split_v139(all_t)
        for chunk in chunks:
            meta = extract_metadata_ai(ai_model, chunk)
            db.supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'), "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2}).execute()
        st.success("학습 완료!"); st.rerun()

elif mode == "📝 지식 등록":
    with st.form("reg_v139"):
        f_iss = st.text_input("제목")
        f_sol = st.text_area("내용")
        if st.form_submit_button("💾 저장하기"):
            db.supabase.table("knowledge_base").insert({"domain": "기술지식", "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1, "is_verified": True}).execute()
            st.success("저장 완료!")
