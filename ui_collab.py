import streamlit as st
import pandas as pd
import time
from datetime import datetime, timedelta, timezone

# 캘린더 라이브러리 임포트
try:
    from streamlit_calendar import calendar
except ImportError:
    st.error("⚠️ 'streamlit-calendar' 라이브러리가 필요합니다.")
    calendar = None

def show_collab_ui(db):
    # [CSS] 모바일 최적화 & 디자인 정의
    st.markdown("""<style>
        /* 연락처 카드 (PC/모바일 반응형) */
        .contact-card {
            background-color: white;
            border: 1px solid #e2e8f0;
            border-radius: 12px;
            padding: 16px;
            margin-bottom: 12px;
            box-shadow: 0 2px 4px rgba(0,0,0,0.05);
        }
        .comp-name { font-size: 1.1rem; font-weight: bold; color: #1e293b; }
        .rank-badge { font-size: 0.8rem; background: #e0f2fe; color: #0284c7; padding: 2px 6px; border-radius: 4px; margin-left: 5px; }
        .phone-btn {
            display: inline-block;
            text-decoration: none;
            color: #2563eb;
            font-weight: bold;
            background: #eff6ff;
            padding: 6px 12px;
            border-radius: 20px;
            margin-top: 8px;
        }
        
        /* 캘린더 모바일 최적화 CSS */
        @media (max-width: 600px) {
            .fc-toolbar-title { font-size: 1.0rem !important; }
            .fc-header-toolbar { flex-direction: column; gap: 5px; }
            .fc-event { font-size: 0.75rem !important; } /* 글자 크기 축소 */
        }
    </style>""", unsafe_allow_html=True)

    # 탭 구성
    tab1, tab2 = st.tabs(["📅 일정 & 당직", "📒 업체 연락처"])

    # ------------------------------------------------------------------
    # [Tab 1] 일정 & 당직 (모바일 가독성 개선)
    # ------------------------------------------------------------------
    with tab1:
        if calendar is None: return 

        c1, c2 = st.columns([3, 1.2]) 
        
        with c1:
            st.subheader("📆 월간/주간 일정")
            
            # [Tip] 모바일 가이드
            st.caption("💡 모바일에서는 우측 상단 **'주간(Week)'** 버튼을 누르면 보기가 훨씬 편합니다!")

            if "selected_event" not in st.session_state:
                st.session_state.selected_event = None

            schedules = db.get_schedules()
            duties = db.get_duty_roster()
            
            calendar_events = []
            
            # 일정 데이터
            color_map = {"점검": "#3b82f6", "월간": "#8b5cf6", "회의": "#10b981", "행사": "#f59e0b", "기타": "#6b7280"}
            if schedules:
                for s in schedules:
                    cat = s.get('category', '기타')
                    calendar_events.append({
                        "title": f"[{cat}] {s['title']}",
                        "start": s['start_time'],
                        "end": s['end_time'],
                        "backgroundColor": color_map.get(cat, "#6b7280"),
                        "borderColor": color_map.get(cat, "#6b7280"),
                        "extendedProps": {
                            "type": "schedule",
                            "id": str(s['id']),
                            "real_title": s['title'],
                            "description": s.get('description', ''),
                            "user": s.get('created_by', ''),
                            "category": cat,
                            "location": s.get('location', '')
                        }
                    })

            # 당직 데이터
            if duties:
                for d in duties:
                    calendar_events.append({
                        "title": f"👮‍♂️ {d['worker_name']}",
                        "start": d['date'],
                        "allDay": True,
                        "backgroundColor": "#16a34a",
                        "borderColor": "#16a34a",
                        "display": "block",
                        "extendedProps": {
                            "type": "duty",
                            "id": str(d['id']),
                            "worker_name": d['worker_name'],
                            "date": d['date']
                        }
                    })

            # [V262] 캘린더 옵션: 'dayGridWeek' (주간) 뷰 추가 -> 모바일 구세주!
            calendar_options = {
                "headerToolbar": {
                    "left": "prev,next today",
                    "center": "title",
                    "right": "dayGridMonth,dayGridWeek,listMonth" # 주간 뷰 추가
                },
                "buttonText": {
                    "today": "오늘",
                    "dayGridMonth": "월간",
                    "dayGridWeek": "주간(추천)", # 모바일 추천
                    "listMonth": "리스트"
                },
                "initialView": "dayGridMonth",
                "locale": "ko",
                "navLinks": True, 
                "selectable": True, 
                "dayMaxEvents": 3, # 3개 넘어가면 +more 처리 (깔끔하게)
                "height": "auto"
            }
            
            cal_state = calendar(events=calendar_events, options=calendar_options, key="my_calendar")

            if cal_state.get("eventClick"):
                st.session_state.selected_event = cal_state["eventClick"]["event"]

            # --- 수정 폼 (기존 유지) ---
            if st.session_state.selected_event:
                evt = st.session_state.selected_event
                props = evt["extendedProps"]
                e_type = props.get("type", "schedule")

                st.divider()
                if e_type == "schedule":
                    c_head, c_close = st.columns([9, 1])
                    c_head.info(f"✏️ **일정 수정**")
                    if c_close.button("❌", key="close_sch"):
                        st.session_state.selected_event = None
                        st.rerun()

                    with st.form(key=f"edit_sch_{props['id']}"):
                        e_title = st.text_input("제목", value=props['real_title'])
                        
                        cat_opts = ["점검", "월간", "회의", "행사", "기타", "직접입력"]
                        curr_cat = props['category']
                        idx = cat_opts.index(curr_cat) if curr_cat in cat_opts else 5
                        e_cat_select = st.selectbox("분류", cat_opts, index=idx)
                        e_cat_manual = ""
                        if e_cat_select == "직접입력":
                            e_cat_manual = st.text_input("직접 입력", value=curr_cat if curr_cat not in cat_opts[:-1] else "")
                        
                        e_loc = st.text_input("장소", value=props.get('location', ''))
                        e_desc = st.text_area("내용", value=props['description'])
                        
                        c_b1, c_b2 = st.columns(2)
                        if c_b1.form_submit_button("수정 저장"):
                            final_cat = e_cat_manual if e_cat_select == "직접입력" else e_cat_select
                            if db.update_schedule(props['id'], e_title, evt['start'], evt.get('end'), final_cat, e_desc, e_loc):
                                st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        if c_b2.form_submit_button("삭제"):
                            db.delete_schedule(props['id'])
                            st.success("삭제됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()

                elif e_type == "duty":
                    c_head, c_close = st.columns([9, 1])
                    c_head.success(f"👮‍♂️ **당직 수정**")
                    if c_close.button("❌", key="close_duty"):
                        st.session_state.selected_event = None
                        st.rerun()
                    with st.form(key=f"edit_duty_{props['id']}"):
                        new_name = st.text_input("근무자", value=props['worker_name'])
                        c1, c2 = st.columns(2)
                        if c1.form_submit_button("수정"):
                            db.set_duty_worker(props['date'], new_name)
                            st.success("수정됨"); st.session_state.selected_event=None; time.sleep(0.5); st.rerun()
                        if c2.form_submit_button("삭제"):
                            db.delete_duty_worker(props['id'])
                            st.rerun()

        # === [우측] 관리 패널 ===
        with c2:
            st.markdown("### 👮‍♂️ 당직 관리")
            d_tab1, d_tab2 = st.tabs(["📥 엑셀", "✍️ 수동"])
            
            with d_tab1:
                uploaded_file = st.file_uploader("당직표(A:날짜, B:이름)", type=['xlsx'])
                if uploaded_file and st.button("업로드"):
                    try:
                        df = pd.read_excel(uploaded_file)
                        for _, row in df.iterrows():
                            db.set_duty_worker(pd.to_datetime(row.iloc[0]).strftime("%Y-%m-%d"), str(row.iloc[1]))
                        st.success("완료!"); time.sleep(1); st.rerun()
                    except: st.error("오류 발생")

            with d_tab2:
                m_date = st.date_input("날짜", value=datetime.now().date())
                m_name = st.text_input("이름")
                if st.button("등록"):
                    if m_name:
                        db.set_duty_worker(str(m_date), m_name)
                        st.success("등록됨"); time.sleep(0.5); st.rerun()

            st.divider()
            st.markdown("### ➕ 일정 등록")
            cat_select = st.selectbox("분류", ["점검", "월간", "회의", "행사", "기타", "직접입력"], key="n_cat")
            cat_manual = st.text_input("분류명", key="n_man") if cat_select == "직접입력" else ""
            
            n_title = st.text_input("제목", key="n_tit")
            n_loc = st.text_input("장소", key="n_loc")
            
            nd1, nt1 = st.columns(2)
            n_date = nd1.date_input("날짜", key="n_d")
            n_time = nt1.time_input("시간", value=datetime.now().time(), key="n_t")
            n_desc = st.text_area("내용", key="n_dsc")
            n_user = st.text_input("등록자", "관리자", key="n_usr")
            
            if st.button("저장", type="primary", use_container_width=True):
                if n_title:
                    f_cat = cat_manual if cat_select == "직접입력" else cat_select
                    start = datetime.combine(n_date, n_time)
                    end = start + timedelta(hours=1)
                    db.add_schedule(n_title, start.isoformat(), end.isoformat(), f_cat, n_desc, n_user, n_loc)
                    st.success("저장됨"); time.sleep(0.5); st.rerun()

    # ------------------------------------------------------------------
    # [Tab 2] 연락처 관리 (V262: 수정 기능 & 직급 & 전화연결)
    # ------------------------------------------------------------------
    with tab2:
        st.subheader("📒 업체 연락처")
        
        # [State] 연락처 수정 모드
        if "edit_contact_id" not in st.session_state:
            st.session_state.edit_contact_id = None

        search_txt = st.text_input("🔍 검색", placeholder="업체, 담당자, 태그...")
        all_contacts = db.get_contacts()
        
        filtered = [c for c in all_contacts if search_txt.lower() in f"{c.get('company_name')} {c.get('person_name')} {c.get('tags')}".lower()] if search_txt else all_contacts

        if not filtered:
            st.info("데이터가 없습니다.")
        else:
            for c in filtered:
                c_id = c['id']
                
                # --- [A] 일반 보기 모드 ---
                if st.session_state.edit_contact_id != c_id:
                    # HTML 카드 렌더링
                    rank_html = f"<span class='rank-badge'>{c.get('rank')}</span>" if c.get('rank') else ""
                    phone = c.get('phone', '')
                    
                    st.markdown(f"""
                    <div class="contact-card">
                        <div class="comp-name">{c.get('company_name')}</div>
                        <div>👤 {c.get('person_name')} {rank_html}</div>
                        <a href="tel:{phone}" class="phone-btn">📞 {phone if phone else '번호 없음'}</a>
                        <div style="margin-top:8px; color:#64748b; font-size:0.9rem;">📧 {c.get('email','-')}</div>
                        <div style="font-size:0.85rem; color:#94a3b8;">🏷️ {c.get('tags','')}</div>
                        <div style="margin-top:5px; padding-top:5px; border-top:1px solid #f1f5f9; color:#475569;">{c.get('memo','')}</div>
                    </div>
                    """, unsafe_allow_html=True)
                    
                    # 수정 버튼
                    if st.button("✏️ 수정", key=f"btn_edit_{c_id}"):
                        st.session_state.edit_contact_id = c_id
                        st.rerun()

                # --- [B] 수정 모드 (같은 위치에 폼이 열림) ---
                else:
                    with st.container(border=True):
                        st.info("✏️ 연락처 수정 중...")
                        with st.form(key=f"edit_con_form_{c_id}"):
                            ec1, ec2 = st.columns(2)
                            e_comp = ec1.text_input("업체명", value=c['company_name'])
                            e_name = ec2.text_input("담당자", value=c.get('person_name',''))
                            
                            ec3, ec4 = st.columns(2)
                            e_rank = ec3.text_input("직급", value=c.get('rank',''))
                            e_phone = ec4.text_input("전화번호", value=c.get('phone',''))
                            
                            e_email = st.text_input("이메일", value=c.get('email',''))
                            e_tags = st.text_input("태그", value=c.get('tags',''))
                            e_memo = st.text_area("메모", value=c.get('memo',''))
                            
                            eb1, eb2, eb3 = st.columns([2, 2, 5])
                            if eb1.form_submit_button("💾 저장"):
                                db.update_contact(c_id, e_comp, e_name, e_phone, e_email, e_tags, e_memo, e_rank)
                                st.session_state.edit_contact_id = None
                                st.success("수정됨"); time.sleep(0.5); st.rerun()
                            
                            if eb2.form_submit_button("취소"):
                                st.session_state.edit_contact_id = None
                                st.rerun()
                                
                            if eb3.form_submit_button("🗑️ 삭제"):
                                db.delete_contact(c_id)
                                st.session_state.edit_contact_id = None
                                st.rerun()

        st.divider()
        with st.expander("➕ 새 연락처 등록하기"):
            with st.form("add_contact_new"):
                c1, c2 = st.columns(2)
                nc = c1.text_input("업체명 (필수)")
                nn = c2.text_input("담당자")
                c3, c4 = st.columns(2)
                nr = c3.text_input("직급") # 직급 추가
                np = c4.text_input("전화번호")
                ne = st.text_input("이메일")
                nt = st.text_input("태그")
                nm = st.text_area("메모")
                
                if st.form_submit_button("저장하기", type="primary"):
                    if nc:
                        # V262 db_services의 add_contact는 rank 인자를 받음
                        if db.add_contact(nc, nn, np, ne, nt, nm, nr):
                            st.success("저장되었습니다.")
                            time.sleep(0.5); st.rerun()
                    else:
                        st.error("업체명은 필수입니다.")
