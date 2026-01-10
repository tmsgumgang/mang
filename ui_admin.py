import streamlit as st
import io, time
import PyPDF2
from logic_ai import *

def show_admin_ui(ai_model, db):
    tabs = st.tabs(["🧹 현황 대시보드", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
    
    with tabs[0]:
        k_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count
        m_cnt = db.supabase.table("manual_base").select("id", count="exact").execute().count
        c1, c2 = st.columns(2)
        c1.metric("경험 지식", f"{k_cnt}건")
        c2.metric("매뉴얼 데이터", f"{m_cnt}건")

    with tabs[1]:
        st.subheader("🚨 제조사 미지정 데이터 정제")
        target = st.radio("조회 대상", ["경험", "매뉴얼"], horizontal=True, key="admin_cls_target")
        t_name = "knowledge_base" if target == "경험" else "manual_base"
        unclass = db.supabase.table(t_name).select("*").or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').limit(5).execute().data
        if unclass:
            for r in unclass:
                with st.expander(f"ID {r['id']} 상세 내용"):
                    st.write(r.get('content') or r.get('solution') or r.get('issue'))
                    with st.form(key=f"admin_cls_{t_name}_{r['id']}"):
                        c1, c2, c3 = st.columns(3)
                        n_mfr = c1.text_input("제조사 (필수)", key=f"nm_{r['id']}")
                        n_mod = c2.text_input("모델명", key=f"no_{r['id']}")
                        n_itm = c3.text_input("항목", key=f"ni_{r['id']}")
                        batch_apply = st.checkbox("이 파일 일괄 적용", key=f"batch_{r['id']}") if r.get('file_name') else False
                        b1, b2 = st.columns(2)
                        if b1.form_submit_button("✅ 저장"):
                            if not n_mfr.strip(): st.error("제조사 필수")
                            else:
                                res = db.update_file_labels(t_name, r['file_name'], n_mfr, n_mod, n_itm) if batch_apply else db.update_record_labels(t_name, r['id'], n_mfr, n_mod, n_itm)
                                if res[0]: st.success(f"{res[1]}!"); time.sleep(0.5); st.rerun()
                        if b2.form_submit_button("🗑️ 폐기"):
                            if db.delete_record(t_name, r['id'])[0]: st.warning("삭제됨"); time.sleep(0.5); st.rerun()
        else: st.success("✅ 모든 데이터 분류 완료")

    with tabs[2]:
        st.subheader("🏗️ 벡터 인덱스 재구성")
        if st.button("🛠️ 지식 재인덱싱 시작", type="primary"):
            rows = db.supabase.table("manual_base").select("id, content").execute().data
            if rows:
                pb = st.progress(0)
                for i, r in enumerate(rows):
                    db.update_vector("manual_base", r['id'], get_embedding(r['content']))
                    pb.progress((i+1)/len(rows))
                st.success("완료!")

    with tabs[3]:
        st.subheader("🏷️ AI 라벨링 승인 대기")
        staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
        for r in staging:
            with st.form(key=f"admin_aprv_{r['id']}"):
                st.write(r.get('content')[:300])
                mfr, mod, itm = st.text_input("제조사", r.get('manufacturer','')), st.text_input("모델명", r.get('model_name','')), st.text_input("항목", r.get('measurement_item',''))
                if st.form_submit_button("✅ 승인"): db.update_record_labels("manual_base", r['id'], mfr, mod, itm); st.rerun()

def show_manual_upload_ui(ai_model, db):
    up_f = st.file_uploader("PDF 매뉴얼 업로드", type=["pdf"])
    if up_f and st.button("🚀 학습 시작", use_container_width=True):
        with st.status("학습 중..."):
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v143(all_t)
            for chunk in chunks:
                meta = extract_metadata_ai(ai_model, chunk)
                db.supabase.table("manual_base").insert({"domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name, "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'), "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2}).execute()
        st.success("업로드 및 학습 완료!"); st.rerun()

# [V164] 직접 등록 시에도 라벨링 필수화
def show_knowledge_reg_ui(ai_model, db):
    with st.form("admin_reg_knowledge_v164"):
        st.info("💡 본 데이터는 지식 베이스의 질적 향상을 위한 라벨링 수집용입니다. 정확한 장비 정보를 입력해 주세요.")
        f_iss = st.text_input("제목(이슈)")
        f_sol = st.text_area("해결방법/경험지식", height=200)
        c1, c2, c3 = st.columns(3)
        mfr = c1.text_input("제조사")
        mod = c2.text_input("모델명")
        itm = c3.text_input("측정항목")
        
        if st.form_submit_button("💾 지식 저장"):
            if f_iss and f_sol and mfr:
                success, msg = db.promote_to_knowledge(f_iss, f_sol, mfr, mod, itm)
                if success: st.success("저장 완료!"); time.sleep(0.5); st.rerun()
                else: st.error(f"저장 실패: {msg}")
            else:
                st.error("제목, 해결방법, 제조사는 필수 입력 항목입니다.")
