import streamlit as st
import time
from logic_ai import *

def show_search_ui(ai_model, db):
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 고장 조치", label_visibility="collapsed")
        search_btn = st.button("🔍 초정밀 지능 검색 실행", use_container_width=True, type="primary")

    if user_q and (search_btn or user_q):
        if "last_query" not in st.session_state or st.session_state.last_query != user_q:
            st.session_state.last_query = user_q
            if "full_report" in st.session_state: del st.session_state.full_report

        with st.spinner("의도 분석 및 정밀 검색 중..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            
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
            final = rerank_results_ai(ai_model, user_q, raw_candidates)
            
            if final:
                top_summary_3line = generate_3line_summary(ai_model, user_q, final[:3])
                
                _, res_col, _ = st.columns([0.5, 3, 0.5])
                with res_col:
                    st.subheader("⚡ 즉각 대응 3줄 요약")
                    st.markdown(f'<div class="summary-box"><b>{top_summary_3line}</b></div>', unsafe_allow_html=True)
                    
                    st.subheader("🔍 AI 전문가 정밀 분석")
                    if "full_report" not in st.session_state:
                        if st.button("📋 심층 기술 리포트 생성 및 확인", use_container_width=True):
                            with st.spinner("분석 중..."):
                                st.session_state.full_report = generate_relevant_summary(ai_model, user_q, final[:5])
                                st.rerun()
                    else:
                        st.info(st.session_state.full_report)
                        if st.button("🔄 리포트 다시 읽기"): del st.session_state.full_report; st.rerun()
                    
                    st.subheader("📋 정밀 검증된 근거 데이터 및 품질 관리")
                    for d in final[:6]:
                        v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                        score = d.get('rerank_score', 0)
                        with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            
                            # [V160 복구] 검색 결과 내 라벨링 폼 (절대 누락 금지 지침 준수)
                            st.markdown("---")
                            st.markdown("🔧 **데이터 품질 관리 (현장 라벨 교정)**")
                            with st.form(key=f"edit_v160_{d['u_key']}"):
                                c1, c2, c3 = st.columns(3)
                                e_mfr = c1.text_input("제조사", d.get('manufacturer',''), key=f"m_{d['u_key']}")
                                e_mod = c2.text_input("모델명", d.get('model_name',''), key=f"o_{d['u_key']}")
                                e_itm = c3.text_input("항목", d.get('measurement_item',''), key=f"i_{d['u_key']}")
                                if st.form_submit_button("💾 정보 교정 및 DB 반영"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    success, msg = db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)
                                    if success: st.success("데이터 품질 교정 완료!"); time.sleep(0.5); st.rerun()
                                    else: st.error(msg)
            else: st.warning("🔍 검색 결과가 없습니다.")
