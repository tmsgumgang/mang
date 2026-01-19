import streamlit as st
import time

def show_community_ui(ai_model, db):
    # ----------------------------------------------------------------------
    # [Style] CSS 스타일 정의
    # ----------------------------------------------------------------------
    st.markdown("""<style>
        .comment-box { 
            background-color: rgba(0, 74, 153, 0.1); 
            padding: 15px; 
            border-radius: 8px; 
            border-left: 5px solid #004a99; 
            margin-bottom: 12px; 
            color: inherit !important; 
        }
        .comment-box strong { color: #d97706 !important; }
    </style>""", unsafe_allow_html=True)

    st.subheader("👥 현장 지식 커뮤니티 (Q&A)")

    if "community_mode" not in st.session_state:
        st.session_state.community_mode = "list"

    # [UI] 상단 버튼 영역
    c1, c2 = st.columns([0.8, 0.2])
    with c2:
        if st.session_state.community_mode == "list":
            if st.button("✍️ 질문 등록", use_container_width=True):
                st.session_state.community_mode = "write"
                st.rerun()
        elif st.session_state.community_mode in ["write", "edit"]:
             if st.button("목록으로", use_container_width=True):
                st.session_state.community_mode = "list"
                st.rerun()

    # ----------------------------------------------------------------------
    # [UI] 글쓰기 / 수정 모드
    # ----------------------------------------------------------------------
    if st.session_state.community_mode in ["write", "edit"]:
        is_edit = st.session_state.community_mode == "edit"
        post_data = st.session_state.get("editing_post", {})
        
        with st.form("post_form_v168"):
            st.markdown(f"### 📝 {'질문 수정' if is_edit else '새로운 질문 등록'}")
            
            author = st.text_input("작성자 (필수)", value=post_data.get("author", ""), disabled=is_edit, placeholder="닉네임을 입력하세요")
            title = st.text_input("질문 제목 (필수)", value=post_data.get("title", ""))
            content = st.text_area("고장 현상 및 내용 (필수)", value=post_data.get("content", ""), height=150)
            
            st.markdown("---")
            st.markdown("🏷️ **장비 라벨링 정보 (필수)**")
            c1, c2, c3 = st.columns(3)
            mfr = c1.text_input("제조사", value=post_data.get("manufacturer", ""))
            mod = c2.text_input("모델명", value=post_data.get("model_name", ""))
            itm = c3.text_input("측정항목", value=post_data.get("measurement_item", ""))
            
            b1, b2 = st.columns(2)
            if b1.form_submit_button("🚀 등록/수정 완료"):
                if author and title and content and mfr:
                    if is_edit: success = db.update_community_post(post_data['id'], title, content, mfr, mod, itm)
                    else: success = db.add_community_post(author, title, content, mfr, mod, itm)
                    
                    if success:
                        st.success("반영 완료!")
                        time.sleep(0.5)
                        st.session_state.community_mode = "list"
                        st.rerun()
                    else: st.error("DB 처리 실패")
                else: st.error("작성자, 제목, 내용, 제조사는 필수입니다.")
            
            if b2.form_submit_button("❌ 취소"):
                st.session_state.community_mode = "list"
                st.rerun()

    # ----------------------------------------------------------------------
    # [UI] 게시글 목록 모드
    # ----------------------------------------------------------------------
    else:
        posts = db.get_community_posts()
        if not posts: st.warning("등록된 질문이 없습니다.")
        else:
            for p in posts:
                label_tag = f"[{p.get('measurement_item') or '-'}] {p.get('model_name') or '공통'}"
                with st.expander(f"📌 {label_tag} {p['title']} (작성자: {p.get('author', '익명')})"):
                    st.write(p['content'])
                    st.caption(f"제조사: {p.get('manufacturer') or '미지정'} | 작성일: {str(p.get('created_at', ''))[:10]}")
                    
                    c_edit, c_del, _ = st.columns([0.15, 0.15, 0.7])
                    if c_edit.button("📝 수정", key=f"ed_{p['id']}"):
                        st.session_state.community_mode = "edit"; st.session_state.editing_post = p; st.rerun()
                    if c_del.button("🗑️ 삭제", key=f"dl_{p['id']}"):
                        if db.delete_community_post(p['id']): st.warning("삭제됨"); time.sleep(0.5); st.rerun()
                    
                    st.divider()
                    comments = db.get_comments(p['id'])
                    if comments:
                        st.markdown("#### 💬 현장 대원 답변 (AI 지식 자동 동기화)")
                        for c in comments:
                            st.markdown(f"""<div class="comment-box">
                                <strong>{c['author']} 대원:</strong><br>{c['content']}
                            </div>""", unsafe_allow_html=True)

                    # -------------------------------------------------------
                    # [UI 개선] 답변 작성 폼 (가독성 및 필수 입력 강조)
                    # -------------------------------------------------------
                    st.markdown("#### 💡 답변 남기기")
                    with st.form(key=f"cf_{p['id']}"):
                        # [변경] 컬럼(col1, col2) 제거 -> 위아래 배치로 변경하여 입력칸 확보
                        c_author = st.text_input("👤 답변자 닉네임 (필수)", key=f"ca_{p['id']}", placeholder="본인의 이름을 입력해주세요")
                        c_content = st.text_area("답변 내용", key=f"cc_{p['id']}", placeholder="증상 해결 방법이나 조언을 입력해주세요")
                        
                        if st.form_submit_button("🚀 답변 등록 (AI 지식으로 자동 저장)"):
                            # [유효성 검사] 이름이 없으면 절대 통과 불가
                            if c_author.strip() and c_content.strip():
                                if db.add_comment(p['id'], c_author, c_content):
                                    # [지식 승격] 작성자 정보 포함하여 전달
                                    success, msg = db.promote_to_knowledge(
                                        p['title'], 
                                        c_content, 
                                        p.get('manufacturer','미지정'), 
                                        p.get('model_name','미지정'), 
                                        p.get('measurement_item','공통'),
                                        c_author 
                                    )
                                    if success:
                                        st.success(f"🎉 {c_author}님의 답변이 등록되고, AI 지식베이스에 추가되었습니다!")
                                        time.sleep(1.5)
                                        st.rerun()
                                    else: st.error(f"지식 동기화 실패: {msg}")
                            else:
                                st.error("⚠️ [답변자 닉네임]과 [내용]을 모두 입력해야 등록됩니다!")
