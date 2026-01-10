import streamlit as st
import time

def show_community_ui(ai_model, db):
    st.markdown("""<style>
        .comment-box { background-color: rgba(0,74,153,0.1); padding: 15px; border-radius: 8px; border-left: 5px solid #004a99; margin-bottom: 12px; color: #ffffff !important; }
        .comment-box strong { color: #ffd700 !important; }
        .promo-form { background-color: rgba(22, 101, 52, 0.05); padding: 15px; border-radius: 8px; border: 1px solid #166534; margin-top: 10px; }
    </style>""", unsafe_allow_html=True)

    st.subheader("👥 현장 지식 커뮤니티 (Q&A)")
    st.info("현장의 고충을 공유하고 정답을 찾아 지식 베이스(DB)로 등록하세요.")

    if "community_mode" not in st.session_state:
        st.session_state.community_mode = "list"

    c1, c2 = st.columns([0.8, 0.2])
    with c2:
        if st.session_state.community_mode == "list":
            if st.button("✍️ 질문 등록", use_container_width=True):
                st.session_state.community_mode = "write"
                st.rerun()

    if st.session_state.community_mode == "write":
        with st.form("write_post_v164"):
            st.markdown("### 📝 새로운 질문 등록")
            author = st.text_input("작성자", placeholder="성함 또는 닉네임")
            title = st.text_input("질문 제목")
            content = st.text_area("내용", height=200)
            b1, b2 = st.columns(2)
            if b1.form_submit_button("🚀 등록하기"):
                if author and title and content:
                    if db.add_community_post(author, title, content):
                        st.success("등록 완료!"); time.sleep(0.5)
                        st.session_state.community_mode = "list"
                        st.rerun()
                    else: st.error("DB 저장 실패")
                else: st.error("항목을 모두 채워주세요.")
            if b2.form_submit_button("❌ 취소"):
                st.session_state.community_mode = "list"
                st.rerun()

    else:
        posts = db.get_community_posts()
        if not posts:
            st.warning("등록된 질문이 없습니다.")
        else:
            for p in posts:
                with st.expander(f"📌 {p['title']} (작성자: {p['author']})"):
                    st.write(p['content'])
                    st.divider()
                    
                    comments = db.get_comments(p['id'])
                    if comments:
                        st.markdown("#### 💬 현장 대원 답변")
                        for c in comments:
                            st.markdown(f"""<div class="comment-box">
                                <strong>{c['author']} 대원:</strong><br>{c['content']}
                            </div>""", unsafe_allow_html=True)
                            
                            # [V164] 답변 승격 시 라벨링 수집 인터페이스
                            with st.expander("💎 이 답변을 정식 지식으로 등록 (라벨링 수집)"):
                                st.markdown('<div class="promo-form">', unsafe_allow_html=True)
                                st.info("💡 본 데이터는 지식 베이스의 질적 향상을 위한 라벨링 수집용입니다. 장비 정보를 정확히 입력해 주세요.")
                                c_mfr = st.text_input("제조사", key=f"m_p_{c['id']}")
                                c_mod = st.text_input("모델명", key=f"o_p_{c['id']}")
                                c_itm = st.text_input("측정항목", key=f"i_p_{c['id']}")
                                if st.button("💾 지식베이스 등록 실행", key=f"btn_p_{c['id']}", use_container_width=True):
                                    if c_mfr and c_mod and c_itm:
                                        success, msg = db.promote_to_knowledge(p['title'], c['content'], c_mfr, c_mod, c_itm)
                                        if success: st.success("경험 지식으로 승격되었습니다!"); time.sleep(1); st.rerun()
                                        else: st.error(f"지식화 실패: {msg}")
                                    else: st.warning("라벨링 정보(제조사, 모델명, 항목)를 모두 입력해 주세요.")
                                st.markdown('</div>', unsafe_allow_html=True)

                    with st.form(key=f"comment_form_{p['id']}"):
                        c_author = st.text_input("내 이름", key=f"ca_{p['id']}")
                        c_content = st.text_area("답변 내용", key=f"cc_{p['id']}")
                        if st.form_submit_button("💬 답변 달기"):
                            if c_author and c_content:
                                if db.add_comment(p['id'], c_author, c_content):
                                    st.success("답변 저장 완료!"); st.rerun()
