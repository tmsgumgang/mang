import streamlit as st
import io
import time
import PyPDF2
# [V204] OCR 및 이미지 처리를 위한 라이브러리 추가
try:
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

from logic_ai import extract_metadata_ai, get_embedding, clean_text_for_db, semantic_split_v143

def show_admin_ui(ai_model, db):
    st.title("🔧 관리자 및 데이터 엔지니어링")
    
    # 탭 구성
    tabs = st.tabs(["🧹 현황", "📂 매뉴얼 학습", "📝 지식 등록", "🚨 분류실", "🏗️ 재건축", "🏷️ 승인"])
    
    # 1. 현황 대시보드
    with tabs[0]:
        st.subheader("🧹 데이터 현황 대시보드")
        try:
            k_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count
            m_cnt = db.supabase.table("manual_base").select("id", count="exact").execute().count
            c1, c2 = st.columns(2)
            c1.metric("경험 지식", f"{k_cnt}건")
            c2.metric("매뉴얼 데이터", f"{m_cnt}건")
        except:
            st.warning("DB 연결 상태를 확인해주세요.")

    # 2. 매뉴얼 학습 (V204 OCR 탑재)
    with tabs[1]:
        show_manual_upload_ui(ai_model, db)

    # 3. 지식 직접 등록
    with tabs[2]:
        show_knowledge_reg_ui(ai_model, db)

    # 4. 수동 분류실
    with tabs[3]:
        st.subheader("🚨 제조사 미지정 데이터 정제")
        target = st.radio("조회 대상", ["경험", "매뉴얼"], horizontal=True, key="admin_cls_target")
        t_name = "knowledge_base" if target == "경험" else "manual_base"
        
        try:
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
            else: st.success("✅ 분류가 필요한 데이터가 없습니다.")
        except: st.error("데이터 로드 실패")

    # 5. 지식 재건축
    with tabs[4]:
        st.subheader("🏗️ 벡터 인덱스 재구성")
        if st.button("🛠️ 지식 재인덱싱 시작", type="primary"):
            rows = db.supabase.table("manual_base").select("id, content").execute().data
            if rows:
                pb = st.progress(0)
                for i, r in enumerate(rows):
                    db.update_vector("manual_base", r['id'], get_embedding(r['content']))
                    pb.progress((i+1)/len(rows))
                st.success("완료!")

    # 6. 라벨 승인
    with tabs[5]:
        st.subheader("🏷️ AI 라벨링 승인 대기")
        staging = db.supabase.table("manual_base").select("*").eq("semantic_version", 2).limit(3).execute().data
        if staging:
            for r in staging:
                with st.form(key=f"admin_aprv_{r['id']}"):
                    st.write(r.get('content')[:300])
                    mfr = st.text_input("제조사", r.get('manufacturer',''))
                    mod = st.text_input("모델명", r.get('model_name',''))
                    itm = st.text_input("항목", r.get('measurement_item',''))
                    if st.form_submit_button("✅ 승인"): 
                        db.update_record_labels("manual_base", r['id'], mfr, mod, itm)
                        st.rerun()
        else: st.info("승인 대기 중인 데이터가 없습니다.")

# [V204] 업로드 함수 (OCR 엔진 통합)
def show_manual_upload_ui(ai_model, db):
    st.subheader("📂 PDF 매뉴얼 업로드 (V204 OCR Engine)")
    
    # [V204] OCR 옵션 UI
    col_u1, col_u2 = st.columns([3, 1])
    up_f = col_u1.file_uploader("PDF 파일 선택", type=["pdf"])
    use_ocr = col_u2.checkbox("OCR(이미지 스캔) 사용", help="스캔된 문서나 이미지 위주의 PDF일 경우 체크하세요. 속도가 느릴 수 있습니다.")
    
    if not OCR_AVAILABLE and use_ocr:
        st.warning("⚠️ 서버에 Tesseract/Poppler가 설치되지 않아 OCR을 사용할 수 없습니다. (관리자 문의)")

    if up_f and st.button("🚀 학습 시작", use_container_width=True, type="primary"):
        with st.status("데이터 처리 중...", expanded=True) as status:
            try:
                raw_text = ""
                
                # 1. 텍스트 추출 (OCR vs 일반)
                if use_ocr and OCR_AVAILABLE:
                    status.write("📷 OCR 엔진 가동 중 (이미지 → 텍스트 변환)...")
                    # PDF를 이미지 리스트로 변환
                    images = convert_from_bytes(up_f.read())
                    total_pages = len(images)
                    
                    # 각 페이지별로 OCR 수행
                    ocr_prog = st.progress(0)
                    for idx, img in enumerate(images):
                        # 한글+영어 혼용 인식
                        page_text = pytesseract.image_to_string(img, lang='kor+eng')
                        raw_text += page_text + "\n"
                        ocr_prog.progress((idx + 1) / total_pages)
                        status.write(f"  - {idx+1}/{total_pages} 페이지 스캔 완료")
                    
                    status.write("✅ OCR 변환 완료!")
                    
                else:
                    status.write("📖 PDF 텍스트 레이어 읽는 중...")
                    pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                    raw_text = "\n".join([p.extract_text() or "" for p in pdf_r.pages])

                if len(raw_text.strip()) < 50:
                    st.warning("⚠️ 추출된 텍스트가 너무 적습니다. 문서가 이미지라면 'OCR 사용'을 체크해주세요.")

                # 2. 청킹
                status.write("✂️ 문맥 단위 분할 중...")
                chunks = semantic_split_v143(raw_text)
                
                # 3. AI 분석 및 저장
                progress_bar = st.progress(0)
                total = len(chunks)
                
                for i, chunk in enumerate(chunks):
                    status.write(f"🧠 AI 분석 중 ({i+1}/{total})...")
                    
                    # 메타데이터 추출
                    meta = extract_metadata_ai(ai_model, chunk)
                    
                    # [V203 방어 로직 유지]
                    if isinstance(meta, list):
                        if len(meta) > 0 and isinstance(meta[0], dict): meta = meta[0]
                        else: meta = {}
                    if not isinstance(meta, dict): meta = {}

                    # DB 저장
                    db.supabase.table("manual_base").insert({
                        "domain": "기술지식", 
                        "content": clean_text_for_db(chunk), 
                        "file_name": up_f.name, 
                        "manufacturer": meta.get('manufacturer','미지정'), 
                        "model_name": meta.get('model_name','미지정'), 
                        "measurement_item": meta.get('measurement_item','공통'), 
                        "embedding": get_embedding(chunk), 
                        "semantic_version": 2
                    }).execute()
                    
                    progress_bar.progress((i + 1) / total)
                
                status.update(label="✅ 학습 완료!", state="complete", expanded=False)
                st.success(f"총 {total}개의 지식 블록이 생성되었습니다.")
                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")
                print(f"DEBUG Error: {e}")

# [V164 유지] 지식 직접 등록 함수
def show_knowledge_reg_ui(ai_model, db):
    st.subheader("📝 지식 직접 등록")
    with st.form("admin_reg_knowledge_v164"):
        st.info("💡 현장 경험 지식을 직접 데이터베이스에 등록합니다.")
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
# [End of File]
