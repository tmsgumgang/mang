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

# [V85] 의도 및 기기 정보 정밀 분석
def analyze_query_v85(text):
    if not text: return False, False, None, None
    tech_keys = ["시마즈", "백년기술", "코비", "케이엔알", "YSI", "TOC", "TN", "TP", "VOC", "점검", "교체", "수리", "HATOX", "HATA", "ROBOCHEM", "SSR", "펌프"]
    is_tech = any(k.lower() in text.lower() for k in tech_keys)
    life_keys = ["맛집", "식당", "카페", "추천", "금산", "옥천", "영동", "주차", "메뉴"]
    is_life_intent = any(k in text for k in life_keys)
    m_match = re.search(r'(\d{2,})', text)
    found_mod_num = m_match.group(1) if m_match else None
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    return is_tech, is_life_intent, found_mfr, found_mod_num

# 도움 점수 업데이트
def update_helpfulness(item_list):
    try:
        for item in item_list:
            table = "knowledge_base" if "solution" in item else "manual_base"
            current_count = item.get('helpful_count', 0) or 0
            supabase.table(table).update({"helpful_count": current_count + 1}).eq("id", item['id']).execute()
        return True
    except: return False

# 미해결 질문 자동 등록
def log_unsolved(query, reason, is_life):
    try:
        exists = supabase.table("unsolved_questions").select("id").eq("query", query).eq("status", "대기중").execute().data
        if not exists:
            supabase.table("unsolved_questions").insert({"query": query, "reason": reason, "is_lifestyle": is_life}).execute()
            return True
    except: pass
    return False

# 게시판 지식 동기화
def sync_qa_to_knowledge(q_id):
    try:
        q_data = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        a_data = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '실전해결'}] {a['author']} (👍{a.get('likes', 0) or 0}): {a['content']}" for a in a_data]
        full_sync_txt = f"현장상황: {q_data['content']}\n조치방법:\n" + "\n".join(ans_list)
        is_tech, is_life, mfr, mod_num = analyze_query_v85(q_data['title'] + q_data['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "맛집/정보" if (is_life and not is_tech) else "게시판답변",
            "manufacturer": mfr if mfr else ("생활정보" if is_life else "커뮤니티"),
            "model_name": q_data.get('category', '일반') or '일반', "issue": q_data['title'],
            "solution": full_sync_txt, "registered_by": q_data['author'],
            "embedding": get_embedding(f"{mfr} {q_data['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    header[data-testid="stHeader"] { display: none !important; }
    .fixed-header {
        position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white;
        padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2);
    }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.8rem !important; }
    .source-tag { font-size: 0.7rem; padding: 2px 8px; border-radius: 6px; font-weight: 700; margin-bottom: 5px; display: inline-block; }
    .tag-exp { background-color: #e0f2fe; color: #0369a1; }
    .tag-man { background-color: #fef3c7; color: #92400e; }
    .tag-qa { background-color: #f5f3ff; color: #5b21b6; }
    .tag-info { background-color: #f0fdf4; color: #166534; }
    .tag-unsolved { background-color: #fee2e2; color: #b91c1c; border: 1px solid #f87171; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V85: 하이브리드 가중치 및 필터 적용) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("최적의 지식 선별 중..."):
            try:
                is_tech, is_life_intent, target_mfr, target_mod_num = analyze_query_v85(user_q)
                is_life = True if "생활정보" in search_mode else False
                query_vec = get_embedding(user_q)
                
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.03, "match_count": 45}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.03, "match_count": 30}).execute().data or []
                
                final_pool, seen_fps, seen_ks, top_score = [], set(), set(), 0

                for d in (exp_cands + man_cands):
                    score = d.get('similarity', 0) or 0
                    if score > top_score: top_score = score
                    cat = d.get('category') or '매뉴얼'
                    mfr = d.get('manufacturer') or '기타'
                    mod = str(d.get('model_name') or '일반').upper()
                    
                    if not is_life and cat == "맛집/정보": continue
                    elif is_life and cat != "맛집/정보": continue
                    
                    is_conflict = any(ob in mfr and ob != target_mfr for ob in ["시마즈", "백년기술", "코비", "케이엔알", "YSI"])
                    if target_mfr == mfr or (target_mod_num and target_mod_num in mod) or not is_conflict:
                        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                        content_raw = d.get('solution') or d.get('content') or ""
                        f_print = "".join(content_raw.split())[:60]
                        if u_key not in seen_ks and f_print not in seen_fps:
                            d['final_score'] = score + ((d.get('helpful_count') or 0) * 0.01)
                            final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)

                if final_pool and top_score >= 0.03:
                    context = "\n".join([f"[{d.get('category') or '매뉴얼'}/{d.get('manufacturer') or '기타'}](도움👍:{d.get('helpful_count') or 0}): {d.get('solution') or d.get('content')}" for d in final_pool[:10]])
                    ans_p = f"""금강수계 수질 전문가입니다.
                    [지침] 하단 데이터에 연관된 내용이 하나라도 있다면 절대 "정보가 없다"고 하지 마세요. 
                    핵심 조치법을 요약하여 답변하세요. 질문: {user_q} \n 데이터: {context}"""
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    c_f1, c_f2, c_f3 = st.columns([0.4, 0.3, 0.3])
                    c_f1.caption("답변이 도움이 되셨나요?")
                    if c_f2.button("👍 도움이 돼요!", use_container_width=True):
                        if update_helpfulness(final_pool[:3]): st.success("반영되었습니다!"); time.sleep(0.5); st.rerun()
                    if c_f3.button("👎 도움이 안 돼요", use_container_width=True):
                        log_unsolved(user_q, "사용자 불만족", is_life)
                        st.warning("미해결 과제로 등록되었습니다."); time.sleep(0.5); st.rerun()
                    
                    st.markdown("---")
                    for d in final_pool[:10]:
                        t_name = "게시판답변" if d.get('qa_id') else ("매뉴얼" if 'content' in d else ("맛집정보" if d.get('category') == "맛집/정보" else "현장경험"))
                        with st.expander(f"[{t_name}] {d.get('manufacturer') or '기타'} | {d.get('model_name') or '일반'} (👍{d.get('helpful_count') or 0})"):
                            st.write(d.get('solution') or d.get('content'))
                else:
                    st.warning("⚠️ 일치하는 지식을 찾지 못했습니다. 미해결 과제로 등록되었습니다.")
                    log_unsolved(user_q, "검색결과 없음", is_life)
            except Exception as e: st.error(f"조회 실패: {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("reg_v85", clear_on_submit=True):
        if cat_sel != "맛집/정보":
            c1, c2 = st.columns(2)
            m_sel = c1.selectbox("제조사", ["시마즈", "코비", "백년기술", "케이엔알", "YSI", "직접 입력"])
            m_man = c1.text_input("└ 직접 입력")
            model_n, item_n = c2.text_input("모델명"), c2.text_input("측정항목")
        else:
            c1, c2 = st.columns(2)
            res_n, res_l, res_m = c1.text_input("식당명"), c2.text_input("위치"), st.text_input("대표메뉴")
        reg_n, iss_t, sol_d = st.text_input("등록자"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("✅ 저장"):
            final_m = (m_man if m_sel == "직접 입력" else m_sel) if cat_sel != "맛집/정보" else res_n
            final_mod, final_it = (model_n, item_n) if cat_sel != "맛집/정보" else (res_l, res_m)
            if final_m and iss_t and sol_d:
                supabase.table("knowledge_base").insert({"category": cat_sel, "manufacturer": clean_text_for_db(final_m), "model_name": clean_text_for_db(final_mod), "measurement_item": clean_text_for_db(final_it), "issue": clean_text_for_db(iss_t), "solution": clean_text_for_db(sol_d), "registered_by": clean_text_for_db(reg_n), "embedding": get_embedding(f"{cat_sel} {final_m} {final_mod} {iss_t} {sol_d}")}).execute()
                st.success("🎉 지식 등록 완료!")

# --- 6. 미해결 과제 (V85: 답변 시 기기 정보 상세 입력 폼 탑재) ---
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 동료의 지식이 필요한 질문들")
    unsolved = supabase.table("unsolved_questions").select("*").eq("status", "대기중").order("created_at", desc=True).execute().data
    if not unsolved: st.success("✨ 해결할 과제가 없습니다!")
    else:
        for item in unsolved:
            with st.container():
                st.markdown(f"<div style='background:#fff1f2; padding:15px; border-radius:10px; border-left:5px solid #b91c1c; margin-bottom:10px;'><b>{item['query']}</b><br><small>사유: {item['reason']}</small></div>", unsafe_allow_html=True)
                with st.form(key=f"form_sos_{item['id']}"):
                    ans_in = st.text_area("해결법 입력", placeholder="여기에 조치 노하우를 상세히 입력하세요...")
                    if not item['is_lifestyle']: # 기술 질문일 때만 상세 폼 노출
                        st.caption("🛠️ 기기 정보 (정확히 적을수록 검색이 잘 됩니다)")
                        c1, c2, c3 = st.columns(3)
                        sos_mfr = c1.text_input("제조사", placeholder="예: 시마즈", key=f"mfr_{item['id']}")
                        sos_mod = c2.text_input("모델명", placeholder="예: TOC-4200", key=f"mod_{item['id']}")
                        sos_itm = c3.text_input("측정항목", placeholder="예: TOC", key=f"itm_{item['id']}")
                    
                    cc1, cc2 = st.columns([0.8, 0.2])
                    if cc1.form_submit_button("✅ 지식으로 등록"):
                        if ans_in:
                            final_m = sos_mfr if not item['is_lifestyle'] and sos_mfr else ('생활정보' if item['is_lifestyle'] else '현장장비')
                            final_mo = sos_mod if not item['is_lifestyle'] and sos_mod else '일반'
                            final_it = sos_itm if not item['is_lifestyle'] and sos_itm else '일반'
                            
                            new_vec = get_embedding(f"{final_m} {final_mo} {item['query']} {ans_in}")
                            supabase.table("knowledge_base").insert({
                                "category": '맛집/정보' if item['is_lifestyle'] else '현장꿀팁',
                                "manufacturer": final_m, "model_name": final_mo, "measurement_item": final_it,
                                "issue": item['query'], "solution": ans_in,
                                "registered_by": "동료지성", "embedding": new_vec
                            }).execute()
                            supabase.table("unsolved_questions").update({"status": "해결됨"}).eq("id", item['id']).execute()
                            st.success("등록 완료!"); time.sleep(0.5); st.rerun()
                    if cc2.form_submit_button("🗑️ 삭제"):
                        supabase.table("unsolved_questions").delete().eq("id", item['id']).execute(); st.rerun()
                st.divider()

# --- 3, 4, 5 메뉴 유지 (V84와 동일) ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
        all_t = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
        chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
        if st.button("학습 시작"):
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk)}).execute()
            st.success("완료!"); st.rerun()

elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    st.subheader("🛠️ 지식 데이터 관리")
    t1, t2 = st.tabs(["📝 경험 관리", "📄 매뉴얼 관리"])
    with t1:
        ms = st.text_input("🔍 검색")
        if ms:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%").execute()
            for r in res.data:
                with st.expander(f"[{r.get('manufacturer')}] {r['issue']}"):
                    st.write(r['solution'])
                    if st.button("삭제", key=f"del_k_{r['id']}"):
                        supabase.table("knowledge_base").delete().eq("id", r['id']).execute(); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    st.subheader("💬 소통 공간")
    # (이전 버전 Q&A 로직 유지)
