import streamlit as st
import time

def show_community_ui(ai_model, db):
    # 커뮤니티 전용 스타일 (다크모드 대응)
    st.markdown("""<style>
        .comment-box { background-color: rgba(0,74,153,0.1); padding: 15px; border-radius: 8px; border-left: 5px solid #004a99; margin-bottom: 12px; color: #ffffff !important; }
        .comment-box strong { color: #ffd700 !important; }
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

    # --- 1. 질문 작성 화면 ---
    if st.session_state.community_mode == "write":
        with st.form("write_post_v162"):
            st.markdown("### 📝 새로운 질문 등록")
            author = st.text_input("작성자", placeholder="성함 또는 닉네임")
            title = st.text_input("질문 제목", placeholder="예: TN-2060 펌프 소음 관련 문의")
            content = st.text_area("상세 고장 현상 및 질문 내용", height=200)
            b1, b2 = st.columns(2)
            if b1.form_submit_button("🚀 등록하기"):
                if author and title and content:
                    if db.add_community_post(author, title, content):
                        st.success("질문이 성공적으로 등록되었습니다!"); time.sleep(0.5)
                        st.session_state.community_mode = "list"
                        st.rerun()
                    else:
                        st.error("DB 저장에 실패했습니다. 테이블 생성을 확인하세요.")
                else: st.error("모든 항목을 입력해주세요.")
            if b2.form_submit_button("❌ 취소"):
                st.session_state.community_mode = "list"
                st.rerun()

    # --- 2. 게시글 목록 ---
    else:
        posts = db.get_community_posts()
        if not posts:
            st.warning("현재 등록된 질문이 없습니다. 첫 질문을 남겨보세요!")
        else:
            for p in posts:
                with st.expander(f"📌 {p['title']} (작성자: {p['author']})"):
                    st.write(f"**질문 내용:**\n{p['content']}")
                    st.caption(f"작성일: {p['created_at']}")
                    st.divider()
                    
                    comments = db.get_comments(p['id'])
                    if comments:
                        st.markdown("#### 💬 현장 대원 답변")
                        for c in comments:
                            st.markdown(f"""<div class="comment-box">
                                <strong>{c['author']} 대원:</strong><br>{c['content']}
                            </div>""", unsafe_allow_html=True)
                            
                            if st.button("💎 이 답변을 정식 지식으로 등록", key=f"promo_{c['id']}"):
                                if db.promote_to_knowledge(p['title'], c['content']):
                                    st.success("경험 지식으로 승격되었습니다!"); time.sleep(1)
                                else: st.error("지식화 실패")

                    with st.form(key=f"comment_form_{p['id']}"):
                        c_author = st.text_input("내 이름", key=f"ca_{p['id']}")
                        c_content = st.text_area("답변 내용", key=f"cc_{p['id']}")
                        if st.form_submit_button("💬 답변 달기"):
                            if c_author and c_content:
                                if db.add_comment(p['id'], c_author, c_content):
                                    st.success("답변 저장 완료!"); st.rerun()
