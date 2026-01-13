import streamlit as st
import time
import json
from logic_ai import *
from utils_search import perform_unified_search

def show_search_ui(ai_model, db):
    # ----------------------------------------------------------------------
    # [Style] CSS 스타일 정의
    # ----------------------------------------------------------------------
    st.markdown("""<style>
        .summary-box { background-color: #f8fafc; border: 2px solid #166534; padding: 20px; border-radius: 12px; color: #0f172a !important; margin-bottom: 10px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); line-height: 1.8; }
        .summary-box b { color: #166534 !important; }
        .meta-bar { background-color: #004a99 !important; padding: 12px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 12px; color: #ffffff !important; display: flex; gap: 15px; flex-wrap: wrap; }
        .report-box { background-color: #ffffff; border: 1px solid #004a99; padding: 25px; border-radius: 12px; color: #0f172a !important; box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05); line-height: 1.8; }
        .feedback-bar { background-color: rgba(226, 232, 240, 0.5); padding: 10px; border-radius: 8px; margin-top: 5px; margin-bottom: 20px; border: 1px solid #cbd5e1; text-align: center; }
        .doc-feedback-bar { background-color: rgba(226, 232, 240, 0.3); padding: 8px; border-radius: 6px; margin-top: 10px; border: 1px solid #e2e8f0; }
    </style>""", unsafe_allow_html=True)

    # ----------------------------------------------------------------------
    # [Input] 검색 입력창
    # ----------------------------------------------------------------------
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 고장 조치", label_visibility="collapsed")
        search_btn = st.button("🔍 검색", use_container_width=True, type="primary")

    # ----------------------------------------------------------------------
    # [Logic] 검색 실행 및 결과 출력
    # ----------------------------------------------------------------------
    if user_q and (search_btn or user_q):
        # 쿼리가 바뀌면 상태 초기화
        if "last_query" not in st.session_state or st.session_state.last_query != user_q:
            st.session_state.last_query = user_q
            if "full_report" in st.session_state: del st.session_state.full_report
            if "streamed_summary" in st.session_state: del st.session_state.streamed_summary

        with st.spinner("수석 엔지니어가 지식을 탐색 중입니다..."):
            final, intent, q_vec = perform_unified_search(ai_model, db, user_q, u_threshold)

        if final:
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                # 1. AI 핵심 조치 가이드 (요약)
                st.subheader("⚡ AI 핵심 조치 가이드")
                summary_placeholder = st.empty()
                
                if "streamed_summary" in st.session_state:
                     summary_placeholder.markdown(f'<div class="summary-box">{st.session_state.streamed_summary.replace("\\n", "<br>")}</div>', unsafe_allow_html=True)
                else:
                    try:
                        stream_gen = generate_3line_summary_stream(ai_model, user_q, final)
                        full_text = ""
                        for chunk in stream_gen:
                            full_text += chunk
                            summary_placeholder.markdown(f'<div class="summary-box">{full_text.replace("\\n", "<br>")}</div>', unsafe_allow_html=True)
                        st.session_state.streamed_summary = full_text
                    except Exception as e:
                        summary_placeholder.error(f"요약 중 오류: {str(e)}")

                # --------------------------------------------------------
                # [New] 통합 피드백 버튼 (질문 <-> Top1 문서 관계 평가)
                # --------------------------------------------------------
                st.markdown('<div class="feedback-bar">', unsafe_allow_html=True)
                st.write("💡 이 답변이 문제 해결에 도움이 되셨나요?")
                
                # 가장 정확도가 높은 1위 문서 가져오기
                top_doc = final[0]
                t_name_top = top_doc.get('source_table', 'manual_base')
                
                fb_c1, fb_c2, _ = st.columns([1, 1, 3])
                with fb_c1:
                    if st.button("👍 도움됨", key=f"main_up_{len(st.session_state.last_query)}"):
                        db.save_relevance_feedback(user_q, top_doc['id'], t_name_top, 1, q_vec)
                        st.toast("✅ 피드백 반영 완료! 더 똑똑해졌습니다.")
                with fb_c2:
                    if st.button("👎 별로임", key=f"main_down_{len(st.session_state.last_query)}"):
                        db.save_relevance_feedback(user_q, top_doc['id'], t_name_top, -1, q_vec)
                        st.toast("🚨 의견 감사합니다. 개선하겠습니다.")
                st.markdown('</div>', unsafe_allow_html=True)
                # --------------------------------------------------------

                # 2. 심층 리포트 (옵션)
                st.subheader("🔍 AI 전문가 심층 분석")
                if "full_report" not in st.session_state:
                    if st.button("📋 기술 리포트 전문 생성", use_container_width=True):
                        with st.spinner("보고서 작성 중..."):
                            st.session_state.full_report = generate_relevant_summary(ai_model, user_q, final[:5])
                            st.rerun()
                else:
                    st.markdown('<div class="report-box">', unsafe_allow_html=True)
                    st.write(st.session_state.full_report)
                    st.markdown('</div>', unsafe_allow_html=True)

                # 3. 개별 문서 리스트
                st.subheader("📋 참조 데이터 및 연관성 평가")
                for d in final[:6]:
                    v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                    score = d.get('rerank_score', 0)
                    
                    with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                        st.markdown(f'''<div class="meta-bar">
                            <span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span>
                            <span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span>
                            <span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span>
                        </div>''', unsafe_allow_html=True)
                        st.write(d.get('content') or d.get('solution'))
                        
                        t_name = d.get('source_table', 'manual_base') 

                        # 개별 문서 피드백
                        st.markdown('<div class="doc-feedback-bar">', unsafe_allow_html=True)
                        c1, c2, _ = st.columns([0.25, 0.25, 0.5])
                        
                        if c1.button("✅ 정확함", key=f"doc_up_{d['u_key']}"):
                            db.save_relevance_feedback(user_q, d['id'], t_name, 1, q_vec)
                            st.toast("반영되었습니다.")
                        if c2.button("❌ 부정확", key=f"doc_down_{d['u_key']}"):
                            db.save_relevance_feedback(user_q, d['id'], t_name, -1, q_vec)
                            st.toast("제외 처리되었습니다.")
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        # 문서 수정 폼
                        st.markdown("---")
                        with st.form(key=f"edit_v190_{d['u_key']}"):
                            c1, c2, c3 = st.columns(3)
                            e_mfr = c1.text_input("제조사", d.get('manufacturer',''), key=f"m_{d['u_key']}")
                            e_mod = c2.text_input("모델명", d.get('model_name',''), key=f"o_{d['u_key']}")
                            e_itm = c3.text_input("항목", d.get('measurement_item',''), key=f"i_{d['u_key']}")
                            if st.form_submit_button("💾 정보 교정"):
                                if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)[0]:
                                    st.success("교정 완료"); st.cache_data.clear(); time.sleep(1.0); st.rerun()
                                else: st.error("DB 오류")
        else:
            st.warning("🔍 검색 결과가 없습니다.")
