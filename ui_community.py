import streamlit as st
import time

def show_community_ui(ai_model, db):
    st.markdown("""<style>
        .comment-box { background-color: rgba(0,74,153,0.1); padding: 15px; border-radius: 8px; border-left: 5px solid #004a99; margin-bottom: 12px; color: #ffffff !important; }
        .comment-box strong { color: #ffd700 !important; }
        .promo-ready { background-color: rgba(22, 101, 52, 0.1); padding: 15px; border-radius: 8px; border: 1px solid #166534; margin-top: 10px; color: #ffffff !important; }
    </style>""", unsafe_allow_html=True)

    st.subheader("👥 현장 지식 커뮤니티 (Q&A)")

    if "community_mode" not in st.session_state:
        st.session_state.community_mode = "list"

    c1, c2 = st.columns([0.8, 0.2])
    with c2:
        if st.session_state.community_mode == "list":
            if st.button("✍️ 질문 등록", use_container_width=True):
                st.session_state.community_mode = "write"
                st.rerun()

    # --- 1. 질문 작성 (라벨링 포함) ---
    if st.session_state.community_mode == "write":
        with st.form("write_post_v165"):
            st.markdown("### 📝 새로운 질문 등록")
            st.info("💡 정확한 장비 정보를 입력하면 AI가 더 정밀하게 지식을 학습합니다.")
            
            author = st.text_input("작성자", placeholder="성함 또는 닉네임")
            title = st.text_input("질문 제목")
            content = st.text_area("고장 현상 및 내용", height=150)
            
            st.markdown("---")
            st.markdown("🏷️ **장비 라벨링 정보**")
            c1, c2, c3 = st.columns(3)
            mfr = c1.text_input("제조사")
            mod = c2.text_input("모델명")
            itm = c3.text_input("측정항목")
            
            b1, b2 = st.columns(2)
            if b1.form_submit_button("🚀 등록하기"):
                if author and title and content and mfr:
                    if db.add_community_post(author, title, content, mfr, mod, itm):
                        st.success("등록 완료!"); time.sleep(0.5)
                        st.session_state.community_mode = "list"
                        st.rerun()
                    else: st.error("DB 저장 실패 (SQL 실행 여부를 확인하세요)")
                else: st.error("작성자, 제목, 내용, 제조사는 필수입니다.")
            if b2.form_submit_button("❌ 취소"):
                st.session_state.community_mode = "list"
                st.rerun()

    # --- 2. 게시글 목록 및 답변 지식화 ---
    else:
        posts = db.get_community_posts()
        if not posts:
            st.warning("등록된 질문이 없습니다.")
        else:
            for p in posts:
                # 질문 제목 바에 라벨링 정보 작게 노출
                label_tag = f"[{p.get('measurement_item','-')}] {p.get('model_name','공통')}"
                with st.expander(f"📌 {label_tag} {p['title']} (작성자: {p['author']})"):
                    st.write(p['content'])
                    st.caption(f"제조사: {p.get('manufacturer','미지정')}")
                    st.divider()
                    
                    comments = db.get_comments(p['id'])
                    if comments:
                        st.markdown("#### 💬 현장 대원 답변")
                        for c in comments:
                            st.markdown(f"""<div class="comment-box">
                                <strong>{c['author']} 대원:</strong><br>{c['content']}
                            </div>""", unsafe_allow_html=True)
                            
                            # [V165] 이미 라벨링된 정보를 기반으로 버튼만 누르면 승격
                            st.markdown('<div class="promo-ready">', unsafe_allow_html=True)
                            if st.button("💎 이 답변을 정식 지식으로 등록", key=f"promo_{c['id']}", use_container_width=True):
                                # 질문글(p)에 저장된 라벨 정보를 그대로 가져옴
                                success, msg = db.promote_to_knowledge(
                                    p['title'], 
                                    c['content'], 
                                    p.get('manufacturer','미지정'), 
                                    p.get('model_name','미지정'), 
                                    p.get('measurement_item','공통')
                                )
                                if success:
                                    st.success("이미 등록된 장비 정보와 함께 지식 승격 완료!"); time.sleep(1); st.rerun()
                                else:
                                    st.error(f"지식화 실패 사유: {msg}")
                            st.markdown('</div>', unsafe_allow_html=True)

                    with st.form(key=f"comment_form_{p['id']}"):
                        c_author = st.text_input("내 이름", key=f"ca_{p['id']}")
                        c_content = st.text_area("답변 내용", key=f"cc_{p['id']}")
                        if st.form_submit_button("💬 답변 달기"):
                            if c_author and c_content:
                                if db.add_comment(p['id'], c_author, c_content):
                                    st.success("답변 저장 완료!"); st.rerun()
