import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

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

# --- V158 UI 테마 및 스타일링 ---
st.set_page_config(page_title="금강수계 AI V158", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
    .meta-bar { background-color: rgba(255, 255, 255, 0.1); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; color: #ffffff !important; }
    .summary-box { background-color: #f0fdf4; border: 1px solid #166534; padding: 15px; border-radius: 10px; color: #166534; margin-bottom: 25px; font-size: 1.1rem; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); }
    .stButton>button { border-radius: 8px; font-weight: bold; border: 1px solid #004a99; color: #004a99; transition: all 0.3s; }
    .stButton>button:hover { background-color: #004a99; color: white; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V158</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 고장 조치", label_visibility="collapsed")
        search_btn = st.button("🔍 초정밀 지능 검색 실행", use_container_width=True, type="primary")

    if user_q and (search_btn or user_q):
        # [V158] 검색 시마다 상세 리포트 초기화
        if "last_query" not in st.session_state or st.session_state.last_query != user_q:
            st.session_state.last_query = user_q
            if "full_report" in st.session_state: del st.session_state.full_report

        with st.spinner("의도 분석 및 실시간 3줄 요약 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
            # 1단계: 벡터 검색 후보 추출 (Top 8)
            m_res = db.match_filtered_db("match_manual", q_vec, u_threshold, intent)
            k_res = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent)
            
            raw_candidates = []
            for d in (m_res + k_res):
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if d.get('semantic_version') == 1:
                    score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.1)
                    if d.get('is_verified'): score += 0.15
                    raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
            
            raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
            
            # 2단계: 리랭킹 및 3줄 요약만 생성 (상세 리포트 제외로 속도 확보)
            final = rerank_results_ai(ai_model, user_q, raw_candidates)
            
            if final:
                st.session_state.final_results = final # 리포트 생성을 위해 결과 저장
                top_summary_3line = generate_3line_summary(ai_model, user_q, final[:3])
                
                _, res_col, _ = st.columns([0.5, 3, 0.5])
                with res_col:
                    st.subheader("⚡ 즉각 대응 3줄 요약")
                    st.markdown(f'<div class="summary-box"><b>{top_summary_3line}</b></div>', unsafe_allow_html=True)
                    
                    # [V158 핵심] "상세보기" 버튼을 누르는 순간 리포트 생성 (Lazy Loading)
                    st.subheader("🔍 AI 전문가 정밀 분석")
                    if "full_report" not in st.session_state:
                        if st.button("📋 심층 기술 리포트 생성 및 확인", use_container_width=True):
                            with st.spinner("최종 데이터 분석 및 리포트 작성 중... (약 3초 소요)"):
                                st.session_state.full_report = generate_relevant_summary(ai_model, user_q, final[:5])
                                st.rerun()
                    else:
                        st.info(st.session_state.full_report)
                        if st.button("🔄 리포트 다시 읽기", key="reset_report"):
                            del st.session_state.full_report; st.rerun()
                    
                    st.subheader("📋 정밀 검증된 근거 데이터")
                    for d in final[:6]:
                        v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                        score = d.get('rerank_score', 0)
                        with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
            else:
                st.warning("🔍 검색 결과가 없습니다.")

# --- 관리자 및 매뉴얼 등록 모듈 (기존 V157 로직 100% 유지) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[1]: # 수동 분류실
            st.subheader("🚨 제조사 미지정 데이터 정제")
            target = st.radio("조회 대상", ["경험", "매뉴얼"], horizontal=True, key="m_cls_target")
            t_name = "knowledge_base" if target == "경험" else "manual_base"
            unclass = db.supabase.table(t_name).select("*").or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').limit(5).execute().data
            if unclass:
                for r in unclass:
                    with st.expander(f"ID {r['id']} 상세"):
                        st.write(r.get('content') or r.get('solution') or r.get('issue'))
                        with st.form(key=f"v158_cls_{t_name}_{r['id']}"):
                            c1, c2, c3 = st.columns(3)
                            n_mfr = c1.text_input("제조사 (필수)", key=f"nm_{r['id']}")
                            n_mod = c2.text_input("모델명", key=f"no_{r['id']}")
                            n_itm = c3.text_input("항목", key=f"ni_{r['id']}")
                            batch_apply = st.checkbox("이 파일 일괄 적용", key=f"batch_{r['id']}") if r.get('file_name') else False
                            b1, b2 = st.columns(2)
                            if b1.form_submit_button("✅ 저장"):
                                if not n_mfr.strip(): st.error("제조사 필수")
                                else:
                                    res = db.update_file_labels(t_name, r['file_name'], n_mfr, n_mod, n_itm) if batch_apply else db.update_record_labels(t_name, r['id'], n_mfr, n_mod, n_itm)
                                    if res[0]: st.success(f"{res[1]}!"); time.sleep(0.5); st.rerun()
                            if b2.form_submit_button("🗑️ 폐기"):
                                if db.delete_record(t_name, r['id'])[0]: st.warning("삭제됨"); time.sleep(0.5); st.rerun()
            else: st.success("✅ 미분류 데이터 없음")
        with tabs[0]:
            k_cnt, m_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count, db.supabase.table("manual_base").select("id", count="exact").execute().count
            st.metric("경험", f"{k_cnt}건"); st.metric("매뉴얼", f"{m_cnt}건")
        with tabs[2]:
            if st.button("🏗️ 지식 재인덱싱 시작", type="primary"):
                rows = db.supabase.table("manual_base").select("id, content").execute().data
                pb = st.progress(0)
                for i, r in enumerate(rows):
                    db.update_vector("manual_base", r['id'], get_embedding(r['content']))
                    pb.progress((i+1)/len(rows))
                st.success("완료!")
        with tabs[3]:
            staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
            for r in staging:
                with st.form(key=f"aprv_v158_{r['id']}"):
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
    with st.form("reg_v158"):
        f_iss, f_sol = st.text_input("제목"), st.text_area("해결방법", height=200)
        if st.form_submit_button("💾 저장"):
            db.supabase.table("knowledge_base").insert({"domain": "기술지식", "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1, "is_verified": True}).execute()
            st.success("저장 완료")
