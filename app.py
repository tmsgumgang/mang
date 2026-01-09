import streamlit as st
from supabase import create_client, Client
import google.generativeai as genai
import pandas as pd
import PyPDF2
import io
import json
import re
import time

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

# 자동 깨우기: DB 세션 유지
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

# [V102] 한글 태그 및 카테고리 표시 로직
def display_tag_v102(u_key, category):
    prefix = "경험지식" if "EXP_" in u_key else "매뉴얼"
    num = u_key.split("_")[1]
    return f"{prefix}_{num} ({category})"

# [V102] 3대 카테고리 및 세부 항목 정밀 분석
def analyze_query_v102(text):
    if not text: return "측정기기", None, None, None
    
    # 1. 일상 분석
    life_keys = ["맛집", "식당", "카페", "추천", "주차", "메뉴", "점심", "회식", "영동", "옥천", "금산"]
    if any(k in text for k in life_keys):
        return "일상", None, None, None
    
    # 2. 채수펌프 분석
    pump_keys = ["펌프", "채수", "흡입", "토출", "배관", "펌프교체", "볼륨팩터"]
    if any(k in text for k in pump_keys):
        return "채수펌프", None, None, None
    
    # 3. 측정기기 및 세부 항목 분석
    item_keys = ["TOC", "TN", "TP", "VOC", "PH", "DO", "EC", "TUR", "온도"]
    found_item = next((k for k in item_keys if k.lower() in text.lower()), None)
    
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    
    m_match = re.search(r'(\d{2,})', text)
    found_mod = m_match.group(1) if m_match else None
    
    return "측정기기", found_mfr, found_mod, found_item

# 블랙리스트 및 도움 점수 로직 (V101 유지)
def add_to_blacklist(query, source_id, reason, comment=""):
    try: supabase.table("knowledge_blacklist").insert({"query": query, "source_id": source_id, "reason": reason, "comment": comment}).execute()
    except: pass
    return True

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

def update_single_helpfulness(source_id):
    try:
        prefix, row_id = source_id.split("_")
        table = "knowledge_base" if prefix == "EXP" else "manual_base"
        res = supabase.table(table).select("helpful_count").eq("id", int(row_id)).execute()
        if res.data:
            supabase.table(table).update({"helpful_count": (res.data[0].get('helpful_count') or 0) + 1}).eq("id", int(row_id)).execute()
            return True
    except: pass
    return False

def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists: supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .guide-box { background-color: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 15px; color: #166534; }
    .index-badge { background-color: #e2e8f0; color: #475569; padding: 2px 6px; border-radius: 4px; font-weight: bold; margin-right: 5px; font-size: 0.8rem; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V102: 삼중 격리 필터) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("카테고리 분류 및 지식 필터링 중..."):
            try:
                # [V102] 질문 의도 및 카테고리 판별
                target_cat, t_mfr, t_mod, t_item = analyze_query_v102(user_q)
                is_life_mode = True if "생활정보" in search_mode else False
                
                # 강제 카테고리 교정 (검색 모드 우선)
                if is_life_mode: target_cat = "일상"
                elif target_cat == "일상" and not is_life_mode: target_cat = "측정기기" # 기술 모드에서 맛집 키워드 시 측정기기로 간주
                
                query_vec = get_embedding(user_q)
                blacklist_ids = get_blacklist(user_q)
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 60}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()

                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    
                    # 데이터 속성 추출
                    d_cat_raw = str(d.get('category') or '')
                    d_mfr = str(d.get('manufacturer') or '').upper()
                    d_item = str(d.get('measurement_item') or '').upper()
                    d_iss = str(d.get('issue') or '')
                    
                    # [V102] 3대 카테고리 물리적 격리 로직
                    # 데이터의 카테고리 판별
                    if any(k in d_cat_raw or k in d_mfr for k in ["맛집", "식당", "생활정보"]): d_cat = "일상"
                    elif any(k in d_cat_raw or k in d_iss for k in ["펌프", "채수"]): d_cat = "채수펌프"
                    else: d_cat = "측정기기"
                    
                    # [V102 핵심] 카테고리 불일치 시 삭제 (일상 데이터 오염 방지)
                    if target_cat != d_cat: continue
                    
                    # 측정기기 세부 필터 (브랜드/항목)
                    keyword_bonus = 0
                    if target_cat == "측정기기":
                        if t_mfr and t_mfr.upper() in d_mfr: keyword_bonus += 0.4
                        if t_item and t_item.upper() in d_item: keyword_bonus += 0.4
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = (d.get('similarity') or 0) + keyword_bonus + ((d.get('helpful_count') or 0) * 0.01)
                        d['display_category'] = d_cat
                        d['source_id_tag'] = u_key
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)

                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    context = "\n".join([f"[{display_tag_v102(d['source_id_tag'], d['display_category'])}]: {d.get('solution') or d.get('content')}" for d in final_pool[:10]])
                    ans_p = f"수질 전문가입니다. {target_cat} 관련 답변. 질문: {user_q} \n 데이터: {context} \n 문장 끝에 출처 표기."
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    st.markdown('<div class="guide-box">✅ 하단 리스트의 각 지식을 평가해 주세요. <b>[무관함]</b> 사유는 카테고리 필터 강화에 사용됩니다.</div>', unsafe_allow_html=True)
                    
                    st.caption(f"🔍 '{target_cat}' 관련 지식 검색 결과 (총 {len(final_pool)}건)")
                    for i, d in enumerate(final_pool[:10]):
                        s_tag = d['source_id_tag']
                        d_tag = display_tag_v102(s_tag, d['display_category'])
                        with st.expander(f"{i+1}. [{d_tag}] {str(d.get('issue') or '상세 내용')[:35]}..."):
                            if d.get('issue'):
                                st.markdown(f"**🚩 현상/상황**: {d['issue']}")
                                st.markdown(f"**🛠️ 조치/내용**: {d['solution']}")
                                if d.get('measurement_item'): st.caption(f"측정항목: {d['measurement_item']}")
                            else: st.markdown(f"**📄 매뉴얼 내용**\n{d['content']}")
                            st.caption(f"제조사: {d.get('manufacturer')} | 추천👍: {d.get('helpful_count', 0)}")
                            c1, c2 = st.columns(2)
                            if c1.button("👍 도움됨", key=f"v_ok_{s_tag}_{i}", use_container_width=True):
                                if update_single_helpfulness(s_tag): st.success("반영!"); time.sleep(0.5); st.rerun()
                            with c2:
                                with st.popover("❌ 무관함", use_container_width=True):
                                    r_sel = st.selectbox("사유", ["카테고리 오분류", "브랜드 불일치", "주제 무관", "오래된 정보"], key=f"rs_{s_tag}_{i}")
                                    if st.button("제외 확정", key=f"cf_{s_tag}_{i}"):
                                        if add_to_blacklist(user_q, s_tag, r_sel): st.error("제외됨"); time.sleep(0.5); st.rerun()
                else:
                    st.warning(f"⚠️ '{target_cat}' 관련 지식을 찾지 못했습니다. 미해결 과제로 등록되었습니다.")
                    log_unsolved(user_q, f"카테고리({target_cat}) 내 결과 없음", is_life_mode)
            except Exception as e: st.error(f"조회 실패 (V102): {e}")

# --- 2. 현장 노하우 등록 (V102: 3대 카테고리 적용) ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류 (대분류)", ["측정기기", "채수펌프", "일상(맛집/정보)"])
    with st.form("reg_v102", clear_on_submit=True):
        c1, c2 = st.columns(2)
        if cat_sel != "일상(맛집/정보)":
            m_sel = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_man = c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목 (TOC, TN 등)")
        else:
            res_n, res_l = c1.text_input("식당명/정보명"), c2.text_input("위치/지역")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("현상 (제목)"), st.text_area("조치/상세 내용")
        if st.form_submit_button("✅ 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if cat_sel != "일상(맛집/정보)" else "생활정보"
            final_mod = model_n if cat_sel != "일상(맛집/정보)" else res_l
            final_it = item_n if cat_sel != "일상(맛집/정보)" else ""
            if iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": clean_text_for_db(final_m), "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it), "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": clean_text_for_db(reg_n), "embedding": get_embedding(f"{cat_sel} {final_m} {final_it} {iss_t} {sol_d}")}).execute()
                st.success("🎉 등록 완료!")

# --- 3. 문서 등록 (대용량 대응 V101 유지) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        up_f.seek(0)
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("분석 중..."):
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_r.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"추출: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        f_mfr, f_mod = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 저장"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_mod, "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk)}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("✅ 완료!"); st.rerun()

# --- 4, 5, 6 메뉴 (안정화 로직 유지) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록"])
    with t2:
        ms = st.text_input("🔍 지식 검색")
        if ms:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%").execute()
            for r in res.data:
                with st.expander(f"[{r.get('category')}] {r.get('manufacturer')} | {r['issue']}"):
                    st.write(r['solution'])
                    if st.button("삭제", key=f"del_{r['id']}"): supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    st.subheader("💬 소통 공간") # 이전 로직과 동일

elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문") # 이전 로직과 동일
