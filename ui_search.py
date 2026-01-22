import streamlit as st
import time
import json
import re
from logic_ai import *
from utils_search import perform_unified_search

# [Helper] 하이라이팅 함수
def highlight_text(text, keywords):
    if not text: return ""
    if not keywords: return text
    
    escaped_keywords = [re.escape(k) for k in keywords if len(k) > 0]
    if not escaped_keywords: return text
    
    pattern = re.compile(f"({'|'.join(escaped_keywords)})", re.IGNORECASE)
    highlighted = pattern.sub(r'<mark style="background-color: #fef08a; color: black; padding: 0 2px; border-radius: 2px;">\1</mark>', text)
    return highlighted

def show_search_ui(ai_model, db):
    # ----------------------------------------------------------------------
    # [Style] CSS 스타일 정의
    # ----------------------------------------------------------------------
    st.markdown("""<style>
        .summary-box { background-color: #f8fafc; border: 2px solid #166534; padding: 20px; border-radius: 12px; color: #0f172a !important; margin-bottom: 10px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); line-height: 1.8; }
        .inventory-box { background-color: #ecfdf5; border: 2px solid #10b981; padding: 20px; border-radius: 12px; color: #064e3b !important; margin-bottom: 20px; box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); line-height: 1.6; }
        .meta-bar { background-color: #004a99 !important; padding: 12px; border-radius: 6px; font-size: 0.9rem; margin-bottom: 12px; color: #ffffff !important; display: flex; gap: 15px; flex-wrap: wrap; }
        .report-box { background-color: #ffffff; border: 1px solid #004a99; padding: 25px; border-radius: 12px; color: #0f172a !important; box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05); line-height: 1.8; }
        .doc-feedback-area { background-color: #f1f5f9; padding: 15px; border-radius: 8px; margin-top: 15px; border: 1px solid #e2e8f0; }
        .stSelectbox, .stTextInput { margin-bottom: 10px !important; }
    </style>""", unsafe_allow_html=True)

    # ----------------------------------------------------------------------
    # [Input] 검색 입력창
    # ----------------------------------------------------------------------
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        user_q = st.text_input("질문 입력", placeholder="예: 시마즈 TOC 재고 있어? 또는 고장 조치", label_visibility="collapsed")
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

        # [NEW] 1. 재고 검색 우선 처리 로직
        # 사용자가 재고 관련 단어를 언급했는지 확인
        inventory_triggers = ["재고", "수량", "몇개", "몇 개", "개수", "현황", "있나", "있어", "남았"]
        is_inventory_intent = any(trigger in user_q for trigger in inventory_triggers)

        if is_inventory_intent:
            with st.spinner("📦 창고 데이터를 조회하고 있습니다..."):
                # db_services.py에 추가한 함수 호출
                inv_result = db.search_inventory_for_chat(user_q)
            
            # 재고 결과가 존재하면 출력하고 종료 (기술 검색 스킵)
            if inv_result:
                _, res_col, _ = st.columns([0.5, 3, 0.5])
                with res_col:
                    st.subheader("📦 실시간 재고 확인")
                    st.markdown(f'<div class="inventory-box">{inv_result.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                    
                    st.info("💡 '재고' 관련 질문이 감지되어 기술 문서 대신 재고 현황을 보여드렸습니다.")
                    
                    # 사용자가 실수로 검색했을 수도 있으니, 기술 검색 버튼 제공
                    if st.button("아니요, 관련 '기술 매뉴얼'을 검색하고 싶어요"):
                        # 재고 의도가 아니라고 판단되면 아래 기술 검색 로직으로 통과시킴
                        pass 
                    else:
                        return # 재고 보여주고 끝냄

        # 2. 일반 기술/생활 정보 검색 (기존 로직)
        with st.spinner("지식을 탐색 중입니다..."):
            final, intent, q_vec = perform_unified_search(ai_model, db, user_q, u_threshold)

        if final:
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                # (1) AI 핵심 조치 가이드
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

                # (2) 심층 리포트
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

                # (3) 개별 문서 리스트
                st.subheader("📋 참조 데이터 및 연관성 평가")
                search_keywords = user_q.split()

                for d in final[:6]:
                    v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                    score = d.get('rerank_score', 0)
                    
                    with st.expander(f"[{d.get('measurement_item','-')}] {d.get('model_name','공통')} (신뢰도: {score}%) {v_mark}"):
                        st.markdown(f'''<div class="meta-bar">
                            <span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span>
                            <span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span>
                            <span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span>
                        </div>''', unsafe_allow_html=True)
                        
                        raw_content = d.get('content') or d.get('solution') or ""
                        safe_content = raw_content.replace("\n", "<br>") 
                        highlighted_content = highlight_text(safe_content, search_keywords)
                        
                        st.markdown(highlighted_content, unsafe_allow_html=True)
                        
                        t_name = d.get('source_table', 'manual_base') 
                        unique_k = d.get('u_key', d['id']) 

                        # 문서 평가 영역
                        st.markdown('<div class="doc-feedback-area">', unsafe_allow_html=True)
                        with st.expander("📝 이 문서 평가하기 (클릭)"):
                            f_col1, f_col2 = st.columns([3, 1])
                            with f_col1:
                                reason_type = st.selectbox("평가 사유", ["선택 안 함", "정확한 해결책임", "관련 없는 문서", "모델명 다름", "내용 부실", "직접 입력"], key=f"rs_{unique_k}", label_visibility="collapsed")
                                feedback_reason = reason_type
                                if reason_type == "직접 입력":
                                    feedback_reason = st.text_input("사유 입력", key=f"rt_{unique_k}")
                            with f_col2:
                                if st.button("👍 도움됨", key=f"up_{unique_k}", use_container_width=True):
                                    db.save_relevance_feedback(user_q, d['id'], t_name, 1, q_vec, reason=feedback_reason)
                                    st.toast("✅ 기록됨")
                                if st.button("👎 무관함", key=f"dn_{unique_k}", use_container_width=True):
                                    db.save_relevance_feedback(user_q, d['id'], t_name, -1, q_vec, reason=feedback_reason)
                                    st.toast("📉 제외됨")
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        # (관리자용) 수정 폼
                        st.markdown("---")
                        with st.form(key=f"edit_{unique_k}"):
                            st.caption("🛠️ 데이터 교정")
                            c1, c2, c3 = st.columns(3)
                            e_mfr = c1.text_input("제조사", d.get('manufacturer',''), key=f"em_{unique_k}")
                            e_mod = c2.text_input("모델명", d.get('model_name',''), key=f"eo_{unique_k}")
                            e_itm = c3.text_input("항목", d.get('measurement_item',''), key=f"ei_{unique_k}")
                            if st.form_submit_button("💾 교정"):
                                if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)[0]:
                                    st.success("완료"); time.sleep(0.5); st.rerun()
        else:
            st.warning("🔍 검색 결과가 없습니다.")
