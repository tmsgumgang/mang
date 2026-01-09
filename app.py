import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

# [환경 설정]
SUPABASE_URL = st.secrets["SUPABASE_URL"]
SUPABASE_KEY = st.secrets["SUPABASE_KEY"]
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]

@st.cache_resource
def init_system():
    genai.configure(api_key=GEMINI_API_KEY)
    ai_model = genai.GenerativeModel('gemini-2.0-flash')
    sb_client = create_client(SUPABASE_URL, SUPABASE_KEY)
    return ai_model, DBManager(sb_client)

ai_model, db = init_system()

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI 스타일링 (V144 다크모드 대응 및 시인성 강화) ---
st.set_page_config(page_title="금강수계 AI V144", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; font-weight: bold; }
    .main .block-container { padding-top: 5.5rem !important; }
    .meta-bar { background-color: rgba(255, 255, 255, 0.1); border-left: 5px solid #004a99; padding: 10px; border-radius: 4px; font-size: 0.85rem; margin-bottom: 10px; color: #ffffff !important; }
    .guide-box { background-color: #f1f5f9; border: 1px solid #cbd5e1; padding: 15px; border-radius: 8px; font-size: 0.9rem; color: #1e293b; margin-bottom: 15px; }
    label, p, span { color: inherit !important; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V144</div>""", unsafe_allow_html=True)

_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    mode = st.selectbox("메뉴", ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"], label_visibility="collapsed")

st.divider()

# --- 1. 통합 지식 검색 ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    with main_col:
        s_mode = st.radio("검색 대상", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        u_threshold = st.slider("검색 정밀도 설정", 0.0, 1.0, 0.6, 0.05)
        st.markdown(f'<div class="guide-box">🎯 <b>검색 모드: {"정밀 타격" if u_threshold > 0.6 else "균형 탐색"}</b><br>임계값이 높을수록 질문과 기술 키워드가 정확히 일치하는 정보만 표시합니다.</div>', unsafe_allow_html=True)
        user_q = st.text_input("무엇이 궁금하신가요?", placeholder="예: TN-2060 점검 방법", label_visibility="collapsed")
        search_btn = st.button("🔍 AI 전문가 지식 검색", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("전문가 지식 베이스에서 가장 적절한 답변을 구성 중입니다..."):
            intent = analyze_search_intent(ai_model, user_q)
            q_vec = get_embedding(user_q)
            penalties = db.get_penalty_counts()
            m_res = db.match_filtered_db("match_manual", q_vec, u_threshold, intent)
            k_res = db.match_filtered_db("match_knowledge", q_vec, u_threshold, intent)
            
            final = []
            for d in (m_res + k_res):
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if d.get('semantic_version') == 1:
                    score = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.1)
                    if d.get('is_verified'): score += 0.15
                    final.append({**d, 'final_score': score, 'u_key': u_key})
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                if final:
                    st.subheader("🤖 AI 전문가 통합 요약")
                    st.info(generate_relevant_summary(ai_model, user_q, final[:10]))
                    for d in final[:8]:
                        v_mark = ' ✅ 인증됨' if d.get('is_verified') else ''
                        with st.expander(f"[{d.get('model_name','공통')}] {d.get('issue', '매뉴얼 데이터')} {v_mark}"):
                            st.markdown(f'<div class="meta-bar"><span>🏢 제조사: <b>{d.get("manufacturer","미지정")}</b></span><span>🧪 항목: <b>{d.get("measurement_item","공통")}</b></span><span>🏷️ 모델: <b>{d.get("model_name","공통")}</b></span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                            with st.form(key=f"edit_{d['u_key']}"):
                                st.markdown("🔧 **데이터 라벨 교정**")
                                c1, c2, c3 = st.columns(3)
                                e_mfr = c1.text_input("제조사", value=d.get('manufacturer',''), key=f"m_{d['u_key']}")
                                e_mod = c2.text_input("모델명", value=d.get('model_name',''), key=f"o_{d['u_key']}")
                                e_itm = c3.text_input("항목", value=d.get('measurement_item',''), key=f"i_{d['u_key']}")
                                if st.form_submit_button("💾 현장 정보 저장"):
                                    t_name = "knowledge_base" if "EXP" in d['u_key'] else "manual_base"
                                    if db.update_record_labels(t_name, d['id'], e_mfr, e_mod, e_itm):
                                        st.toast("지식이 실시간으로 교정되었습니다!"); time.sleep(0.5); st.rerun()
                else: st.warning("🔍 검색 결과가 없습니다. 정밀도를 조금 낮춰보세요.")

# --- 4. 데이터 전체 관리 ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        with tabs[3]: 
            st.subheader("🏷️ AI 라벨링 데이터 최종 검토")
            t_sel = st.radio("데이터 유형", ["경험 지식", "매뉴얼 데이터"], horizontal=True, key="apprv_target")
            t_name = "knowledge_base" if t_sel == "경험 지식" else "manual_base"
            
            if t_name == "manual_base":
                st.markdown('<div style="background-color:rgba(0, 74, 153, 0.1); padding:20px; border-radius:10px; border: 1px solid #004a99;">', unsafe_allow_html=True)
                st.write("📂 **파일 단위 일괄 승인 시스템**")
                all_staging = db.supabase.table(t_name).select("file_name").eq("semantic_version", 2).execute().data
                files = sorted(list(set([r['file_name'] for r in all_staging if r.get('file_name')])))
                if files:
                    c1, c2 = st.columns([0.7, 0.3])
                    target_f = c1.selectbox("승인할 파일 선택", files, label_visibility="collapsed")
                    if c2.button("🚀 선택 파일 전체 승인", use_container_width=True):
                        db.bulk_approve_file(t_name, target_f); st.toast(f"{target_f} 승인 완료!"); time.sleep(1); st.rerun()
                else: st.info("모든 매뉴얼 데이터가 검토 완료되었습니다.")
                st.markdown('</div>', unsafe_allow_html=True)

            staging = db.supabase.table(t_name).select("*").eq("semantic_version", 2).limit(3).execute().data
            if staging:
                for r in staging:
                    with st.form(key=f"aprv_{r['id']}"):
                        st.write(f"**ID {r['id']}** | {r.get('content') or r.get('solution')[:400]}...")
                        c1, c2, c3 = st.columns(3)
                        mfr, mod, itm = c1.text_input("제조사", r.get('manufacturer','')), c2.text_input("모델명", r.get('model_name','')), c3.text_input("항목", r.get('measurement_item',''))
                        if st.form_submit_button("✅ 개별 데이터 확정"):
                            db.update_record_labels(t_name, r['id'], mfr, mod, itm); st.rerun()
            else: st.success("🎉 모든 대기 데이터 승인이 완료되었습니다.")

# --- 3. 문서(매뉴얼) 등록 (V144 핵심: 프로그레스 바 적용) ---
elif mode == "📄 문서(매뉴얼) 등록":
    _, up_col, _ = st.columns([1, 2, 1])
    with up_col:
        up_f = st.file_uploader("학습할 PDF 매뉴얼 업로드", type=["pdf"])
        if up_f and st.button("🚀 지능형 문서 학습 시작", use_container_width=True):
            with st.status("문서 분석 및 지식화 진행 중...", expanded=True) as status:
                st.write("1. PDF 텍스트 추출 중...")
                pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
                all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
                
                st.write("2. 시맨틱 청크 분할 및 AI 라벨링 중...")
                chunks = semantic_split_v143(all_t)
                total = len(chunks)
                prog_bar = st.progress(0)
                
                for i, chunk in enumerate(chunks):
                    meta = extract_metadata_ai(ai_model, chunk)
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
                    prog_bar.progress((i + 1) / total)
                    if i % 5 == 0: st.write(f"진행율: {i+1}/{total} 완료")
                
                status.update(label="✅ 문서 학습 및 라벨링 완료!", state="complete", expanded=False)
            st.success(f"'{up_f.name}' 파일이 총 {total}개의 지식 조각으로 분해되어 저장되었습니다.")
            time.sleep(1.5); st.rerun()

# --- 2. 지식 등록 ---
elif mode == "📝 지식 등록":
    _, reg_col, _ = st.columns([1, 2, 1])
    with reg_col:
        st.markdown('<div class="guide-box">💡 현장 점검 중 발생한 특이사항이나 자신만의 해결 노하우를 기록하세요.</div>', unsafe_allow_html=True)
        with st.form("reg_v144"):
            f_iss = st.text_input("장비 증상 또는 질문 제목", placeholder="예: TN-2060 시약 공급 라인 막힘")
            f_sol = st.text_area("해결 방법 및 조치 내용", placeholder="상세한 조치 단계나 주의사항을 입력하세요.", height=300)
            if st.form_submit_button("💾 전문가 지식 베이스 저장", use_container_width=True):
                if f_iss and f_sol:
                    db.supabase.table("knowledge_base").insert({
                        "domain": "기술지식", 
                        "issue": f_iss, 
                        "solution": f_sol, 
                        "embedding": get_embedding(f_iss), 
                        "semantic_version": 1, 
                        "is_verified": True
                    }).execute()
                    st.success("새로운 지식이 성공적으로 등록되었습니다!")
                    time.sleep(1); st.rerun()
                else: st.error("제목과 내용을 모두 입력해주세요.")
