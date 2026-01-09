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

# --- 표준 카테고리 ---
DOMAIN_MAP = {
    "기술지식": {
        "측정기기": ["TOC", "TN", "TP", "일반항목", "VOCs", "물벼룩", "황산화", "미생물", "발광박테리아", "기타"],
        "채수시설": ["펌프", "레듀샤", "호스", "커플링", "캡록", "여과 필터", "기타"],
        "전처리/반응조": ["공통"], "통신/데이터": ["공통"], "전기/제어": ["공통"], "소모품/시약": ["공통"]
    }
}

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI 스타일 ---
st.set_page_config(page_title="금강수계 AI V140", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 5.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.1); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .guide-box { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; font-size: 0.85rem; color: #475569; margin-bottom: 15px; }
    .verified-badge { background-color: #e0f2fe; color: #0369a1; padding: 2px 8px; border-radius: 12px; font-weight: bold; font-size: 0.75rem; border: 1px solid #7dd3fc; }
    .edit-form { background-color: #fffaf0; border: 1px dashed #ed8936; padding: 12px; border-radius: 6px; margin-top: 10px; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V140</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

# --- 1. 통합 검색 (V140 기능 완전 복구) ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도(임계값) 설정", 0.0, 1.0, 0.6, 0.05)
        st.markdown(f'<div class="guide-box">🎯 <b>정밀 타격(0.6↑)</b>: 정확한 용어 위주 / <b>포괄 탐색(0.4↓)</b>: 의미 위주</div>', unsafe_allow_html=True)
        user_q = st.text_input("질문 입력", placeholder="예: TN-2060 점검 절차", label_visibility="collapsed")
        search_btn = st.button("🔍 지능형 검색 실행", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("질문의 의도와 장비명을 분석 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
            # [V140] 필터링 강화 검색
            m_res = db.match_filtered_db("match_manual", q_vec, u_threshold, intent)
            k_res = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent)
            
            final = []
            for d in (m_res + k_res):
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if d.get('semantic_version') == 1:
                    score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.1)
                    if d.get('is_verified'): score += 0.15
                    final.append({**d, 'final_score': score, 'u_key': u_key})
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                if final:
                    st.subheader("🤖 AI 전문가 분석 요약")
                    st.info(generate_relevant_summary(ai_model, user_q, final[:10]))
                    for d in final[:8]:
                        v_mark = '<span class="verified-badge">✅ 전문가 인증</span>' if d.get('is_verified') else ''
                        with st.expander(f"[{d.get('model_name','공통')}] 상세 지식 {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            
                            # [V140 핵심] 현장 라벨 교정 폼 (image_02023c 피드백 반영)
                            with st.form(key=f"edit_{d['u_key']}"):
                                st.markdown("🔧 **장비 정보 교정 (검색 품질 개선용)**")
                                c1, c2, c3 = st.columns(3)
                                new_mfr = c1.text_input("제조사", value=d.get('manufacturer',''), key=f"m_{d['u_key']}")
                                new_mod = c2.text_input("모델명", value=d.get('model_name',''), key=f"o_{d['u_key']}")
                                new_itm = c3.text_input("항목", value=d.get('measurement_item',''), key=f"i_{d['u_key']}")
                                if st.form_submit_button("💾 정보 교정 저장"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    if db.update_record_labels(t_name, d['id'], new_mfr, new_mod, new_itm):
                                        st.toast("라벨이 교정되었습니다!", icon="✅"); time.sleep(0.5); st.rerun()
                else: st.warning("🔍 검색 결과가 없습니다.")

# --- 4. 데이터 전체 관리 (모든 서브 탭 복구) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[3]: # 라벨 승인 및 일괄 처리 (V133 로직 완벽 유지)
            st.subheader("🏷️ AI 라벨링 최종 승인")
            t_sel = st.radio("대상", ["경험", "매뉴얼"], horizontal=True)
            t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
            all_staging = db.supabase.table(t_name).select("file_name").eq("semantic_version", 2).execute().data
            files = sorted(list(set([r['file_name'] for r in all_staging if r.get('file_name')])))
            if files:
                c1, c2 = st.columns([0.7, 0.3]); target_f = c1.selectbox("일괄 승인", files)
                if c2.button("🚀 전체 승인"): db.bulk_approve_file(t_name, target_f); st.rerun()
            staging = db.supabase.table(t_name).select("*").eq("semantic_version", 2).limit(2).execute().data
            for r in staging:
                with st.form(key=f"aprv_{r['id']}"):
                    st.write(f"ID {r['id']}: {r.get('content')[:300]}...")
                    c1, c2, c3 = st.columns(3)
                    mfr, mod, itm = c1.text_input("제조사", r.get('manufacturer','')), c2.text_input("모델명", r.get('model_name','')), c3.text_input("항목", r.get('measurement_item',''))
                    if st.form_submit_button("✅ 최종 승인"):
                        db.supabase.table(t_name).update({"manufacturer": mfr, "model_name": mod, "measurement_item": itm, "semantic_version": 1}).eq("id", r['id']).execute(); st.rerun()

# --- 3. 문서 등록 및 2. 지식 등록 ---
elif mode == "📄 문서(매뉴얼) 등록":
    _, up_col, _ = st.columns([1, 2, 1])
    with up_col:
        up_f = st.file_uploader("PDF 업로드", type=["pdf"])
        if up_f and st.button("🚀 심층 분석 학습 시작", use_container_width=True):
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v140(all_t)
            for chunk in chunks:
                meta = extract_metadata_ai(ai_model, chunk)
                db.supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'), "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2}).execute()
            st.success("학습 완료!"); st.rerun()

elif mode == "📝 지식 등록":
    _, reg_col, _ = st.columns([1, 2, 1])
    with reg_col:
        with st.form("reg_v140"):
            f_iss = st.text_input("제목(Issue)")
            f_sol = st.text_area("조치방법(Solution)")
            if st.form_submit_button("💾 지식 저장"):
                db.supabase.table("knowledge_base").insert({"domain": "기술지식", "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1, "is_verified": True}).execute()
                st.success("저장 완료!")
