import streamlit as st
import time
from logic_ai import *

def show_search_ui(ai_model, db):
    st.markdown("""<style>
        .summary-box { background-color: #f8fafc; border: 2px solid #166534; padding: 20px; border-radius: 12px; color: #0f172a !important; margin-bottom: 25px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); line-height: 1.6; }
        .report-box { background-color: #ffffff; border: 1px solid #004a99; padding: 25px; border-radius: 12px; color: #0f172a !important; box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05); line-height: 1.8; }
        .meta-bar { background-color: #004a99 !important; padding: 12px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 12px; color: #ffffff !important; display: flex; gap: 15px; flex-wrap: wrap; }
        .meta-bar b { color: #ffd700 !important; }
        div[data-testid="stForm"] { border: 1px solid #e2e8f0; background-color: rgba(241, 245, 249, 0.1); padding: 20px; border-radius: 10px; }
    </style>""", unsafe_allow_html=True)

    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 고장 조치", label_visibility="collapsed")
        search_btn = st.button("🔍 초정밀 하이브리드 검색 실행", use_container_width=True, type="primary")

    if user_q and (search_btn or user_q):
        if "last_query" not in st.session_state or st.session_state.last_query != user_q:
            st.session_state.last_query = user_q
            if "full_report" in st.session_state: del st.session_state.full_report

        progress_bar = st.progress(0, text="AI가 질문의 의도를 분석 중입니다...")
        
        # 1. 의도 분석 및 벡터 생성
        intent = analyze_search_intent(ai_model, user_q)
        q_vec = get_embedding(user_q)
        progress_bar.progress(40, text=f"검색 조건 식별: {intent.get('target_mfr','미지정')} / {intent.get('target_item','미지정')}")

        # 2. 하이브리드 검색
        penalties = db.get_penalty_counts()
        m_res = db.match_filtered_db("match_manual", q_vec, u_threshold, intent, user_q)
        k_res = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent, user_q)
        
        progress_bar.progress(70, text="지식 후보군 정밀 리랭킹 중...")
        
        raw_candidates = []
        for d in (m_res + k_res):
            u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
            if d.get('semantic_version') == 1:
                score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.1)
                if d.get('is_verified'): score += 0.15
                raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
        
        raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
        
        # 3. [V173] 의도(intent)를 리랭커에 전달하여 신뢰도 0% 현상 해결
        final = rerank_results_ai(ai_model, user_q, raw_candidates, intent)
        progress_bar.progress(100, text="분석 완료!")
        time.sleep(0.3); progress_bar.empty()

        if final:
            top_summary_3line = generate_3line_summary(ai_model, user_q, final[:3])
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                st.subheader("⚡ 즉각 대응 핵심 요약 (3줄)")
                st.markdown(f'<div class="summary-box">{top_summary_3line.replace("\\n", "<br>")}</div>', unsafe_allow_html=True)
                
                st.subheader("🔍 AI 전문가 정밀 분석")
                if "full_report" not in st.session_state:
                    if st.button("📋 심층 기술 리포트 생성 및 확인", use_container_width=True):
                        st.session_state.full_report = generate_relevant_summary(ai_model, user_q, final[:5])
                        st.rerun()
                else:
                    st.markdown('<div class="report-box">', unsafe_allow_html=True)
                    st.write(st.session_state.full_report)
                    st.markdown('</div>', unsafe_allow_html=True)
                    if st.button("🔄 리포트 다시 읽기"): del st.session_state.full_report; st.rerun()
                
                st.subheader("📋 정밀 검색 결과 및 연관성 평가")
                for d in final[:6]:
                    v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                    # 신뢰도가 0%로 나오지 않도록 보정값 확인
                    score = d.get('rerank_score', 0)
                    with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                        st.markdown(f'''<div class="meta-bar">
                            <span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span>
                            <span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span>
                            <span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span>
                        </div>''', unsafe_allow_html=True)
                        st.write(d.get('content') or d.get('solution'))
                        
                        t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                        c1, c2, _ = st.columns([0.25, 0.25, 0.5])
                        if c1.button("✅ 질문과 연관있음", key=f"v173_up_{d['u_key']}"):
                            if db.save_relevance_feedback(user_q, d['id'], t_name, 1): st.rerun()
                        if c2.button("❌ 질문과 무관함", key=f"v173_down_{d['u_key']}"):
                            if db.save_relevance_feedback(user_q, d['id'], t_name, -1): st.rerun()
                        
                        st.markdown("---")
                        with st.form(key=f"edit_v173_{d['u_key']}"):
                            c1, c2, c3 = st.columns(3)
                            e_mfr = c1.text_input("제조사", d.get('manufacturer',''), key=f"m_{d['u_key']}")
                            e_mod = c2.text_input("모델명", d.get('model_name',''), key=f"o_{d['u_key']}")
                            e_itm = c3.text_input("항목", d.get('measurement_item',''), key=f"i_{d['u_key']}")
                            if st.form_submit_button("💾 정보 교정 및 DB 반영"):
                                if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)[0]: st.rerun()
        else: st.warning("🔍 검색 결과가 없습니다.")
