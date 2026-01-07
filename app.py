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

# [논리 고정] 의도 및 기기 정보 정밀 추출
def analyze_query_v75(text):
    life_keys = ["맛집", "식당", "카페", "추천", "금산", "옥천", "영동", "청주", "대전", "주차", "점심", "회식"]
    is_life = any(k in text for k in life_keys)
    mfr_map = {"시마즈": "시마즈", "백년기술": "백년기술", "코비": "코비", "케이엔알": "케이엔알", "YSI": "YSI", "robochem": "백년기술", "hatox": "코비", "hata": "코비", "hatn": "코비"}
    found_mfr = next((v for k, v in mfr_map.items() if k.lower() in text.lower()), None)
    model_match = re.search(r'(\d{2,})', text)
    found_mod_num = model_match.group(1) if model_match else None
    return is_life, found_mfr, found_mod_num

# 게시판 지식 동기화
def sync_qa_to_knowledge(q_id):
    try:
        q_data = supabase.table("qa_board").select("*").eq("id", q_id).execute().data[0]
        a_data = supabase.table("qa_answers").select("*").eq("question_id", q_id).order("created_at").execute().data
        ans_list = [f"[{'답글' if a.get('parent_id') else '실전해결'}] {a['author']} (👍{a.get('likes', 0)}): {a['content']}" for a in a_data]
        full_sync_txt = f"현장상황: {q_data['content']}\n조치방법:\n" + "\n".join(ans_list)
        is_life, mfr, mod_num = analyze_query_v75(q_data['title'] + q_data['content'])
        supabase.table("knowledge_base").upsert({
            "qa_id": q_id, "category": "맛집/정보" if is_life else "게시판답변",
            "manufacturer": mfr if mfr else ("생활정보" if is_life else "커뮤니티"),
            "model_name": q_data['category'], "issue": q_data['title'],
            "solution": full_sync_txt, "registered_by": q_data['author'],
            "embedding": get_embedding(f"{mfr} {q_data['title']} {full_sync_txt}")
        }, on_conflict="qa_id").execute()
    except: pass

# --- UI 설정 ---
st.set_page_config(page_title="금강수계 AI 챗봇", layout="centered", initial_sidebar_state="collapsed")
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
    </style>
    <div class="fixed-header"><span class="header-title">🌊 금강수계 수질자동측정망 AI 챗봇</span></div>
    """, unsafe_allow_html=True)

menu_options = ["🔍 통합 지식 검색", "📝 현장 노하우 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리", "💬 질문 게시판 (Q&A)"]
selected_mode = st.selectbox("☰ 메뉴", options=menu_options, index=menu_options.index(st.session_state.page_mode), label_visibility="collapsed")
if selected_mode != st.session_state.page_mode:
    st.session_state.page_mode = selected_mode
    st.rerun()

# --- 1. 통합 지식 검색 (V75: 트리플 락 중복 제거 알고리즘) ---
if st.session_state.page_mode == "🔍 통합 지식 검색":
    col_i, col_b = st.columns([0.8, 0.2])
    with col_i: user_q = st.text_input("상황 입력", label_visibility="collapsed", placeholder="질문이나 맛집을 입력하세요")
    with col_b: search_clicked = st.button("조회", use_container_width=True)
    if user_q and (search_clicked or user_q):
        with st.spinner("정밀 필터링 및 중복 지식 제거 중..."):
            try:
                is_life, target_mfr, target_mod_num = analyze_query_v75(user_q)
                query_vec = get_embedding(user_q)
                exp_cands = supabase.rpc("match_knowledge", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 40}).execute().data or []
                man_cands = supabase.rpc("match_manual", {"query_embedding": query_vec, "match_threshold": 0.05, "match_count": 30}).execute().data or []
                
                final_results = []
                # 중복 체크용 집합
                seen_contents = set()
                seen_keys = set()

                for d in (exp_cands + man_cands):
                    cat, mfr, mod = d.get('category', '매뉴얼'), d.get('manufacturer', '기타'), d.get('model_name', '일반').upper()
                    content_body = d.get('solution', d.get('content', ''))
                    
                    # [V75 핵심] 트리플 락 중복 제거 논리
                    # 1. 고유 키 생성 (테이블구분 + ID)
                    unique_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                    # 2. 내용 지문 생성 (공백 제거 후 앞 50글자)
                    content_fingerprint = "".join(content_body.split())[:50]

                    if unique_key in seen_keys or content_fingerprint in seen_contents:
                        continue # 이미 처리된 데이터는 건너뜀

                    # 도메인 격리 및 브랜드 필터 (V74 논리)
                    if is_life:
                        if cat == "맛집/정보": 
                            final_results.append(d)
                            seen_keys.add(unique_key); seen_contents.add(content_fingerprint)
                        continue
                    if cat == "맛집/정보": continue
                    
                    other_brands = ["시마즈", "백년기술", "코비", "케이엔알", "YSI"]
                    is_conflict = any(ob in mfr and ob != target_mfr for ob in other_brands)
                    model_hit = target_mod_num and target_mod_num in mod
                    
                    if target_mfr == mfr or model_hit or not is_conflict:
                        final_results.append(d)
                        seen_keys.add(unique_key)
                        seen_contents.add(content_fingerprint)

                if final_results:
                    final_results = final_results[:10]
                    context = "\n".join([f"[{d.get('category','매뉴얼')}/{d['manufacturer']}/{d['model_name']}]: {d.get('solution', d.get('content'))}" for d in final_results])
                    ans_p = f"""수질 전문가 답변. 
                    1. 질문의 장비번호({target_mod_num}) 정보를 최우선 요약.
                    2. 제조사가 '기타/커뮤니티'인 데이터는 질문 장비 정보로 간주.
                    3. 중복된 내용은 하나로 합쳐서 자연스럽게 답변. 3줄 요약.
                    데이터: {context} \n 질문: {user_q}"""
                    st.info(ai_model.generate_content(ans_p).text)
                    st.markdown("---")
                    for d in final_results:
                        tag_name = "게시판답변" if d.get('qa_id') else ("매뉴얼" if 'content' in d else ("맛집정보" if d.get('category') == "맛집/정보" else "현장경험"))
                        with st.expander(f"[{tag_name}] {d['manufacturer']} | {d['model_name']}"):
                            st.write(d.get('solution', d.get('content')))
                else: st.warning("⚠️ 일치하는 지식을 찾지 못했습니다.")
            except Exception as e: st.error(f"조회 실패: {e}")

# --- 2. 현장 노하우 등록 ---
elif st.session_state.page_mode == "📝 현장 노하우 등록":
    st.subheader("📝 현장 노하우 등록")
    cat_sel = st.selectbox("분류", ["기기점검", "현장꿀팁", "맛집/정보"])
    with st.form("reg_v75", clear_on_submit=True):
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

# --- 3. 문서(매뉴얼) 등록 ---
elif st.session_state.page_mode == "📄 문서(매뉴얼) 등록":
    st.subheader("📄 매뉴얼 등록 (768차원)")
    up_f = st.file_uploader("PDF 업로드", type=["pdf"])
    if up_f:
        if 's_m' not in st.session_state or st.session_state.get('l_f') != up_f.name:
            with st.spinner("분석 중..."):
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                preview = "\n".join([p.extract_text() for p in pdf_reader.pages[:3] if p.extract_text()])
                info = extract_json(ai_model.generate_content(f"제조사/모델명 JSON: {preview[:3000]}").text) or {}
                st.session_state.s_m, st.session_state.s_mod, st.session_state.l_f = info.get("mfr", "기타"), info.get("model", "매뉴얼"), up_f.name
        c1, c2 = st.columns(2)
        f_mfr, f_model = st.text_input("🏢 제조사", value=st.session_state.s_m), st.text_input("🏷️ 모델명", value=st.session_state.s_mod)
        if st.button("🚀 저장"):
            with st.status("📑 저장 중...") as status:
                pdf_reader = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                all_t = "\n".join([p.extract_text() for p in pdf_reader.pages if p.extract_text()])
                chunks = [all_t[i:i+1000] for i in range(0, len(all_t), 800)]
                for i, chunk in enumerate(chunks):
                    supabase.table("manual_base").insert({"manufacturer": f_mfr, "model_name": f_model, "content": clean_text_for_db(chunk), "file_name": up_f.name, "page_num": (i//2)+1, "embedding": get_embedding(chunk)}).execute()
                st.success("✅ 완료!"); st.rerun()

# --- 4. 데이터 전체 관리 (라벨 리파이너 탑재) ---
elif st.session_state.page_mode == "🛠️ 데이터 전체 관리":
    if st.button("🔄 게시판 지식 재동기화 (V75 반영)"):
        qa_list = supabase.table("qa_board").select("id").execute().data
        for qa in qa_list: sync_qa_to_knowledge(qa['id'])
        st.success("✅ 완료!")
    t1, t2 = st.tabs(["📝 경험/맛집 리파이너", "📄 매뉴얼 리파이너"])
    with t1:
        ms = st.text_input("🔍 이름표 수정할 데이터 검색")
        if ms:
            res = supabase.table("knowledge_base").select("*").or_(f"manufacturer.ilike.%{ms}%,issue.ilike.%{ms}%,model_name.ilike.%{ms}%").execute()
            for r in res.data:
                with st.expander(f"[{r['manufacturer']}] {r['issue']}"):
                    with st.form(f"edit_e_{r['id']}"):
                        e_mfr, e_mod = st.text_input("제조사/식당명", value=r['manufacturer']), st.text_input("모델명/위치", value=r['model_name'])
                        e_sol = st.text_area("내용", value=r['solution'])
                        if st.form_submit_button("💾 갱신"):
                            new_vec = get_embedding(f"{r['category']} {e_mfr} {e_mod} {r['issue']} {e_sol}")
                            supabase.table("knowledge_base").update({"manufacturer": e_mfr, "model_name": e_mod, "solution": e_sol, "embedding": new_vec}).eq("id", r['id']).execute()
                            st.success("✅ 갱신 완료!"); st.rerun()
    with t2:
        ds = st.text_input("🔍 매뉴얼 브랜드 수정")
        if ds:
            res = supabase.table("manual_base").select("*").or_(f"manufacturer.ilike.%{ds}%,file_name.ilike.%{ds}%").execute()
            files = list(set([r['file_name'] for r in res.data]))
            for f in files:
                sample = next(r for r in res.data if r['file_name'] == f)
                with st.expander(f"📄 {f}"):
                    with st.form(f"edit_m_{f}"):
                        new_mfr, new_mod = st.text_input("제조사 변경", value=sample['manufacturer']), st.text_input("모델명 변경", value=sample['model_name'])
                        if st.form_submit_button("💾 파일 전체 갱신"):
                            supabase.table("manual_base").update({"manufacturer": new_mfr, "model_name": new_mod}).eq("file_name", f).execute()
                            st.success("✅ 갱신 완료!"); st.rerun()

# --- 5. 질문 게시판 ---
elif st.session_state.page_mode == "💬 질문 게시판 (Q&A)":
    if st.session_state.get('selected_q_id'):
        if st.button("⬅️ 목록"): st.session_state.selected_q_id = None; st.rerun()
        q_d = supabase.table("qa_board").select("*").eq("id", st.session_state.selected_q_id).execute().data[0]
        st.subheader(f"❓ {q_d['title']}"); st.caption(f"👤 {q_d['author']} | 📅 {q_d['created_at'][:10]}")
        if st.button(f"👍 {q_d.get('likes', 0)}", key="q_lk"):
            supabase.table("qa_board").update({"likes": q_d.get('likes', 0) + 1}).eq("id", q_d['id']).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
        st.info(q_d['content'])
        ans_d = supabase.table("qa_answers").select("*").eq("question_id", q_d['id']).order("created_at").execute().data
        for a in [x for x in ans_d if not x.get('parent_id')]:
            st.markdown(f'<div style="padding:10px; background:#f8fafc; border-radius:8px; margin-bottom:5px;"><b>{a["author"]}</b>: {a["content"]}</div>', unsafe_allow_html=True)
            if st.button(f"👍 {a.get('likes', 0)}", key=f"al_{a['id']}"):
                supabase.table("qa_answers").update({"likes": a.get('likes', 0) + 1}).eq("id", a['id']).execute(); sync_qa_to_knowledge(q_d['id']); st.rerun()
        with st.form("ans_v75"):
            at, ct = st.text_input("작성자"), st.text_area("답변")
            if st.form_submit_button("등록"):
                supabase.table("qa_answers").insert({"question_id": q_d['id'], "author": at, "content": clean_text_for_db(ct)}).execute()
                sync_qa_to_knowledge(q_d['id']); st.rerun()
    else:
        st.subheader("💬 질문 게시판")
        with st.popover("➕ 질문하기", use_container_width=True):
            with st.form("q_v75"):
                cat, auth, tit, cont = st.selectbox("분류", ["기기이상", "일반"]), st.text_input("작성자"), st.text_input("제목"), st.text_area("내용")
                if st.form_submit_button("등록"):
                    res = supabase.table("qa_board").insert({"author": auth, "title": tit, "content": clean_text_for_db(cont), "category": cat}).execute()
                    if res.data: sync_qa_to_knowledge(res.data[0]['id']); st.rerun()
        for q_r in supabase.table("qa_board").select("*").order("created_at", desc=True).execute().data:
            c1, c2 = st.columns([0.8, 0.2])
            c1.markdown(f"**[{q_r['category']}] {q_r['title']}** (👍 {q_r.get('likes', 0)})\n👤 {q_r['author']} | 📅 {q_r['created_at'][:10]}")
            if c2.button("보기", key=f"q_{q_r['id']}"): st.session_state.selected_q_id = q_r['id']; st.rerun()
            st.write("---")
