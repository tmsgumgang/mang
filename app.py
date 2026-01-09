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

def v118_route_intent(query):
    try:
        prompt = f"질문의 도메인을 [기술자산, 행정절차, 복지생활] 중 하나로 결정해. 질문: {query}\nJSON: {{\"domain\": \"도메인\"}}"
        res = ai_model.generate_content(prompt)
        return extract_json(res.text).get('domain', '기술자산')
    except: return "기술자산"

def v118_classify_data(content):
    try:
        prompt = f"데이터 분류. 도메인:[기술자산, 행정절차, 복지생활], 세부분류, 측정항목. 내용: {content}\nJSON: {{\"domain\": \"도메인\", \"sub_category\": \"분류\", \"item\": \"항목\"}}"
        res = ai_model.generate_content(prompt)
        return extract_json(res.text)
    except: return None

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
keep_db_alive()
if 'page_mode' not in st.session_state: st.session_state.page_mode = "🔍 통합 지식 검색"

st.markdown("""
    <style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; box-shadow: 0 4px 10px rgba(0,0,0,0.2); }
    .header-title { font-size: 1.1rem; font-weight: 800; }
    .main .block-container { padding-top: 4.5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.15); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 12px; display: grid; grid-template-columns: repeat(auto-fit, minmax(120px, 1fr)); gap: 10px; }
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇 V118</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)", "🆘 미해결 과제"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    search_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("질문 입력", label_visibility="collapsed", placeholder="장비 문제나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    
    if user_q and (search_clicked or user_q):
        with st.spinner("의도를 분석하고 지식을 격리 중..."):
            try:
                target_domain = "복지생활" if "생활정보" in search_mode else v118_route_intent(user_q)
                query_vec = get_embedding(user_q)
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 60}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.01, "match_count": 40}).execute().data or []
                
                final_pool, seen_fps, seen_ks = [], set(), set()
                for d in (exp_cands + man_cands):
                    u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    # [V118] 도메인 매칭 및 검토 대기 데이터 제외
                    if d.get('domain') != target_domain or d.get('review_required'): continue 
                    
                    raw_c = d.get('solution') or d.get('content') or ""
                    f_print = "".join(raw_c.split())[:60]
                    if u_key not in seen_ks and f_print not in seen_fps:
                        d['final_score'] = d.get('similarity') or 0
                        final_pool.append(d); seen_ks.add(u_key); seen_fps.add(f_print)

                final_pool = sorted(final_pool, key=lambda x: x['final_score'], reverse=True)
                if final_pool:
                    st.subheader("🤖 AI 정밀 요약")
                    st.info(ai_model.generate_content(f"질문: {user_q} 데이터: {final_pool[:12]}").text)
                    for i, d in enumerate(final_pool[:10]):
                        with st.expander(f"{i+1}. [{d.get('domain')}] {str(d.get('issue') or '상세내용')[:35]}..."):
                            st.write(d.get('solution') or d.get('content'))
                else: st.warning("지식을 찾지 못했습니다.")
            except Exception as e: st.error(f"조회 실패: {e}")

# --- 4. 데이터 전체 관리 (V118: 수동 분류 대기실 추가) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    t1, t2, t3, t4, t5, t6 = st.tabs(["📊 로그 분석", "📝 경험 리파이너", "📄 매뉴얼 리파이너", "🚫 교정 기록", "🧹 시맨틱 최신화", "🚨 수동 분류 대기실"])
    
    with t5:
        st.subheader("🧹 데이터베이스 시맨틱 최신화")
        target_table = st.radio("대상", ["경험 지식", "매뉴얼 지식"], horizontal=True, key="migrate_target")
        table_name = "knowledge_base" if target_table == "경험 지식" else "manual_base"
        unlabeled = supabase.table(table_name).select("id", count="exact").eq("semantic_version", 0).execute()
        st.metric("최신화 대기 데이터", f"{unlabeled.count or 0} 건")
        
        if st.button("🚀 최신화 시작 (20건)"):
            rows = supabase.table(table_name).select("*").eq("semantic_version", 0).limit(20).execute().data
            if rows:
                with st.status("🏗️ 분석 중...", expanded=True) as status:
                    for r in rows:
                        try: # [V118 핵심] 개별 행 에러 가드
                            content = r.get('solution') or r.get('content') or ""
                            result = v118_classify_data(content[:2500])
                            if result:
                                supabase.table(table_name).update({
                                    "domain": result.get('domain'), "sub_category": result.get('sub_category'),
                                    "measurement_item": result.get('item'), "semantic_version": 1, "review_required": False
                                }).eq("id", r['id']).execute()
                                st.write(f"✅ ID {r['id']}: [{result.get('domain')}] 완료")
                            else:
                                # 분석 실패 시 격리소로 전송
                                supabase.table(table_name).update({"semantic_version": 1, "review_required": True}).eq("id", r['id']).execute()
                                st.write(f"🚨 ID {r['id']}: 분석 실패 (격리소 이동)")
                        except:
                            # DB 에러 시 격리소로 전송
                            supabase.table(table_name).update({"semantic_version": 1, "review_required": True}).eq("id", r['id']).execute()
                            st.write(f"⚠️ ID {r['id']}: 통신 오류 (격리소 이동)")
                    status.update(label="처리 완료!", state="complete")
                st.rerun()

    with t6:
        st.subheader("🚨 수동 분류 대기실")
        st.write("AI가 판단을 보류했거나 오류가 발생한 데이터입니다. 직접 명찰을 달아주세요.")
        t_sel = st.radio("테이블", ["경험", "매뉴얼"], horizontal=True, key="review_target")
        t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
        
        review_list = supabase.table(t_name).select("*").eq("review_required", True).limit(10).execute().data
        if not review_list: st.success("🎉 검토할 데이터가 없습니다!")
        else:
            for item in review_list:
                with st.container():
                    st.markdown(f"**[데이터 원문]**\n{item.get('issue') or ''}\n{item.get('solution') or item.get('content', '')[:500]}...")
                    with st.form(key=f"manual_{t_name}_{item['id']}"):
                        c1, c2, c3 = st.columns(3)
                        m_dom = c1.selectbox("도메인", ["기술자산", "행정절차", "복지생활"])
                        m_sub = c2.text_input("세부분류", placeholder="예: 측정기기")
                        m_item = c3.text_input("측정항목", value=item.get('measurement_item', '공통'))
                        if st.form_submit_button("✅ 분류 확정"):
                            supabase.table(t_name).update({
                                "domain": m_dom, "sub_category": m_sub, 
                                "measurement_item": m_item, "review_required": False
                            }).eq("id", item['id']).execute()
                            st.success("데이터가 정상 지식으로 승격되었습니다!"); st.rerun()
                st.divider()

# --- 2, 3, 5, 6 메뉴 (안정화 유지) ---
elif st.session_state.page_mode == "📝 지식 등록":
    st.subheader("📝 신규 지식 등록")
    with st.form("reg_v118", clear_on_submit=True):
        f_dom = st.selectbox("도메인", ["기술자산", "행정절차", "복지생활"])
        f_mfr, f_iss, f_sol = st.text_input("제조사"), st.text_input("제목"), st.text_area("내용")
        if st.form_submit_button("저장"):
            supabase.table("knowledge_base").insert({"domain": f_dom, "manufacturer": f_mfr, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f"{f_dom} {f_mfr} {f_iss}"), "semantic_version": 1}).execute()
            st.success("완료!")

elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        f_dom = st.selectbox("도메인", ["기술자산", "행정절차", "복지생활"])
        if st.button("🚀 학습 시작"):
            up_f.seek(0)
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
            p_bar = st.progress(0)
            for i, chunk in enumerate(chunks):
                supabase.table("manual_base").insert({"domain": f_dom, "content": clean_text_for_db(chunk), "file_name": up_f.name, "embedding": get_embedding(chunk), "semantic_version": 1}).execute()
                p_bar.progress((i+1)/len(chunks))
            st.success("완료!"); st.rerun()

elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    st.subheader("💬 소통 공간") # 기본 로직 유지
elif st.session_state.page_mode == "🆘 미해결 과제":
    st.subheader("🆘 해결이 필요한 질문") # 기본 로직 유지
