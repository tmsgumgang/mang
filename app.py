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

# [V112] 지능형 도메인 판별 로직
def analyze_domain_v112(text):
    if not text: return "기술자산"
    # 도메인 키워드 정의
    tech_keys = ["점검", "교체", "수리", "오류", "에러코드", "TOC", "TN", "TP", "VOC", "PH", "펌프", "시약", "조제"]
    admin_keys = ["일지", "양식", "보고서", "신청", "절차", "안전", "규칙", "공문"]
    life_keys = ["맛집", "식당", "카페", "주차", "점심", "저녁", "회식", "메뉴", "짜글이"]
    
    if any(k in text for k in life_keys): return "복지생활"
    if any(k in text for k in admin_keys): return "행정절차"
    return "기술자산"

# [V112] 마이그레이션 전용 에이전트
def ai_classify_data(content):
    prompt = f"""아래 데이터를 [도메인 / 세부분류 / 측정항목]으로 분류해서 JSON으로만 대답해.
    도메인: [기술자산, 행정절차, 복지생활] 중 하나
    데이터: {content}
    응답예시: {{"domain": "기술자산", "sub_category": "측정기기", "item": "TOC"}}"""
    res = ai_model.generate_content(prompt)
    return extract_json(res.text)

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
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V112</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V112: 도메인 격리 엔진) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 도메인", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("질문 입력", label_visibility="collapsed", placeholder="장비 문제나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("도메인을 판별하고 지식을 격리 중입니다..."):
            try:
                # 1. 도메인 확정
                target_domain = "복지생활" if "생활정보" in search_mode else analyze_domain_v112(user_q)
                
                query_vec = get_embedding(user_q)
                blacklist_ids = [r['source_id'] for r in supabase.table("knowledge_blacklist").select("source_id").eq("query", user_q).execute().data]
                
                # 2. 하이브리드 매칭
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 60}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()
                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    if u_key in blacklist_ids: continue
                    
                    # [V112 핵심] 도메인 격리 로직 (미분류 데이터는 통과)
                    d_domain = d.get('domain') or analyze_domain_v112(str(d.get('issue') or d.get('content')))
                    if target_domain != d_domain: continue 

                    # 가중치 계산
                    bonus = 0.5 if any(brand in str(d.get('manufacturer') or '').lower() for brand in ["시마즈", "백년기술", "코비"]) else 0
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = (d.get('similarity') or 0) + bonus
                        d['source_id_tag'], d['final_dom'] = u_key, d_domain
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    context = "\n".join([f"[{d['source_id_tag']}]: {d.get('solution') or d.get('content')}" for d in final_pool[:12]])
                    ans_p = f"수질 전문가입니다. 도메인: {target_domain}. 질문: {user_q} \n 데이터: {context} \n 요약 후 출처 표기."
                    st.info(ai_model.generate_content(ans_p).text)
                    
                    for i, d in enumerate(final_pool[:10]):
                        with st.expander(f"{i+1}. [{d['final_dom']}] {str(d.get('issue') or '상세 지식')[:35]}..."):
                            st.markdown(f"""<div class="meta-bar">
                                <div>🏢 제조사: <b>{d.get('manufacturer', '미지정')}</b></div>
                                <div>🏷️ 모델: <b>{d.get('model_name', '미지정')}</b></div>
                                <div>🧪 분류: <b>{d.get('sub_category', '일반')}</b></div>
                            </div>""", unsafe_allow_html=True)
                            st.write(d.get('solution') or d.get('content'))
                            if st.button(f"🚫 도메인 오분류 신고", key=f"irr_{d['source_id_tag']}"):
                                supabase.table("knowledge_blacklist").insert({"query": user_q, "source_id": d['source_id_tag'], "reason": "도메인 불일치"}).execute()
                                st.error("해당 정보는 현재 도메인에서 제외되었습니다."); time.sleep(0.5); st.rerun()
                else:
                    st.warning(f"⚠️ {target_domain} 도메인에서 일치하는 지식을 찾지 못했습니다.")
            except Exception as e: st.error(f"조회 실패 (V112): {e}")

# --- 4. 데이터 전체 관리 (V112: 데이터 대청소 탭 추가) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4, t5 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록", "🧹 데이터 대청소"])
    
    with t5:
        st.subheader("🧹 기존 데이터 지능형 분류 (마이그레이션)")
        st.info("기존에 등록된 무분별한 데이터들을 [기술/행정/복지] 체계로 자동 분류합니다.")
        
        target_table = st.radio("대상 테이블", ["경험 지식", "매뉴얼 지식"], horizontal=True)
        table_name = "knowledge_base" if target_table == "경험 지식" else "manual_base"
        
        # 분류되지 않은 데이터 개수 확인
        unlabeled = supabase.table(table_name).select("id", count="exact").is_("domain", "null").execute()
        st.metric("분류가 필요한 데이터", f"{unlabeled.count or 0} 건")
        
        if st.button("🚀 AI 자동 분류 시작"):
            rows = supabase.table(table_name).select("*").is_("domain", "null").limit(20).execute().data
            if not rows:
                st.success("🎉 모든 데이터가 분류되어 있습니다!")
            else:
                with st.status("🏗️ 데이터 재정비 중...", expanded=True) as status:
                    for r in rows:
                        content = r.get('solution') or r.get('content') or ""
                        result = ai_classify_data(content[:2000])
                        if result:
                            supabase.table(table_name).update({
                                "domain": result.get('domain'),
                                "sub_category": result.get('sub_category'),
                                "measurement_item": result.get('item', r.get('measurement_item'))
                            }).eq("id", r['id']).execute()
                            st.write(f"✅ ID {r['id']}: [{result.get('domain')}] 분류 완료")
                    status.update(label="재정비 완료!", state="complete")
                st.rerun()

# --- 2, 3, 5, 6 메뉴 (로직 유지 및 도메인 필드 추가) ---
elif st.session_state.page_mode == "📝 지식 등록":
    st.subheader("📝 신규 지식 등록")
    with st.form("reg_v112", clear_on_submit=True):
        f_dom = st.selectbox("도메인", ["기술자산", "행정절차", "복지생활"])
        f_mfr, f_iss, f_sol = st.text_input("제조사/상호"), st.text_input("상황/제목"), st.text_area("내용/조치")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "manufacturer": f_mfr, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f"{f_dom} {f_mfr} {f_iss} {f_sol}")}).execute()
            st.success("등록 완료!")

elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        f_dom = st.selectbox("문서 도메인", ["기술자산", "행정절차", "복지생활"])
        if st.button("🚀 지식 학습 시작"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"domain": f_dom, "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk)}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("완료!"); st.rerun()
