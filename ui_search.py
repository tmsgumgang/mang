import streamlit as st
import time
import json
from logic_ai import *
from utils_search import perform_hybrid_search # [V178] 분리된 검색 엔진 호출

def show_search_ui(ai_model, db):
    # [V175/178] 가독성 및 고대비 테마 CSS 유지
    st.markdown("""<style>
        .summary-box { 
            background-color: #f8fafc; 
            border: 2px solid #166534; 
            padding: 20px; 
            border-radius: 12px; 
            color: #0f172a !important; 
            margin-bottom: 25px; 
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1); 
            line-height: 1.8; 
        }
        .summary-box b { color: #166534 !important; }
        .report-box { 
            background-color: #ffffff; 
            border: 1px solid #004a99; 
            padding: 25px; 
            border-radius: 12px; 
            color: #0f172a !important; 
            box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05); 
            line-height: 1.8; 
        }
        .meta-bar { 
            background-color: #004a99 !important; 
            padding: 12px; 
            border-radius: 6px; 
            font-size: 0.9rem; 
            margin-bottom: 12px; 
            color: #ffffff !important; 
            display: flex; 
            gap: 15px; 
            flex-wrap: wrap; 
        }
        .meta-bar b { color: #ffd700 !important; }
        .feedback-bar { 
            background-color: rgba(226, 232, 240, 0.3); 
            padding: 12px; 
            border-radius: 8px; 
            margin-top: 15px; 
            border: 1px solid #e2e8f0; 
        }
        /* [V178] 검색 결과 강조 스타일 */
        .instant-tag {
            background-color: #166534;
            color: white;
            padding: 2px 6px;
            border-radius: 4px;
            font-size: 0.7rem;
            margin-right: 8px;
        }
    </style>""", unsafe_allow_html=True)

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
            if "lazy_summary" in st.session_state: del st.session_state.lazy_summary

        # 1. [V178 핵심] 인스턴트 검색 실행
        # 요약문을 생성하지 않으므로 매우 빠르게 결과가 리턴됨
        with st.spinner("지식 검색 중..."):
            final, intent = perform_hybrid_search(ai_model, db, user_q, u_threshold)

        if final:
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                # 2. [V178] 지연된 요약 (Lazy Summary) 영역
                st.subheader("⚡ AI 조치 가이드")
                if "lazy_summary" not in st.session_state:
                    if st.button("🪄 AI에게 핵심 요약 요청하기 (3줄)", use_container_width=True):
                        with st.spinner("핵심 데이터를 분석하여 요약 중..."):
                            data_json = json.dumps(final[:3], ensure_ascii=False)
                            st.session_state.lazy_summary = generate_3line_summary(ai_model, user_q, data_json)
                            st.rerun()
                else:
                    st.markdown(f'<div class="summary-box">{st.session_state.lazy_summary.replace("\\n", "<br>")}</div>', unsafe_allow_html=True)
                    if st.button("🔄 요약 새로고침"):
                        del st.session_state.lazy_summary
                        st.rerun()

                # 3. [V178] 인스턴트 결과 목록 (사용자가 즉시 확인 가능한 영역)
                st.subheader("📋 정밀 검색 결과 및 연관성 평가")
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
                        
                        # [V170/178] 맥락 연관성 평가
                        t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                        st.markdown('<div class="feedback-bar">', unsafe_allow_html=True)
                        c1, c2, _ = st.columns([0.25, 0.25, 0.5])
                        if c1.button("✅ 질문과 연관있음", key=f"v178_up_{d['u_key']}"):
                            if db.save_relevance_feedback(user_q, d['id'], t_name, 1):
                                st.success("평가 반영됨!"); time.sleep(0.5); st.rerun()
                        if c2.button("❌ 질문과 무관함", key=f"v178_down_{d['u_key']}"):
                            if db.save_relevance_feedback(user_q, d['id'], t_name, -1):
                                st.warning("반영 완료!"); time.sleep(0.5); st.rerun()
                        st.markdown('</div>', unsafe_allow_html=True)
                        
                        st.markdown("---")
                        # [V160/178] 정보 교정 폼
                        with st.form(key=f"edit_v178_{d['u_key']}"):
                            c1, c2, c3 = st.columns(3)
                            e_mfr = c1.text_input("제조사", d.get('manufacturer',''), key=f"m_{d['u_key']}")
                            e_mod = c2.text_input("모델명", d.get('model_name',''), key=f"o_{d['u_key']}")
                            e_itm = c3.text_input("항목", d.get('measurement_item',''), key=f"i_{d['u_key']}")
                            if st.form_submit_button("💾 정보 교정 및 DB 반영"):
                                if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm)[0]:
                                    st.success("교정 완료!"); time.sleep(0.5); st.rerun()

                # 4. 심층 리포트 (Lazy Loading 유지)
                st.subheader("🔍 AI 전문가 정밀 분석")
                if "full_report" not in st.session_state:
                    if st.button("📋 심층 기술 리포트 생성", use_container_width=True):
                        with st.spinner("전문가 리포트 작성 중..."):
                            st.session_state.full_report = generate_relevant_summary(ai_model, user_q, final[:5])
                            st.rerun()
                else:
                    st.markdown('<div class="report-box">', unsafe_allow_html=True)
                    st.write(st.session_state.full_report)
                    st.markdown('</div>', unsafe_allow_html=True)
        else: st.warning("🔍 검색 결과가 없습니다.")
