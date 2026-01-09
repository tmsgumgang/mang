import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

# [인증 정보]
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

# --- UI 스타일링 ---
st.set_page_config(page_title="금강수계 AI V154", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
    .meta-bar { background-color: rgba(255, 255, 255, 0.1); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; color: #ffffff !important; }
    .guide-box { background-color: #f1f5f9; border: 1px solid #cbd5e1; padding: 15px; border-radius: 8px; font-size: 0.9rem; color: #1e293b; margin-bottom: 15px; }
    .summary-box { background-color: #f0fdf4; border: 1px solid #166534; padding: 15px; border-radius: 10px; color: #166534; margin-bottom: 20px; font-size: 1.05rem; box-shadow: 2px 2px 5px rgba(0,0,0,0.05); }
    .intent-badge { background-color: #e0f2fe; color: #0369a1; padding: 4px 10px; border-radius: 20px; font-size: 0.8rem; font-weight: bold; margin-bottom: 10px; display: inline-block; border: 1px solid #7dd3fc; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V154 (토큰 최적화 버전)</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

# --- 1. 통합 지식 검색 (최적화 로직 적용) ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 고장 조치", label_visibility="collapsed")
        search_btn = st.button("🔍 초고속 지능 검색 실행", use_container_width=True, type="primary")

    if user_q and (search_btn or user_q):
        with st.spinner("최적화된 검색 경로를 탐색 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            if intent.get('target_item') or intent.get('target_model'):
                st.markdown(f"<div class='intent-badge'>🎯 감지된 타겟: {intent.get('target_item','')} {intent.get('target_model','')}</div>", unsafe_allow_html=True)
            
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
            # [최적화 2] 검색 결과 10개 -> 5개로 압축 전달하여 토큰 절약
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
                    # 상단 3줄 요약 (압축된 Top 5 기반)
                    st.subheader("⚡ 즉각 대응 3줄 요약")
                    st.markdown(f'<div class="summary-box"><b>{generate_3line_summary(ai_model, user_q, final[:5])}</b></div>', unsafe_allow_html=True)
                    
                    # [최적화 1] 상세 분석은 더보기 안에서 버튼을 눌렀을 때만 '동적 생성'
                    with st.expander("🔍 AI 전문가 심층 분석 리포트 (필요 시 생성)"):
                        if st.button("📝 상세 분석 리포트 생성 시작", key="gen_detail"):
                            with st.spinner("정밀 분석 중... (토큰이 소모됩니다)"):
                                detail_text = generate_relevant_summary(ai_model, user_q, final[:5])
                                st.info(detail_text)
                        else:
                            st.write("상세 분석이 필요하시면 위 버튼을 클릭하세요. (초기 로딩 속도 향상)")
                    
                    st.subheader("📋 관련 근거 지식")
                    for d in final[:6]:
                        v_mark = ' ✅ 인증됨' if d.get('is_verified') else ''
                        with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} - {d.get('issue', '매뉴얼 정보')} {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            with st.form(key=f"edit_v154_{d['u_key']}"):
                                c1, c2, c3 = st.columns(3)
                                e_mfr, e_mod, e_itm = c1.text_input("제조사", d.get('manufacturer','')), c2.text_input("모델명", d.get('model_name','')), c3.text_input("항목", d.get('measurement_item',''))
                                if st.form_submit_button("💾 정보 교정"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)[0]: st.success("완료!"); time.sleep(0.5); st.rerun()
                else: st.warning("🔍 검색 결과가 없습니다.")

# --- 관리자 및 기타 모듈 (V153 로직 전문 유지) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[1]:
            st.subheader("🚨 제조사 미지정 데이터 정제")
            target = st.radio("조회 대상", ["경험", "매뉴얼"], horizontal=True, key="m_cls_target")
            t_name = "knowledge_base" if target == "경험" else "manual_base"
            unclass = db.supabase.table(t_name).select("*").or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').limit(5).execute().data
            if unclass:
                for r in unclass:
                    with st.expander(f"ID {r['id']} 상세"):
                        st.write(r.get('content') or r.get('solution') or r.get('issue'))
                        with st.form(key=f"v154_cls_{t_name}_{r['id']}"):
                            c1, c2, c3 = st.columns(3)
                            n_mfr, n_mod, n_itm = c1.text_input("제조사 (필수)", key=f"nm_{r['id']}"), c2.text_input("모델명", key=f"no_{r['id']}"), c3.text_input("항목", key=f"ni_{r['id']}")
                            batch_apply = st.checkbox("이 파일 일괄 적용", key=f"batch_{r['id']}") if r.get('file_name') else False
                            b1, b2 = st.columns(2)
                            if b1.form_submit_button("✅ 저장"):
                                if not n_mfr.strip(): st.error("제조사 입력 필수")
                                else:
                                    res = db.update_file_labels(t_name, r['file_name'], n_mfr, n_mod, n_itm) if batch_apply else db.update_record_labels(t_name, r['id'], n_mfr, n_mod, n_itm)
                                    if res[0]: st.success(f"{res[1]}!"); time.sleep(0.5); st.rerun()
                            if b2.form_submit_button("🗑️ 폐기"):
                                if db.delete_record(t_name, r['id'])[0]: st.warning("삭제됨"); time.sleep(0.5); st.rerun()
        with tabs[0]:
            k_cnt, m_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count, db.supabase.table("manual_base").select("id", count="exact").execute().count
            st.metric("경험 지식", f"{k_cnt}건"); st.metric("매뉴얼 데이터", f"{m_cnt}건")
        with tabs[2]:
            if st.button("🏗️ 전체 지식 재인덱싱 시작", type="primary"):
                rows = db.supabase.table("manual_base").select("id, content").execute().data
                pb = st.progress(0)
                for i, r in enumerate(rows):
                    db.update_vector("manual_base", r['id'], get_embedding(r['content']))
                    pb.progress((i+1)/len(rows))
                st.success("완료!")
        with tabs[3]:
            staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
            for r in staging:
                with st.form(key=f"aprv_v154_{r['id']}"):
                    st.write(r.get('content')[:300])
                    mfr, mod, itm = st.text_input("제조사", r.get('manufacturer','')), st.text_input("모델명", r.get('model_name','')), st.text_input("항목", r.get('measurement_item',''))
                    if st.form_submit_button("✅ 승인"): db.update_record_labels("manual_base", r['id'], mfr, mod, itm); st.rerun()

elif mode == "📄 문서(매뉴얼) 등록":
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f and st.button("🚀 학습 시작", use_container_width=True):
        with st.status("학습 중..."):
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v143(all_t)
            for chunk in chunks:
                meta = extract_metadata_ai(ai_model, chunk)
                db.supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'), "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2}).execute()
        st.rerun()

elif mode == "📝 지식 등록":
    with st.form("reg_v154"):
        f_iss, f_sol = st.text_input("제목"), st.text_area("해결방법", height=200)
        if st.form_submit_button("💾 저장"):
            db.supabase.table("knowledge_base").insert({"domain": "기술지식", "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1, "is_verified": True}).execute()
            st.success("저장 완료")
