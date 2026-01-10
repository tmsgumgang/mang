import streamlit as st
import time

def show_community_ui(ai_model, db):
    st.markdown("""<style>
        .comment-box { background-color: rgba(0,74,153,0.1); padding: 15px; border-radius: 8px; border-left: 5px solid #004a99; margin-bottom: 12px; color: #ffffff !important; }
        .comment-box strong { color: #ffd700 !important; }
        .promo-ready { background-color: rgba(22, 101, 52, 0.1); padding: 15px; border-radius: 8px; border: 1px solid #166534; margin-top: 10px; color: #ffffff !important; }
        .action-bar { display: flex; gap: 10px; justify-content: flex-end; margin-top: 10px; }
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

    # --- 1. 질문 작성 및 수정 화면 ---
    if st.session_state.community_mode in ["write", "edit"]:
        is_edit = st.session_state.community_mode == "edit"
        post_data = st.session_state.get("editing_post", {})
        
        with st.form("post_form_v166"):
            st.markdown(f"### 📝 {'질문 수정' if is_edit else '새로운 질문 등록'}")
            author = st.text_input("작성자", value=post_data.get("author", ""), placeholder="성함 또는 닉네임", disabled=is_edit)
            title = st.text_input("질문 제목", value=post_data.get("title", ""))
            content = st.text_area("고장 현상 및 내용", value=post_data.get("content", ""), height=150)
            
            st.markdown("---")
            st.markdown("🏷️ **장비 라벨링 정보**")
            c1, c2, c3 = st.columns(3)
            mfr = c1.text_input("제조사", value=post_data.get("manufacturer", ""))
            mod = c2.text_input("모델명", value=post_data.get("model_name", ""))
            itm = c3.text_input("측정항목", value=post_data.get("measurement_item", ""))
            
            b1, b2 = st.columns(2)
            if b1.form_submit_button("🚀 " + ("수정 완료" if is_edit else "등록하기")):
                if title and content and mfr:
                    if is_edit:
                        success = db.update_community_post(post_data['id'], title, content, mfr, mod, itm)
                    else:
                        success = db.add_community_post(author, title, content, mfr, mod, itm)
                        
                    if success:
                        st.success(f"{'수정' if is_edit else '등록'} 완료!"); time.sleep(0.5)
                        st.session_state.community_mode = "list"
                        if "editing_post" in st.session_state: del st.session_state.editing_post
                        st.rerun()
                    else: st.error("DB 처리 실패")
                else: st.error("제목, 내용, 제조사는 필수입니다.")
            
            if b2.form_submit_button("❌ 취소"):
                st.session_state.community_mode = "list"
                if "editing_post" in st.session_state: del st.session_state.editing_post
                st.rerun()

    # --- 2. 게시글 목록 ---
    else:
        posts = db.get_community_posts()
        if not posts:
            st.warning("등록된 질문이 없습니다.")
        else:
            for p in posts:
                label_tag = f"[{p.get('measurement_item') or '미지정'}] {p.get('model_name') or '공통'}"
                with st.expander(f"📌 {label_tag} {p['title']} (작성자: {p['author']})"):
                    st.write(p['content'])
                    st.caption(f"제조사: {p.get('manufacturer') or '미지정'} | 작성일: {p['created_at']}")
                    
                    # [V166 추가] 수정 및 삭제 버튼 바
                    col_edit, col_del, col_empty = st.columns([0.15, 0.15, 0.7])
                    if col_edit.button("📝 수정", key=f"edit_btn_{p['id']}"):
                        st.session_state.community_mode = "edit"
                        st.session_state.editing_post = p
                        st.rerun()
                    
                    if col_del.button("🗑️ 삭제", key=f"del_btn_{p['id']}"):
                        if db.delete_community_post(p['id']):
                            st.warning("삭제되었습니다."); time.sleep(0.5); st.rerun()
                    
                    st.divider()
                    
                    comments = db.get_comments(p['id'])
                    if comments:
                        st.markdown("#### 💬 현장 대원 답변")
                        for c in comments:
                            st.markdown(f"""<div class="comment-box">
                                <strong>{c['author']} 대원:</strong><br>{c['content']}
                            </div>""", unsafe_allow_html=True)
                            
                            st.markdown('<div class="promo-ready">', unsafe_allow_html=True)
                            if st.button("💎 이 답변을 정식 지식으로 등록", key=f"promo_{c['id']}", use_container_width=True):
                                success, msg = db.promote_to_knowledge(
                                    p['title'], c['content'], 
                                    p.get('manufacturer','미지정'), 
                                    p.get('model_name','미지정'), 
                                    p.get('measurement_item','공통')
                                )
                                if success: st.success("지식 승격 완료!"); time.sleep(1); st.rerun()
                                else: st.error(f"실패: {msg}")
                            st.markdown('</div>', unsafe_allow_html=True)

                    with st.form(key=f"comment_form_{p['id']}"):
                        c_author = st.text_input("내 이름", key=f"ca_{p['id']}")
                        c_content = st.text_area("답변 내용", key=f"cc_{p['id']}")
                        if st.form_submit_button("💬 답변 달기"):
                            if c_author and c_content:
                                if db.add_comment(p['id'], c_author, c_content):
                                    st.success("답변 저장!"); st.rerun()
