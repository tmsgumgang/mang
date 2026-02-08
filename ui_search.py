import streamlit as st
import time
import json
import re
from logic_ai import *
from utils_search import perform_unified_search

# =========================================================================
# [V247] 그래프 관계 매핑 (채팅창에서도 한국어로 직관적 표시)
# =========================================================================
REL_MAP = {
    "causes": "원인이다 (A가 B를 유발)",
    "part_of": "부품이다 (A는 B의 일부)",
    "solved_by": "해결된다 (A는 B로 해결)",
    "requires": "필요로 한다 (A는 B가 필요)",
    "has_status": "상태다 (A는 B라는 증상/상태)",
    "located_in": "위치한다 (A는 B에 있음)",
    "related_to": "관련되어 있다 (A와 B 연관)",
    "manufactured_by": "제품이다 (A는 B가 제조함)"
}

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
        .meta-bar { background-color: #004a99 !important; padding: 8px 12px; border-radius: 6px; font-size: 0.85rem; margin-bottom: 8px; color: #ffffff !important; display: flex; gap: 10px; flex-wrap: wrap; }
        .report-box { background-color: #ffffff; border: 1px solid #004a99; padding: 25px; border-radius: 12px; color: #0f172a !important; box-shadow: inset 0 2px 4px 0 rgba(0, 0, 0, 0.05); line-height: 1.8; }
        .doc-feedback-area { background-color: #f1f5f9; padding: 10px; border-radius: 8px; margin-top: 10px; border: 1px solid #e2e8f0; font-size: 0.9rem;}
        .graph-insight-box { background-color: #fff7ed; border-left: 4px solid #f97316; padding: 15px; border-radius: 4px; margin-bottom: 15px; color: #431407; font-size: 0.95rem; }
        .stSelectbox, .stTextInput { margin-bottom: 5px !important; }
    </style>""", unsafe_allow_html=True)

    # ----------------------------------------------------------------------
    # [Input] 검색 입력창
    # ----------------------------------------------------------------------
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "소모품 재고 📦", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        
        if s_mode != "소모품 재고 📦":
            u_threshold = st.slider("정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        else:
            u_threshold = 0.0 
            
        ph_text = "예: 시마즈 TOC 고장 조치"
        if s_mode == "소모품 재고 📦":
            ph_text = "예: 배양액, 3way valve (단어만 입력해도 됩니다)"
            
        user_q = st.text_input("질문 입력", placeholder=ph_text, label_visibility="collapsed")
        search_btn = st.button("🔍 검색", use_container_width=True, type="primary")

    # ----------------------------------------------------------------------
    # [Logic] 검색 실행 및 결과 출력
    # ----------------------------------------------------------------------
    if user_q and (search_btn or user_q):
        if "last_query" not in st.session_state or st.session_state.last_query != user_q:
            st.session_state.last_query = user_q
            if "full_report" in st.session_state: del st.session_state.full_report
            if "streamed_summary" in st.session_state: del st.session_state.streamed_summary

        # =========================================================
        # [CASE 1] 소모품 재고 검색 모드
        # =========================================================
        if s_mode == "소모품 재고 📦":
            with st.spinner("📦 창고 데이터를 조회하고 있습니다..."):
                inv_result = db.search_inventory_for_chat(user_q)
            
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                st.subheader("📦 실시간 재고 확인")
                if inv_result:
                    st.markdown(f'<div class="inventory-box">{inv_result.replace(chr(10), "<br>")}</div>', unsafe_allow_html=True)
                else:
                    st.warning("🔍 검색 결과가 없습니다.")
            return 

        # =========================================================
        # [CASE 2] 일반 기술/생활 정보 검색 (Graph RAG V247)
        # =========================================================
        with st.spinner("지식을 탐색 중입니다... (Graph + Vector)"):
            try:
                final, intent, q_vec = perform_unified_search(ai_model, db, user_q, u_threshold)
            except Exception as e:
                st.error(f"검색 중 오류가 발생했습니다: {str(e)}")
                return

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

                # --------------------------------------------------------------------------
                # (3) [V247 핵심] 참조 데이터 (그래프와 원본 문서를 분리해서 표시)
                # --------------------------------------------------------------------------
                st.subheader("📚 참조 근거 자료 (Reference)")
                search_keywords = user_q.split()

                # 1. 데이터를 타입별로 분리
                graph_docs = [d for d in final if d.get('source_table') == 'knowledge_graph']
                normal_docs = [d for d in final if d.get('source_table') != 'knowledge_graph']

                # 2. [A] 그래프 지식 (Insights) 먼저 표시
                if graph_docs:
                    with st.expander("💡 [AI 그래프 분석] 발견된 인과관계 (Knowledge Graph)", expanded=True):
                        for gd in graph_docs[:5]: # 너무 길어지지 않게 5개 제한
                            # content에 이미 AI가 요약한 문장(A는 B의 원인이다 등)이 들어있음
                            content = gd.get('content','').replace("\n", "<br>")
                            st.markdown(f'<div class="graph-insight-box">{content}</div>', unsafe_allow_html=True)

                # 3. [B] 원본 문서 (Original Source) 표시 - 그래프가 많아도 밀리지 않도록 별도 출력
                if normal_docs:
                    st.markdown("---")
                    st.caption("📄 원본 문서 내용 (Manual & Knowledge Base)")
                    
                    for d in normal_docs[:5]: # 최대 5개까지 원본 표시
                        v_mark = ' ✅ 인증' if d.get('is_verified') else ''
                        score = d.get('rerank_score', 0)
                        
                        # 아이콘 및 출처 표시
                        icon = "💡"
                        source_label = "지식 베이스(경험)"
                        if d.get('source_table') == 'manual_base': 
                            icon = "📄"
                            source_label = "PDF 매뉴얼"
                        
                        with st.expander(f"{icon} [{source_label}] {d.get('measurement_item','-')} - {d.get('model_name','공통')} (연관도: {score}%) {v_mark}"):
                            # 메타 정보 바
                            st.markdown(f'''<div class="meta-bar">
                                <span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span>
                                <span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span>
                                <span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span>
                            </div>''', unsafe_allow_html=True)
                            
                            # 원본 내용 표시 (인간 작성 텍스트)
                            raw_content = d.get('content') or d.get('solution') or ""
                            # 이슈 내용이 별도로 있으면 병기 (지식베이스 경우)
                            if d.get('issue'):
                                raw_content = f"<b>[증상/이슈]</b> {d['issue']}<br><br><b>[해결/내용]</b> {raw_content}"
                                
                            safe_content = raw_content.replace("\n", "<br>") 
                            highlighted_content = highlight_text(safe_content, search_keywords)
                            
                            st.markdown(highlighted_content, unsafe_allow_html=True)
                            
                            # 문서 평가 UI
                            t_name = d.get('source_table', 'manual_base') 
                            unique_k = d.get('u_key', d['id']) 

                            st.markdown('<div class="doc-feedback-area">', unsafe_allow_html=True)
                            c_fb1, c_fb2 = st.columns([3, 1])
                            with c_fb1:
                                st.caption("이 정보가 도움이 되었나요?")
                            with c_fb2:
                                if st.button("👍", key=f"up_{unique_k}"):
                                    db.save_relevance_feedback(user_q, d['id'], t_name, 1, q_vec, reason="good")
                                    st.toast("기록됨")
                            st.markdown('</div>', unsafe_allow_html=True)
                else:
                    # 원본 문서가 없는 경우
                    st.info("ℹ️ 매뉴얼 원본 문서를 찾지 못했습니다. (지식 그래프 분석 결과만 표시됩니다)")

                # -------------------------------------------------------------
                # [V247] 🛠️ 채팅창 내 그래프 즉시 수정 (수정+삭제 기능)
                # -------------------------------------------------------------
                # 키워드 관련 그래프 지식을 불러와서 바로 수정할 수 있게 함
                keywords = [k for k in user_q.split() if len(k) >= 2]
                graph_hits = []
                for kw in keywords:
                    rels = db.search_graph_relations(kw)
                    if rels: graph_hits.extend(rels[:2]) # 너무 많이 뜨지 않게 조절

                if graph_hits:
                    st.divider()
                    with st.expander("🛠️ 그래프 지식 즉시 교정 (전문가 모드)", expanded=False):
                        st.info("AI가 분석한 인과관계가 틀렸다면 여기서 바로 수정하거나 삭제하세요.")
                        
                        # 중복 제거
                        unique_hits = {v['id']:v for v in graph_hits}.values()
                        relation_keys = list(REL_MAP.keys())

                        for rel in unique_hits:
                            rid = rel['id']
                            with st.form(key=f"chat_edit_graph_{rid}"):
                                c1, c_mid1, c2, c_mid2, c3, c4 = st.columns([2.5, 0.5, 2.5, 0.5, 2.5, 1.5])
                                
                                # 수정 입력창
                                e_src = c1.text_input("주어", value=rel['source'], label_visibility="collapsed")
                                c_mid1.markdown("<div style='text-align: center; margin-top: 10px; font-size: 0.8rem;'>는(은)</div>", unsafe_allow_html=True)
                                
                                e_tgt = c2.text_input("목적어", value=rel['target'], label_visibility="collapsed")
                                c_mid2.markdown("<div style='text-align: center; margin-top: 10px; font-size: 0.8rem;'>의</div>", unsafe_allow_html=True)
                                
                                # 관계 선택 (한국어)
                                curr_rel = rel['relation']
                                opts = relation_keys if curr_rel in relation_keys else relation_keys + [curr_rel]
                                e_rel = c3.selectbox("관계", options=opts, index=opts.index(curr_rel), 
                                                   format_func=lambda x: REL_MAP.get(x, x), label_visibility="collapsed")
                                
                                # 버튼
                                bc1, bc2 = c4.columns(2)
                                save = bc1.form_submit_button("💾")
                                delete = bc2.form_submit_button("🗑️")

                                if save:
                                    if db.update_graph_triple(rid, e_src, e_rel, e_tgt):
                                        st.success("수정 완료!"); time.sleep(0.5); st.rerun()
                                    else: st.error("실패")
                                
                                if delete:
                                    if db.delete_graph_triple(rid):
                                        st.warning("삭제 완료!"); time.sleep(0.5); st.rerun()
                                    else: st.error("실패")
        else:
            st.warning("🔍 검색 결과가 없습니다.")
