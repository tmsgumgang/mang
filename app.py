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

st.set_page_config(page_title="금강수계 AI V145", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 5.5rem !important; }
    .meta-bar { background-color: rgba(255, 255, 255, 0.1); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; color: #ffffff !important; }
    .guide-box { background-color: #f1f5f9; border: 1px solid #cbd5e1; padding: 15px; border-radius: 8px; font-size: 0.85rem; color: #1e293b; margin-bottom: 15px; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V145</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        st.markdown(f'<div class="guide-box">🎯 <b>정밀도: {"높음" if u_threshold > 0.6 else "균형"}</b></div>', unsafe_allow_html=True)
        user_q = st.text_input("질문 입력", placeholder="예: TN-2060 점검 방법", label_visibility="collapsed")
        search_btn = st.button("🔍 검색 실행", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("지식 검색 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
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
                        v_mark = ' ✅ 인증됨' if d.get('is_verified') else ''
                        with st.expander(f"[{d.get('model_name','공통')}] 상세 내용 {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            with st.form(key=f"edit_{d['u_key']}"):
                                st.markdown("🔧 **장비 정보 교정**")
                                c1, c2, c3 = st.columns(3)
                                e_mfr = c1.text_input("제조사", value=d.get('manufacturer',''), key=f"m_{d['u_key']}")
                                e_mod = c2.text_input("모델명", value=d.get('model_name',''), key=f"o_{d['u_key']}")
                                e_itm = c3.text_input("항목", value=d.get('measurement_item',''), key=f"i_{d['u_key']}")
                                if st.form_submit_button("💾 교정 저장"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm):
                                        st.toast("교정 완료!"); time.sleep(0.5); st.rerun()
                else: st.warning("🔍 검색 결과가 없습니다.")

elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[0]:
            st.subheader("🧹 시맨틱 상태 대시보드")
            c1, c2 = st.columns(2)
            k_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count
            m_cnt = db.supabase.table("manual_base").select("id", count="exact").execute().count
            c1.metric("전체 경험 지식", f"{k_cnt}건")
            c2.metric("전체 매뉴얼 청크", f"{m_cnt}건")
        
        with tabs[1]:
            st.subheader("🚨 제조사 미지정 데이터")
            target = st.radio("조회 대상", ["경험", "매뉴얼"], horizontal=True, key="m_cls")
            t_name = "knowledge_base" if target == "경험" else "manual_base"
            unclass = db.supabase.table(t_name).select("*").eq("manufacturer", "미지정").limit(5).execute().data
            if unclass:
                for r in unclass:
                    with st.expander(f"ID {r['id']} 내용 보기"):
                        st.write(r.get('content') or r.get('solution'))
            else: st.success("✅ 미분류 데이터가 없습니다.")

        with tabs[2]: # [V145 구현] 지식 재건축 엔진
            st.subheader("🏗️ 벡터 인덱스 전면 재구성")
            st.warning("주의: 이 작업은 모든 지식의 벡터를 다시 생성합니다. 데이터량에 따라 수십 분이 소요될 수 있습니다.")
            target_re = st.selectbox("재건축 대상 선택", ["전체 데이터", "경험 지식만", "매뉴얼 데이터만"])
            if st.button("🛠️ 검색 엔진 최적화(Re-Indexing) 시작"):
                t_list = []
                if target_re in ["전체 데이터", "경험 지식만"]: t_list.append("knowledge_base")
                if target_re in ["전체 데이터", "매뉴얼 데이터만"]: t_list.append("manual_base")
                
                for t in t_list:
                    rows = db.supabase.table(t).select("id, issue, content, solution").execute().data
                    if rows:
                        st.write(f"📦 {t} 처리 시작 (총 {len(rows)}건)...")
                        pb = st.progress(0)
                        for i, r in enumerate(rows):
                            text = r.get('issue', '') + " " + (r.get('content') or r.get('solution') or '')
                            new_vec = get_embedding(text)
                            db.update_vector(t, r['id'], new_vec)
                            pb.progress((i + 1) / len(rows))
                        st.success(f"✅ {t} 재인덱싱 완료!")
                st.balloons()

        with tabs[3]:
            st.subheader("🏷️ AI 라벨링 최종 승인")
            t_sel = st.radio("승인 대상", ["경험", "매뉴얼"], horizontal=True, key="ap_t")
            t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
            if t_name == "manual_base":
                all_s = db.supabase.table(t_name).select("file_name").eq("semantic_version", 2).execute().data
                files = sorted(list(set([r['file_name'] for r in all_s if r.get('file_name')])))
                if files:
                    c1, c2 = st.columns([0.7, 0.3]); tf = c1.selectbox("파일 선택", files)
                    if c2.button("🚀 일괄 승인", use_container_width=True):
                        db.bulk_approve_file(t_name, tf); st.rerun()
            staging = db.supabase.table(t_name).select("*").eq("semantic_version", 2).limit(2).execute().data
            for r in staging:
                with st.form(key=f"ap_{r['id']}"):
                    st.write(f"ID {r['id']}: {r.get('content') or r.get('solution')[:200]}...")
                    c1, c2, c3 = st.columns(3)
                    mfr, mod, itm = c1.text_input("제조사", r.get('manufacturer','')), c2.text_input("모델명", r.get('model_name','')), c3.text_input("항목", r.get('measurement_item',''))
                    if st.form_submit_button("✅ 승인"):
                        db.update_record_labels(t_name, r['id'], mfr, mod, itm); st.rerun()

elif mode == "📄 문서(매뉴얼) 등록":
    _, up_col, _ = st.columns([1, 2, 1])
    with up_col:
        up_f = st.file_uploader("PDF 업로드", type=["pdf"])
        if up_f and st.button("🚀 학습 시작", use_container_width=True):
            with st.status("학습 중...") as s:
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
                chunks = semantic_split_v143(all_t)
                for i, chunk in enumerate(chunks):
                    meta = extract_metadata_ai(ai_model, chunk)
                    db.supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'), "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2}).execute()
                s.update(label="학습 완료!", state="complete")
            st.rerun()

elif mode == "📝 지식 등록":
    _, reg_col, _ = st.columns([1, 2, 1])
    with reg_col:
        with st.form("reg_v145"):
            f_iss, f_sol = st.text_input("제목"), st.text_area("조치방법")
            if st.form_submit_button("💾 지식 저장"):
                db.supabase.table("knowledge_base").insert({"domain": "기술지식", "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1, "is_verified": True}).execute()
                st.success("저장 완료!")
