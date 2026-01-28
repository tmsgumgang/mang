import streamlit as st
import io
import time
import pdfplumber 

# OCR 라이브러리 (없으면 비활성화)
try:
    import pytesseract
    from pdf2image import convert_from_bytes
    OCR_AVAILABLE = True
except ImportError:
    OCR_AVAILABLE = False

# [V238] extract_triples_from_text 추가 임포트
from logic_ai import extract_metadata_ai, get_embedding, clean_text_for_db, semantic_split_v143, extract_triples_from_text

# =========================================================================
# [V241] 그래프 관계 매핑 (영어 DB값 -> 직관적인 한국어 UI)
# =========================================================================
REL_MAP = {
    "causes": "원인이다 (A가 B를 유발)",
    "part_of": "부품이다 (A는 B의 일부)",
    "solved_by": "해결된다 (A는 B로 해결)",
    "requires": "필요로 한다 (A는 B가 필요)",
    "has_status": "상태다 (A는 B라는 증상/상태)",
    "located_in": "위치한다 (A는 B에 있음)",
    "related_to": "관련되어 있다 (A와 B 연관)"
}

def show_admin_ui(ai_model, db):
    st.title("🔧 관리자 및 데이터 엔지니어링")
    
    # [V240] 탭 구성 유지
    tabs = st.tabs(["🧹 현황", "📂 매뉴얼 학습", "📝 지식 등록", "🚨 분류실", "🏗️ 재건축", "🏷️ 승인", "🛠️ 그래프 교정"])
    
    # 1. 현황 대시보드
    with tabs[0]:
        st.subheader("🧹 데이터 현황 대시보드")
        try:
            k_cnt = db.supabase.table("knowledge_base").select("id", count="exact").execute().count
            m_cnt = db.supabase.table("manual_base").select("id", count="exact").execute().count
            
            # [New] 그래프 데이터 개수 확인 (테이블 없으면 에러 방지)
            try:
                g_cnt = db.supabase.table("knowledge_graph").select("id", count="exact").execute().count
            except:
                g_cnt = 0 
            
            c1, c2, c3 = st.columns(3)
            c1.metric("경험 지식", f"{k_cnt}건")
            c2.metric("매뉴얼 데이터", f"{m_cnt}건")
            c3.metric("🕸️ 지식 그래프", f"{g_cnt}건")
        except:
            st.warning("DB 연결 상태를 확인해주세요.")

    # 2. 매뉴얼 학습 (Graph 기능 추가됨)
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

    # 5. 지식 재건축 (Graph 일괄 생성 기능 포함)
    with tabs[4]:
        st.subheader("🏗️ 데이터 구조 재설계 및 확장")
        
        c_rb1, c_rb2 = st.columns(2)
        
        # [A] 기존 기능: 벡터 임베딩 재생성
        with c_rb1:
            st.info("🔢 **벡터 인덱스(검색용)** 재구성")
            if st.button("🛠️ 벡터 재임베딩 시작", type="primary", use_container_width=True):
                rows = db.supabase.table("manual_base").select("id, content").execute().data
                if rows:
                    pb = st.progress(0)
                    for i, r in enumerate(rows):
                        db.update_vector("manual_base", r['id'], get_embedding(r['content']))
                        pb.progress((i+1)/len(rows))
                    st.success("매뉴얼 벡터 갱신 완료!")
        
        # [B] 신규 기능: 지식 그래프 일괄 생성 (경험 데이터 포함)
        with c_rb2:
            st.info("🕸️ **지식 그래프(관계도)** 일괄 생성")
            
            target_src = st.selectbox("변환 대상 선택", ["사람이 입력한 지식 (knowledge_base)", "PDF 매뉴얼 (manual_base)"])
            
            if st.button("🚀 그래프 변환 시작 (Graph ETL)", type="secondary", use_container_width=True):
                table = "knowledge_base" if "사람" in target_src else "manual_base"
                source_type_val = "knowledge" if "사람" in target_src else "manual"
                
                with st.status(f"'{table}' 데이터를 분석하여 연결 고리를 추출합니다...", expanded=True) as status:
                    data = db.supabase.table(table).select("*").execute().data
                    if not data:
                        st.warning("데이터가 없습니다.")
                    else:
                        total = len(data)
                        count = 0
                        pb2 = st.progress(0)
                        
                        for i, row in enumerate(data):
                            if table == "knowledge_base":
                                text_input = f"증상/이슈: {row.get('issue','')}\n해결책/노하우: {row.get('solution','')}"
                            else:
                                text_input = row.get('content', '')
                            
                            triples = extract_triples_from_text(ai_model, text_input)
                            
                            if triples:
                                db.save_knowledge_triples(row['id'], triples)
                                db.supabase.table("knowledge_graph")\
                                    .update({"source_type": source_type_val})\
                                    .eq("doc_id", row['id'])\
                                    .eq("source_type", "manual")\
                                    .execute() 
                                count += len(triples)
                                status.write(f"✅ ID {row['id']}: {len(triples)}개 관계 발견")
                            
                            pb2.progress((i+1)/total)
                        st.success(f"작업 끝! 총 {count}개의 새로운 지식 연결고리가 생성되었습니다.")

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

    # 7. [V242] 🛠️ 그래프 조회 및 직접 교정 (일괄 변경 기능 탑재)
    with tabs[6]:
        st.subheader("🛠️ 지식 그래프(Graph RAG) 탐색 및 교정")
        st.info("💡 관계식을 자연스러운 문장으로 읽고 수정하거나, 특정 단어를 일괄 변경하세요.")
        
        # [A] 일괄 변경 구역 (Bulk Action)
        with st.expander("🚀 단어 일괄 변경 (Bulk Rename) - '준비물' 한방에 바꾸기", expanded=False):
            bc1, bc2, bc3 = st.columns([2, 2, 1])
            b_old = bc1.text_input("변경 전 단어 (예: 준비물)", key="bulk_old")
            b_new = bc2.text_input("변경 후 단어 (예: 채수펌프 교체 준비물)", key="bulk_new")
            
            if bc3.button("⚡ 일괄 적용", use_container_width=True):
                if b_old and b_new:
                    success, cnt = db.bulk_rename_graph_node(b_old, b_new)
                    if success:
                        st.success(f"총 {cnt}개의 데이터가 '{b_old}' ➡️ '{b_new}' 로 변경되었습니다!")
                        time.sleep(1)
                        st.rerun()
                    else:
                        st.error(f"오류 발생: {cnt}")
                else:
                    st.warning("단어를 입력해주세요.")

        st.markdown("---")

        # [B] 개별 검색 및 수정 구역
        g_query = st.text_input("검색할 키워드 (예: 볼륨팩터, 준비물)", placeholder="수정하고 싶은 단어 입력")
        
        if st.button("🕸️ 관계 검색") and g_query:
            relations = db.search_graph_relations(g_query)
            if relations:
                st.success(f"총 {len(relations)}건의 연결 관계 발견!")
                
                # 헤더
                hc1, hc_mid1, hc2, hc_mid2, hc3, hc4 = st.columns([2.5, 0.5, 2.5, 0.5, 2.5, 1.5])
                hc1.caption("🔸 [A] 주어")
                hc_mid1.caption("는(은)")
                hc2.caption("🔸 [B] 목적어")
                hc_mid2.caption("의(로/에)")
                hc3.caption("➡️ 관계")
                hc4.caption("🛠️ 관리")

                relation_keys = list(REL_MAP.keys())

                for rel in relations:
                    rid = rel['id']
                    with st.form(key=f"edit_graph_{rid}"):
                        c1, c_mid1, c2, c_mid2, c3, c4 = st.columns([2.5, 0.5, 2.5, 0.5, 2.5, 1.5])
                        
                        e_src = c1.text_input("주어", value=rel['source'], label_visibility="collapsed")
                        c_mid1.markdown("<div style='text-align: center; margin-top: 10px;'>는</div>", unsafe_allow_html=True)
                        
                        e_tgt = c2.text_input("목적어", value=rel['target'], label_visibility="collapsed")
                        c_mid2.markdown("<div style='text-align: center; margin-top: 10px;'>의</div>", unsafe_allow_html=True)
                        
                        curr_rel = rel['relation']
                        opts = relation_keys if curr_rel in relation_keys else relation_keys + [curr_rel]
                        
                        e_rel = c3.selectbox(
                            "관계", 
                            options=opts, 
                            index=opts.index(curr_rel), 
                            format_func=lambda x: REL_MAP.get(x, x),
                            label_visibility="collapsed"
                        )
                        
                        bc1, bc2 = c4.columns(2)
                        save_btn = bc1.form_submit_button("💾")
                        del_btn = bc2.form_submit_button("🗑️")

                        if save_btn:
                            if db.update_graph_triple(rid, e_src, e_rel, e_tgt):
                                st.success("저장됨"); time.sleep(0.5); st.rerun()
                        
                        if del_btn:
                            if db.delete_graph_triple(rid):
                                st.warning("삭제됨"); time.sleep(0.5); st.rerun()
            else:
                st.warning("검색된 관계가 없습니다.")

# [V205 -> V238] 스마트 업로드 함수 (Graph 기능 통합)
def show_manual_upload_ui(ai_model, db):
    st.subheader("📂 PDF 매뉴얼 업로드 & 지식 그래프 구축")
    
    col_u1, col_u2 = st.columns([3, 1])
    up_f = col_u1.file_uploader("PDF 파일 선택", type=["pdf"])
    use_ocr = col_u2.checkbox("강제 OCR 사용", value=False, help="글자가 드래그되지 않는 '통이미지' 파일일 때만 켜세요.")
    
    c1, c2 = st.columns(2)
    btn_vector = c1.button("🚀 기본 학습 (Vector RAG)", use_container_width=True, type="primary")
    btn_graph = c2.button("🕸️ 지식 그래프 생성 (Graph RAG)", use_container_width=True)
    
    if up_f and (btn_vector or btn_graph):
        with st.status("데이터 정밀 분석 중...", expanded=True) as status:
            try:
                raw_text = ""
                if use_ocr and OCR_AVAILABLE:
                    status.write("📷 OCR 엔진 강제 구동 (이미지 스캔 중)...")
                    images = convert_from_bytes(up_f.read())
                    total_pages = len(images)
                    prog = st.progress(0)
                    for idx, img in enumerate(images):
                        raw_text += pytesseract.image_to_string(img, lang='kor+eng') + "\n"
                        prog.progress((idx+1)/total_pages)
                else:
                    status.write("📖 고정밀 텍스트 추출 중 (pdfplumber)...")
                    with pdfplumber.open(up_f) as pdf:
                        pages = pdf.pages
                        total_pages = len(pages)
                        prog = st.progress(0)
                        for idx, page in enumerate(pages):
                            page_text = page.extract_text()
                            if page_text: raw_text += page_text + "\n"
                            else: status.write(f"⚠️ {idx+1}페이지 텍스트 없음")
                            prog.progress((idx+1)/total_pages)

                if len(raw_text.strip()) < 100:
                    st.error("❌ 텍스트 추출 실패")
                    st.stop()

                status.write("✂️ 문맥 단위 분할 중...")
                chunks = semantic_split_v143(raw_text)
                total = len(chunks)
                progress_bar = st.progress(0)

                if btn_vector:
                    for i, chunk in enumerate(chunks):
                        status.write(f"🧠 [Vector] 지식 생성 중 ({i+1}/{total})...")
                        meta = extract_metadata_ai(ai_model, chunk)
                        if isinstance(meta, list): meta = meta[0] if meta else {}
                        if not isinstance(meta, dict): meta = {}

                        db.supabase.table("manual_base").insert({
                            "domain": "기술지식", 
                            "content": clean_text_for_db(chunk), 
                            "file_name": up_f.name, 
                            "manufacturer": db._clean_text(meta.get('manufacturer')), 
                            "model_name": db._clean_text(meta.get('model_name')), 
                            "measurement_item": db._normalize_tags(meta.get('measurement_item')), 
                            "embedding": get_embedding(chunk), 
                            "semantic_version": 2
                        }).execute()
                        progress_bar.progress((i + 1) / total)
                    st.success(f"✅ [Vector] 총 {total}개의 지식 블록이 생성되었습니다.")

                elif btn_graph:
                    status.write("🕸️ [Graph] 관계 데이터 추출 시작 (시간이 걸릴 수 있습니다)...")
                    graph_count = 0
                    for i, chunk in enumerate(chunks):
                        res = db.supabase.table("manual_base").insert({
                            "domain": "기술지식_GraphSource", 
                            "content": clean_text_for_db(chunk),
                            "file_name": up_f.name,
                            "semantic_version": 2
                        }).select("id").execute()
                        
                        if res.data:
                            doc_id = res.data[0]['id']
                            triples = extract_triples_from_text(ai_model, chunk)
                            if triples:
                                if db.save_knowledge_triples(doc_id, triples):
                                    graph_count += len(triples)
                                    status.write(f"🔗 {len(triples)}개의 관계 발견! -> DB 저장 완료")
                        progress_bar.progress((i + 1) / total)
                    st.success(f"✅ [Graph] 총 {graph_count}개의 인과관계 데이터(Triple)가 구축되었습니다!")

                time.sleep(1)
                st.rerun()
                
            except Exception as e:
                st.error(f"오류 발생: {str(e)}")

def show_knowledge_reg_ui(ai_model, db):
    st.subheader("📝 지식 직접 등록")
    with st.form("admin_reg_knowledge_v209"):
        st.info("💡 현장 경험 지식을 직접 데이터베이스에 등록합니다.")
        author = st.text_input("👤 지식 제공자 (등록자)", placeholder="본인의 이름을 입력하세요")
        f_iss = st.text_input("제목(이슈)")
        f_sol = st.text_area("해결방법/경험지식", height=200)
        c1, c2, c3 = st.columns(3)
        mfr = c1.text_input("제조사")
        mod = c2.text_input("모델명")
        itm = c3.text_input("측정항목")
        if st.form_submit_button("💾 지식 저장"):
            if f_iss and f_sol and mfr:
                success, msg = db.promote_to_knowledge(f_iss, f_sol, mfr, mod, itm, author or "익명")
                if success: st.success("✅ 저장 완료!"); time.sleep(0.5); st.rerun()
                else: st.error(f"저장 실패: {msg}")
            else:
                st.error("⚠️ 제목, 해결방법, 제조사는 필수 입력 항목입니다.")
