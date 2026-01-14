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
        .doc-feedback-area { background-color: #f1f5f9; padding: 15px; border-radius: 8px; margin-top: 15px; border: 1px solid #e2e8f0; }
        /* 드롭다운/입력창 스타일 조정 */
        .stSelectbox, .stTextInput { margin-bottom: 10px !important; }
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

                # 3. 개별 문서 리스트 및 평가
                st.subheader("📋 참조 데이터 및 연관성 평가")
                for d in final[:6]:
                    v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                    score = d.get('rerank_score', 0)
                    
                    with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                        # 메타 정보 출력
                        st.markdown(f'''<div class="meta-bar">
                            <span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span>
                            <span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span>
                            <span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span>
                        </div>''', unsafe_allow_html=True)
                        
                        # 본문 출력
                        st.write(d.get('content') or d.get('solution'))
                        
                        t_name = d.get('source_table', 'manual_base') 

                        # ----------------------------------------------------
                        # [New] 개별 문서 단위 정밀 피드백 (사유 선택 포함)
                        # ----------------------------------------------------
                        st.markdown('<div class="doc-feedback-area">', unsafe_allow_html=True)
                        
                        # 피드백 입력 폼 (Expander로 숨김 처리하여 UI 간소화)
                        with st.expander("📝 이 문서 평가하기 (클릭)"):
                            f_col1, f_col2 = st.columns([3, 1])
                            
                            # 고유 키(Key) 생성: 위젯 충돌 방지용
                            unique_k = d.get('u_key', d['id']) 
                            
                            with f_col1:
                                reason_type = st.selectbox(
                                    "평가 사유를 선택하세요",
                                    ["선택 안 함", "정확한 해결책임", "관련 없는 문서", "모델명/장비 다름", "내용이 부실함", "직접 입력"],
                                    key=f"reason_sel_{unique_k}",
                                    label_visibility="collapsed"
                                )
                                feedback_reason = reason_type
                                if reason_type == "직접 입력":
                                    feedback_reason = st.text_input(
                                        "사유 입력", placeholder="구체적인 사유를 입력하세요", key=f"reason_txt_{unique_k}"
                                    )
                                elif reason_type == "선택 안 함":
                                    feedback_reason = "개별 문서 평가"

                            with f_col2:
                                if st.button("👍 도움됨", key=f"btn_up_{unique_k}", use_container_width=True):
                                    db.save_relevance_feedback(user_q, d['id'], t_name, 1, q_vec, reason=feedback_reason)
                                    st.toast("✅ 해당 문서의 정확도가 기록되었습니다.")
                                
                                if st.button("👎 무관함", key=f"btn_down_{unique_k}", use_container_width=True):
                                    db.save_relevance_feedback(user_q, d['id'], t_name, -1, q_vec, reason=feedback_reason)
                                    st.toast("📉 해당 문서는 이 질문에서 제외됩니다.")
                        st.markdown('</div>', unsafe_allow_html=True)
                        # ----------------------------------------------------
                        
                        # (관리자용) 문서 데이터 수정 폼
                        st.markdown("---")
                        with st.form(key=f"edit_v190_{d['u_key']}"):
                            st.caption("🛠️ 데이터 메타정보 교정 (관리자용)")
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
