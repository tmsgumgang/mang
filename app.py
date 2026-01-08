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

# 한글 태그 변환
def display_tag(u_key):
    if not u_key: return "정보"
    if "EXP_" in u_key: return u_key.replace("EXP_", "경험지식_")
    if "MAN_" in u_key: return u_key.replace("MAN_", "매뉴얼_")
    return u_key

# 의도 및 키워드 분석
def analyze_query_v101(text):
    if not text: return False, False, None, None
    tech_keys = ["시마즈", "백년기술", "코비", "케이엔알", "YSI", "TOC", "TN", "TP", "VOC", "점검", "교체", "수리", "오류", "HATOX", "SSR", "펌프", "밸브", "교정"]
    is_tech = any(k.lower() in text.lower() for k in tech_keys)
    life_keys = ["맛집", "식당", "카페", "추천", "주차", "메뉴", "점심", "저녁"]
    is_life_intent = any(k in text for k in life_keys)
    m_match = re.search(r'(\d{2,})', text)
    found_mod_num = m_match.group(1) if m_match else None
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    return is_tech, is_life_intent, found_mfr, found_mod_num

# 블랙리스트 사유 저장
def add_to_blacklist(query, source_id, reason, comment=""):
    try:
        supabase.table("knowledge_blacklist").insert({"query": query, "source_id": source_id, "reason": reason, "comment": comment}).execute()
        return True
    except: return False

def get_blacklist(query):
    try:
        res = supabase.table("knowledge_blacklist").select("source_id").eq("query", query).execute()
        return [r['source_id'] for r in res.data]
    except: return []

# 도움 점수 업데이트
def update_single_helpfulness(source_id):
    try:
        prefix, row_id = source_id.split("_")
        table = "knowledge_base" if prefix == "EXP" else "manual_base"
        res = supabase.table(table).select("helpful_count").eq("id", int(row_id)).execute()
        if res.data:
            new_count = (res.data[0].get('helpful_count') or 0) + 1
            supabase.table(table).update({"helpful_count": new_count}).eq("id", int(row_id)).execute()
            return True
    except: pass
    return False

def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists:
            supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
    except: pass

def sync_qa_to_knowledge(q_id):
    try:
        q_d = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{a['author']}]: {a['content']}" for a in ans_d]
        full_txt = f"현상: {q_d['content']}\n조치:\n" + "\n".join(ans_list)
        is_t, is_l, mfr, mod = analyze_query_v101(q_d['title'] + q_d['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "게시판답변", "manufacturer": mfr or "커뮤니티",
            "model_name": q_d.get('category', '일반'), "issue": q_d['title'], "solution": full_txt,
            "registered_by": q_d['author'], "embedding": get_embedding(f"{mfr} {q_d['title']} {full_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .guide-box { background-color: #f0fdf4; border: 1px solid #bbf7d0; padding: 12px; border-radius: 8px; font-size: 0.85rem; margin-bottom: 15px; color: #166534; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("전문 지식 탐색 중..."):
            try:
                is_tech_q, is_life_q, target_mfr, target_mod_num = analyze_query_v101(user_q)
                is_life = True if "생활정보" in search_mode else False
                query_vec = get_embedding(user_q)
                blacklist_ids = get_blacklist(user_q)
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 50}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 30}).execute().data or []
                final_pool, seen_fps, seen_ks = [], set(), set()
                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    cat, mfr, mod, iss = str(d.get('category') or '현장경험'), str(d.get('manufacturer') or '현장장비'), str(d.get('model_name') or '일반').upper(), str(d.get('issue') or '')
                    if not is_life and cat == "맛집/정보": continue
                    elif is_life and cat != "맛집/정보": continue
                    keyword_hit = target_mfr and (target_mfr in mfr or target_mfr in iss)
                    model_hit = target_mod_num and target_mod_num in mod
                    is_conflict = target_mfr and any(comp in mfr and comp != target_mfr for comp in ["시마즈", "백년기술", "코비", "케이엔알", "YSI"])
                    is_generic = any(gen in mfr for gen in ["현장장비", "미분류", "기타", "커뮤니티", "생활정보"])
                    if keyword_hit or model_hit or is_generic or not is_conflict:
                        raw_c = d.get('solution') or d.get('content') or ""
                        f_print = "".join(raw_c.split())[:60]
                        if u_key not in seen_ks and f_print not in seen_fps:
                            bonus = 0.5 if keyword_hit else 0
                            d['final_score'] = (d.get('similarity') or 0) + bonus + ((d.get('helpful_count') or 0) * 0.01)
                            d['source_id_tag'] = u_key
                            final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)
                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                if final_pool:
                    context = "\n".join([f"[{display_tag(d['source_id_tag'])}]: {d.get('solution') or d.get('content')}" for d in final_pool[:12]])
                    ans_p = f"수질 전문가 답변. 질문: {user_q} \n 데이터: {context} \n 요약 후 문장 끝에 [{display_tag('출처')}] 표기."
                    st.subheader("🤖 AI 정밀 요약")
                    st.info(ai_model.generate_content(ans_p).text)
                    st.markdown('<div class="guide-box">✅ 하단 리스트에서 지식을 평가해 주세요. <b>[무관함]</b> 사유는 향후 로직 개선에 활용됩니다.</div>', unsafe_allow_html=True)
                    for d in final_pool[:10]:
                        s_tag, d_tag = d['source_id_tag'], display_tag(d['source_id_tag'])
                        with st.expander(f"[{d_tag}] [상황] {str(d.get('issue') or '상세 지식')[:35]}..."):
                            if d.get('issue'):
                                st.markdown(f"**🚩 현상/상황**: {d['issue']}")
                                st.markdown(f"**🛠️ 조치/내용**: {d['solution']}")
                            else: st.markdown(f"**📄 매뉴얼 내용**\n{d['content']}")
                            st.caption(f"제조사: {d.get('manufacturer')} | 추천👍: {d.get('helpful_count', 0)}")
                            c1, c2 = st.columns(2)
                            if c1.button("👍 도움됨", key=f"v_ok_{s_tag}", use_container_width=True):
                                if update_single_helpfulness(s_tag): st.success("추천 반영!"); time.sleep(0.5); st.rerun()
                            with c2:
                                with st.popover("❌ 무관함", use_container_width=True):
                                    r_sel = st.selectbox("사유", ["브랜드 불일치", "주제 무관", "오래된 정보", "기타"], key=f"rs_{s_tag}")
                                    c_in = st.text_input("의견", key=f"cm_{s_tag}")
                                    if st.button("제외 확정", key=f"cf_{s_tag}"):
                                        if add_to_blacklist(user_q, s_tag, r_sel, c_in): st.error("제외됨"); time.sleep(0.5); st.rerun()
                else:
                    st.warning("⚠️ 일치하는 지식을 찾지 못했습니다. 미해결 과제로 등록되었습니다.")
                    log_unsolved(user_q, "검색결과 없음", is_life)
            except Exception as e: st.error(f"조회 실패 (V101): {e}")

# --- 3. 문서(매뉴얼) 등록 (V101: 대용량 처리 안정화) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드 (최대 200MB)", type=["pdf"])
    if up_f:
        # [V101] 파일 읽기 위치 초기화
        up_f.seek(0)
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("정보 분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_reader.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"추출: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        
        c1, c2 = st.columns(2)
        f_mfr = st.text_input("🏢 제조사", value=st.session_state.s_m)
        f_model = st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        
        if st.button("🚀 저장"):
            # [V101 핵심] 저장 시 파일 포인터 다시 초기화
            up_f.seek(0)
            status_area = st.empty()
            progress_bar = st.progress(0)
            
            try:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                total_pages = len(pdf_reader.pages)
                all_t = ""
                
                # 1. 텍스트 추출 단계
                for i, page in enumerate(pdf_reader.pages):
                    txt = page.extract_text()
                    if txt: all_t += txt + "\n"
                    progress_bar.progress(int((i + 1) / total_pages * 50)) # 50%까지 추출 진행도
                    status_area.write(f"📄 텍스트 추출 중... ({i+1}/{total_pages} 페이지)")
                
                # 2. 임베딩 및 저장 단계
                chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
                total_chunks = len(chunks)
                for i, chunk in enumerate(chunks):
                    supabase.table("manual_base").insert({
                        "manufacturer": f_mfr, "model_name": f_model, 
                        "content": clean_text_for_db(chunk), "file_name": up_f.name, 
                        "page_num": (i//2)+1, "embedding": get_embedding(chunk)
                    }).execute()
                    progress_bar.progress(50 + int((i + 1) / total_chunks * 50)) # 100%까지 저장 진행도
                    status_area.write(f"⚙️ 지식 학습 중... ({i+1}/{total_chunks} 조각)")
                
                st.success(f"✅ '{up_f.name}' 학습이 성공적으로 완료되었습니다!"); time.sleep(1); st.rerun()
            except Exception as e:
                st.error(f"❌ 저장 중 오류 발생: {e}")

# --- 2, 4, 5, 6 메뉴 (V100 유지) ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("reg_v101", clear_on_submit=True):
        if cat_sel != "맛집/정보":
            c1, c2 = st.columns(2)
            m_sel, m_man = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"]), c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목")
        else:
            c1, c2 = st.columns(2)
            res_n, res_l, res_m = c1.text_input("식당명"), c2.text_input("위치"), st.text_input("대표메뉴")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("현상 (제목)"), st.text_area("조치 내용")
        if st.form_submit_button("✅ 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if cat_sel != "맛집/정보" else res_n
            final_mod, final_it = (model_n, item_n) if cat_sel != "맛집/정보" else (res_l, res_m)
            if final_m and iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": clean_text_for_db(final_m), "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it), "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": clean_text_for_db(reg_n), "embedding": get_embedding(f"{cat_sel} {final_m} {final_mod} {iss_t} {sol_d}")}).execute()
                st.success("🎉 지식 등록 완료!")

elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록"])
    with t3:
        st.subheader("📂 매뉴얼 관리")
        ds = st.text_input("🔍 파일명 검색")
        res_m = supabase.table("manual_base").select("*").or_(f"file_name.ilike.%{ds}%").order("created_at", desc=True).limit(50).execute() if ds else supabase.table("manual_base").select("*").order("created_at", desc=True).limit(50).execute()
        if res_m.data:
            unique_f = list(set([r['file_name'] for r in res_m.data if r.get('file_name')]))
            for f in unique_f:
                with st.expander(f"📄 {f}"):
                    if st.button("🗑️ 파일 전체 삭제", key=f"df_{f}"): supabase.table("manual_base").delete().eq("file_name", f).execute(); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q_d = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q_d['title']}"); st.info(q_d['content'])
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_d['id']).order("created_at").execute().data
        for a in ans_d: st.markdown(f'<div style="background:#f8fafc; padding:12px; border-radius:8px; margin-bottom:5px;"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
        with st.form("ans_v101"):
            at, ct = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q_d['id'], "author": at, "content": clean_text_for_db(ct)}).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기"):
            with st.form("q_v101"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id']); st.rerun()
        for q_r in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q_r['category']}] {q_r['title']}**")
            if c2.button("보기", key=f"q_{q_r['id']}"): st.session_state.selected_q_id = q_r['id']; st.rerun()

elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 동료의 지식이 필요한 질문")
    unsolved = supabase.table("unsolved_questions").select("*").eq("status", "대기중").order("created_at", desc=True).execute().data
    if not unsolved: st.success("✨ 해결할 과제가 없습니다!")
    else:
        for item in unsolved:
            with st.container():
                st.markdown(f"<div style='background:#fff1f2; padding:15px; border-radius:10px; border-left:5px solid #b91c1c; margin-bottom:10px;'><b>{item['query']}</b><br><small>사유: {item['reason']}</small></div>", unsafe_allow_html=True)
                with st.form(key=f"form_sos_{item['id']}"):
                    ans_in = st.text_area("조치법 입력")
                    if not item['is_lifestyle']:
                        c1, c2, c3 = st.columns(3)
                        s_mfr, s_mod, s_itm = c1.text_input("제조사", key=f"mfr_{item['id']}"), c2.text_input("모델명", key=f"mod_{item['id']}"), c3.text_input("측정항목", key=f"itm_{item['id']}")
                    if st.form_submit_button("✅ 등록"):
                        if ans_in:
                            f_m = s_mfr if not item['is_lifestyle'] and s_mfr else ('생활정보' if item['is_lifestyle'] else '현장장비')
                            f_mo = s_mod if not item['is_lifestyle'] and s_mod else '일반'
                            f_it = s_itm if not item['is_lifestyle'] and s_itm else '일반'
                            n_v = get_embedding(f"{f_m} {f_mo} {item['query']} {ans_in}")
                            supabase.table("knowledge_base").insert({"category": '현장꿀팁', "manufacturer": f_m, "model_name": f_mo, "measurement_item": f_it, "issue": item['query'], "solution": ans_in, "registered_by": "동료지성", "embedding": n_v}).execute()
                            supabase.table("unsolved_questions").update({"status": "해결됨"}).eq("id", item['id']).execute(); st.rerun()
