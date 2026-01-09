import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time
from collections import Counter

# [보안] Streamlit Secrets
try:
    SUPABASE_URL = st.secrets["SUPABASE_URL"]
    SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
    GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
except KeyError:
    st.error("⚠️ Secrets 설정이 누락되었습니다.")
    st.stop()

@st.cache_resource
def init_clients():
    supabase_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    genai.configure(api_key=GEMINI_API_KEY)
    chat_model = genai.GenerativeModel('gemini-2.0-flash') 
    return supabase_client, chat_model

try:
    supabase, ai_model = init_clients()
except Exception as e:
    st.error(f"시스템 연결 실패: {e}")

# --- 핵심 헬퍼 함수 ---
def keep_db_alive():
    try: supabase.table("knowledge_base").select("id").limit(1).execute()
    except: pass

def clean_text_for_db(text):
    if not text: return ""
    text = text.replace("\u0000", "")
    return "".join(ch for ch in text if ch.isprintable() or ch in ['\n', '\r', '\t']).strip()

def get_embedding(text):
    clean_txt = clean_text_for_db(text)
    if not clean_txt: return [0.0] * 768
    result = genai.embed_content(model="models/text-embedding-004", content=clean_txt, task_type="retrieval_document")
    return result['embedding']

def extract_json(text):
    try:
        cleaned = re.sub(r'```json\s*|```', '', text).strip()
        return json.loads(cleaned)
    except: return None

def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists:
            supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
    except: pass

# [V110] 페널티 데이터 조회를 위한 블랙리스트 카운트
def get_global_irrelevant_counts():
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").execute()
        ids = [r['source_id'] for r in res.data]
        return Counter(ids)
    except: return {}

def update_category_v110(source_id, new_cat):
    try:
        prefix, row_id = source_id.split("_")
        table = "knowledge_base" if prefix == "EXP" else "manual_base"
        supabase.table(table).update({"category": new_cat}).eq("id", int(row_id)).execute()
        return True
    except: return False

def display_tag_v110(u_key, category):
    prefix = "경험지식" if "EXP" in u_key else "매뉴얼"
    icon = "🛠️" if "측정기기" in category else ("🌊" if "채수펌프" in category else "🍴")
    return f"{icon} {prefix}_{u_key.split('_')[1]} ({category})"

def analyze_query_v110(text):
    if not text: return "측정기기", None, None, None
    if any(k in text for k in ["맛집", "식당", "카페", "추천", "주차", "메뉴", "짜글이"]): return "일상", None, None, None
    if any(k in text for k in ["펌프", "채수", "배관", "토출", "흡입", "볼륨", "호스"]): return "채수펌프", None, None, None
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    item_keys = ["TOC", "TN", "TP", "VOC", "PH", "DO", "TUR", "EC", "온도"]
    found_item = next((k for k in item_keys if k.lower() in text.lower()), None)
    m_match = re.search(r'(\d{2,})', text)
    found_mod = m_match.group(1) if m_match else None
    return "측정기기", found_mfr, found_mod, found_item

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .guide-box { background-color: rgba(240, 253, 244, 0.1); border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 15px; color: #166534; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 4px solid #004a99; padding: 8px 12px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 12px; display: flex; flex-wrap: wrap; gap: 12px; line-height: 1.5; }
    .meta-item { display: flex; align-items: center; gap: 5px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V110: 무관 사유 입력 및 페널티 반영) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("최적의 답변을 생성 중입니다..."):
            try:
                target_cat, t_mfr, t_mod, t_item = analyze_query_v110(user_q)
                if "생활정보" in search_mode: target_cat = "일상"
                
                query_vec = get_embedding(user_q)
                blacklist_ids = get_blacklist(user_q)
                
                # [V110] 전역 페널티 정보 가져오기
                irr_counts = get_global_irrelevant_counts()
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 60}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()
                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    d_cat_raw = str(d.get('category') or '측정기기')
                    d_cat = "일상" if any(k in d_cat_raw for k in ["일상", "맛집"]) else ("채수펌프" if "펌프" in d_cat_raw else "측정기기")
                    if target_cat != d_cat: continue
                    
                    # 가중치 계산
                    bonus = 0.5 if target_cat == "측정기기" and (t_mfr and t_mfr.upper() in str(d.get('manufacturer') or '').upper() or t_item and t_item.upper() in str(d.get('measurement_item') or '').upper()) else 0
                    
                    # [V110 핵심] 페널티 로직 반영
                    irr_penalty = irr_counts.get(u_key, 0) * 0.03
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = (d.get('similarity') or 0) + bonus + ((d.get('helpful_count') or 0) * 0.01) - irr_penalty
                        d['source_id_tag'], d['final_cat'] = u_key, d_cat
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    context = "\n".join([f"[{display_tag_v110(d['source_id_tag'], d['final_cat'])}]: {d.get('solution') or d.get('content')}" for d in final_pool[:12]])
                    ans_p = f"수질 전문가 답변. 분류: {target_cat}. 질문: {user_q} \n 데이터: {context} \n 요약 후 출처 표기."
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    st.markdown('<div class="guide-box">💡 <b>교정 가이드</b>: 잘못된 지식은 사유를 입력하여 교정해 주세요. 사유가 누적되면 시스템이 자동으로 검색 순위를 낮춥니다.</div>', unsafe_allow_html=True)
                    for i, d in enumerate(final_pool[:10]):
                        s_tag, d_tag = d['source_id_tag'], display_tag_v110(d['source_id_tag'], d['final_cat'])
                        with st.expander(f"{i+1}. [{d_tag}] {str(d.get('issue') or '상세 지식')[:35]}..."):
                            st.markdown(f"""<div class="meta-bar">
                                <div class="meta-item">🏢 제조사: <b>{d.get('manufacturer', '미지정')}</b></div>
                                <div class="meta-item">🏷️ 모델: <b>{d.get('model_name', '미지정')}</b></div>
                                <div class="meta-item">🧪 항목: <b>{d.get('measurement_item', '공통')}</b></div>
                            </div>""", unsafe_allow_html=True)
                            
                            if d.get('issue'): st.markdown(f"**🚩 현상**: {d['issue']}\n\n**🛠️ 조치**: {d['solution']}")
                            else: st.markdown(f"**📄 매뉴얼 내용**\n{d['content']}")
                            
                            c1, c2 = st.columns(2)
                            if c1.button("👍 도움됨", key=f"ok_{s_tag}_{i}", use_container_width=True):
                                prefix, rid = s_tag.split("_")
                                supabase.table("knowledge_base" if prefix=="EXP" else "manual_base").update({"helpful_count": (d.get('helpful_count') or 0)+1}).eq("id", int(rid)).execute()
                                st.toast("추천이 반영되었습니다!"); time.sleep(0.5); st.rerun()
                            with c2:
                                with st.popover("❌ 무관함 / 교정", use_container_width=True):
                                    # [V110 핵심] 분류 선택 및 수동 사유 입력
                                    st.write("**지식 품질 교정**")
                                    fix_cat = st.selectbox("올바른 분류 선택", ["측정기기", "채수펌프", "일상(맛집/정보)"], key=f"fix_cat_{s_tag}_{i}")
                                    fix_reason = st.text_area("무관한 사유 입력", placeholder="예: 브랜드 오인식, 내용 불일치, 구버전 정보 등", key=f"fix_res_{s_tag}_{i}")
                                    
                                    if st.button("교정 완료 및 검색 제외", key=f"btn_fix_{s_tag}_{i}", type="primary", use_container_width=True):
                                        with st.status("🛠️ 지식 품질 반영 중...", expanded=True) as status:
                                            # 1. DB 카테고리 업데이트
                                            update_category_v110(s_tag, fix_cat)
                                            st.write("✅ 데이터베이스 분류 수정 완료")
                                            # 2. 블랙리스트 및 상세 사유 저장
                                            supabase.table("knowledge_blacklist").insert({
                                                "query": user_q, 
                                                "source_id": s_tag, 
                                                "reason": f"현장교정({fix_cat})",
                                                "comment": fix_reason
                                            }).execute()
                                            st.write("🚫 신고 사유 학습 및 검색 제외 처리 완료")
                                            status.update(label="🎉 지식 정제가 완료되었습니다!", state="complete", expanded=False)
                                            time.sleep(1.0)
                                        st.rerun()
                else:
                    st.warning(f"⚠️ '{target_cat}' 분류에서 지식을 찾지 못했습니다.")
                    log_unsolved(user_q, f"분류({target_cat}) 내 검색결과 없음", "일상" in target_cat)
            except Exception as e: st.error(f"조회 실패 (V110): {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    with st.form("reg_v110", clear_on_submit=True):
        cat_sel = st.selectbox("카테고리", ["측정기기", "채수펌프", "일상(맛집/정보)"])
        c1, c2 = st.columns(2)
        if "일상" not in cat_sel:
            m_sel, m_man = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]), c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목")
        else: res_n, res_l = c1.text_input("상호명"), c2.text_input("위치")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("상황/제목"), st.text_area("조치/설명")
        if st.form_submit_button("✅ 지식 저장"):
            f_m = (m_man if m_sel == "직접 입력" else m_sel) if "일상" not in cat_sel else "생활정보"
            f_mod, f_it = (model_n, item_n) if "일상" not in cat_sel else (res_l, "")
            if iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": f_m, "model_name": f_mod, "measurement_item": f_it, "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": reg_n, "embedding": get_embedding(f"{cat_sel} {f_m} {f_it} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서 등록 (V101 로직 유지) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        doc_cat = st.selectbox("문서 분류", ["측정기기", "채수펌프", "일상"])
        up_f.seek(0)
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("정보 분석 중..."):
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_r.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"제조사 추출: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        c1, c2 = st.columns(2)
        f_mfr, f_model = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 지식 학습 시작"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"category": doc_cat, "manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_f.name, "page_num": (i//2)+1, "embedding": get_embedding(chunk)}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("✅ 학습 완료!"); st.rerun()

# --- 4. 데이터 전체 관리 ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록"])
    with t2:
        ms = st.text_input("🔍 경험 검색", placeholder="검색하거나 비워두면 최신 50건 노출")
        res = supabase.table("knowledge_base").select("*").order("created_at", desc=True).limit(50).execute()
        if ms: res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%,solution.ilike.%{ms}%").execute()
        for r in res.data:
            with st.expander(f"[{r.get('category')}] {r.get('manufacturer')} | {r['issue']}"):
                with st.form(key=f"ed_{r['id']}"):
                    n_cat = st.selectbox("분류", ["측정기기", "채수펌프", "일상(맛집/정보)"], index=["측정기기", "채수펌프", "일상(맛집/정보)"].index(r.get('category', '측정기기')))
                    n_sol = st.text_area("내용", value=r['solution'])
                    if st.form_submit_button("저장"):
                        supabase.table("knowledge_base").update({"category": n_cat, "solution": n_sol}).eq("id", r['id']).execute(); st.rerun()
                if st.button("🗑️ 삭제", key=f"del_e_{r['id']}"): supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()
    with t3:
        ds = st.text_input("🔍 매뉴얼 파일 검색")
        res_m = supabase.table("manual_base").select("*").order("created_at", desc=True).limit(100).execute()
        if ds: res_m = res_m.or_(f"file_name.ilike.%{ds}%").execute()
        for f in list(set([r['file_name'] for r in res_m.data if r.get('file_name')])):
            with st.expander(f"📄 {f}"):
                if st.button("🗑️ 전체 삭제", key=f"df_{f}"): supabase.table("manual_base").delete().eq("file_name", f).execute(); st.rerun()
    with t4:
        st.subheader("🚫 부적합 지식 및 교정 사유 로그")
        bl = supabase.table("knowledge_blacklist").select("*").order("created_at", desc=True).execute().data
        if bl:
            df_bl = pd.DataFrame(bl)
            st.dataframe(df_bl.rename(columns={'query': '검색어', 'source_id': 'ID', 'reason': '분류교정', 'comment': '사용자사유'})[['검색어', 'ID', '분류교정', '사용자사유']], use_container_width=True)

# --- 5. 질문 게시판 ---
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    st.subheader("💬 질문 게시판")
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q_d = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.info(q_d['content'])
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_d['id']).execute().data
        for a in ans_d: st.write(f"**{a['author']}**: {a['content']}")
        with st.form("ans_v110"):
            at, ct = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q_d['id'], "author": at, "content": ct}).execute(); st.rerun()
    else:
        with st.popover("➕ 질문하기"):
            with st.form("q_v110"):
                tit, auth, cont = st.text_input("제목"), st.text_input("작성자"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    supabase.table("qa_board").insert({"title": tit, "author": auth, "content": cont, "category": "일반"}).execute(); st.rerun()
        for q_r in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            if st.button(f"❓ {q_r['title']} (작성: {q_r['author']})", key=f"q_{q_r['id']}", use_container_width=True):
                st.session_state.selected_q_id = q_r['id']; st.rerun()

# --- 6. 미해결 과제 ---
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문")
    unsolved = supabase.table("unsolved_questions").select("*").eq("status", "대기중").order("created_at", desc=True).execute().data
    if not unsolved: st.success("✨ 대기 중인 과제가 없습니다!")
    else:
        for item in unsolved:
            with st.container():
                st.markdown(f"<div style='background:rgba(185, 28, 28, 0.1); padding:15px; border-radius:10px; border-left:5px solid #b91c1c; margin-bottom:10px;'><b>{item['query']}</b><br><small>사유: {item['reason']}</small></div>", unsafe_allow_html=True)
                with st.form(key=f"form_sos_{item['id']}"):
                    ans_in, c1, c2, c3 = st.text_area("조치법 입력"), st.columns(3)[0].text_input("제조사"), st.columns(3)[1].text_input("모델명"), st.columns(3)[2].text_input("측정항목")
                    if st.form_submit_button("✅ 지식으로 등록"):
                        if ans_in:
                            n_v = get_embedding(f"측정기기 {c1} {c2} {item['query']} {ans_in}")
                            supabase.table("knowledge_base").insert({"category": '측정기기', "manufacturer": c1, "model_name": c2, "measurement_item": c3, "issue": item['query'], "solution": ans_in, "embedding": n_v}).execute()
                            supabase.table("unsolved_questions").update({"status": "해결됨"}).eq("id", item['id']).execute(); st.rerun()
                st.divider()
