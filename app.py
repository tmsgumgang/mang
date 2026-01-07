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

# [V77 유지] 자동 깨우기
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

# [논리 고정] 의도 및 기기 정보 정밀 분석
def analyze_query_v79(text):
    tech_keys = ["시마즈", "백년기술", "코비", "케이엔알", "YSI", "TOC", "TN", "TP", "VOC", "점검", "교체", "수리", "HATOX", "HATA", "ROBOCHEM"]
    is_tech = any(k.lower() in text.lower() for k in tech_keys)
    life_keys = ["맛집", "식당", "카페", "추천", "금산", "옥천", "영동", "주차", "메뉴"]
    is_life = any(k in text for k in life_keys)
    m_match = re.search(r'(\d{2,})', text)
    found_mod_num = m_match.group(1) if m_match else None
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    return is_tech, is_life, found_mfr, found_mod_num

# [V79] 미해결 질문 자동 등록 로직
def log_unsolved(query, reason, is_life):
    try:
        # 중복 방지를 위해 최근 동일 질문 확인
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
        ans_list = [f"[{'답글' if a.get('parent_id') else '실전해결'}] {a['author']} (👍{a.get('likes', 0)}): {a['content']}" for a in a_data]
        full_sync_txt = f"현장상황: {q_data['content']}\n조치방법:\n" + "\n".join(ans_list)
        is_tech, is_life, mfr, mod_num = analyze_query_v79(q_data['title'] + q_data['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "맛집/정보" if (is_life and not is_tech) else "게시판답변",
            "manufacturer": mfr if mfr else ("생활정보" if is_life else "커뮤니티"),
            "model_name": q_data['category'], "issue": q_data['title'],
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

# --- 1. 통합 지식 검색 (V79: 필터 및 피드백 기능) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    # [V79] 모드 필터 추가
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("지능형 밸런스 필터링 중..."):
            try:
                is_tech, is_life, target_mfr, target_mod_num = analyze_query_v79(user_q)
                # 라디오 버튼 강제 적용
                is_life = True if "생활정보" in search_mode else False
                
                query_vec = get_embedding(user_q)
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 45}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 30}).execute().data or []
                
                final_pool, seen_fps, seen_ks, top_score = [], set(), set(), 0

                for d in (exp_cands + man_cands):
                    score = d.get('similarity', 0)
                    if score > top_score: top_score = score
                    cat, mfr, mod = d.get('category', '매뉴얼'), d.get('manufacturer', '기타'), d.get('model_name', '일반').upper()
                    
                    if not is_life and cat == "맛집/정보": continue
                    elif is_life and cat != "맛집/정보": continue
                    
                    is_conflict = any(ob in mfr and ob != target_mfr for ob in ["시마즈", "백년기술", "코비", "케이엔알", "YSI"])
                    if target_mfr == mfr or (target_mod_num and target_mod_num in mod) or not is_conflict:
                        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                        f_print = "".join(d.get('solution', d.get('content', '')).split())[:60]
                        if u_key not in seen_ks and f_print not in seen_fps:
                            final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                if final_pool and top_score >= 0.1:
                    context = "\n".join([f"[{d.get('category','매뉴얼')}/{d['manufacturer']}]: {d.get('solution', d.get('content'))}" for d in final_pool[:10]])
                    ans_p = f"수질 전문가 답변. 의도:{'기술' if not is_life else '생활'}. 데이터:{context} \n 질문:{user_q}"
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    # [V79] 피드백 버튼
                    col_f1, col_f2 = st.columns([0.7, 0.3])
                    if col_f2.button("👎 도움이 안 돼요"):
                        log_unsolved(user_q, "사용자 불만족", is_life)
                        st.warning("죄송합니다. 이 질문을 '미해결 과제'로 등록했습니다. 곧 전문가가 답변해 드릴게요!")
                    
                    st.markdown("---")
                    for d in final_pool[:10]:
                        tag_name = "게시판답변" if d.get('qa_id') else ("매뉴얼" if 'content' in d else ("맛집정보" if d.get('category') == "맛집/정보" else "현장경험"))
                        with st.expander(f"[{tag_name}] {d['manufacturer']} | {d['model_name']}"):
                            st.write(d.get('solution', d.get('content')))
                else:
                    st.warning("⚠️ 일치하는 지식을 찾지 못했습니다. 미해결 과제로 등록되었습니다.")
                    log_unsolved(user_q, "검색결과 없음", is_life) # 자동 등록

            except Exception as e: st.error(f"조회 실패: {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("reg_v79", clear_on_submit=True):
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
                st.success("🎉 등록 완료!")

# --- 6. [V79 신규] 미해결 과제 게시판 ---
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 동료의 지식이 필요한 질문들")
    st.caption("AI가 대답하지 못했거나 답변이 부족했던 질문들입니다. 아시는 분은 답변을 남겨주세요!")
    
    unsolved = supabase.table("unsolved_questions").select("*").eq("status", "대기중").order("created_at", desc=True).execute().data
    
    if not unsolved:
        st.success("✨ 모든 문제가 해결되었습니다!")
    else:
        for item in unsolved:
            with st.container():
                st.markdown(f"""
                <div style="background:#fff1f2; padding:15px; border-radius:10px; border-left:5px solid #b91c1c; margin-bottom:10px;">
                    <span class="source-tag tag-unsolved">{'생활' if item['is_lifestyle'] else '기술'}</span>
                    <h4 style="margin:5px 0;">{item['query']}</h4>
                    <p style="font-size:0.8rem; color:#666;">등록 사유: {item['reason']} | 일시: {item['created_at'][:16]}</p>
                </div>
                """, unsafe_allow_html=True)
                
                c1, c2 = st.columns([0.7, 0.3])
                with c1:
                    ans_input = st.text_area("해결법을 아신다면 적어주세요", key=f"ans_{item['id']}", label_visibility="collapsed", placeholder="여기에 조치법을 입력하세요...")
                with c2:
                    if st.button("✅ 지식으로 등록", key=f"btn_{item['id']}", use_container_width=True):
                        if ans_input:
                            # 1. Knowledge Base에 즉시 추가
                            new_vec = get_embedding(f"{'맛집/정보' if item['is_lifestyle'] else '현장꿀팁'} {item['query']} {ans_input}")
                            supabase.table("knowledge_base").insert({
                                "category": '맛집/정보' if item['is_lifestyle'] else '현장꿀팁',
                                "manufacturer": '생활정보' if item['is_lifestyle'] else '미분류',
                                "issue": item['query'], "solution": ans_input,
                                "registered_by": "동료집단지성", "embedding": new_vec
                            }).execute()
                            # 2. 미해결 과제 상태 변경
                            supabase.table("unsolved_questions").update({"status": "해결됨"}).eq("id", item['id']).execute()
                            st.success("멋져요! 이제 챗봇이 이 내용을 학습했습니다."); time.sleep(1); st.rerun()
                st.divider()

# --- 나머지 메뉴 (매뉴얼 등록, 데이터 관리, 질문 게시판)는 이전 버전 로직 유지 ---
# ... (중략) ... 
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    # (V78 코드와 동일)
    st.subheader("📄 매뉴얼 등록")
    # ...
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    # (V78 코드와 동일)
    st.subheader("🛠️ 데이터 관리")
    # ...
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    # (V78 코드와 동일)
    st.subheader("💬 질문 게시판")
    # ...
