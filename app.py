import streamlit as st
import io, time
import PyPDF2
import google.generativeai as genai
from supabase import create_client
from logic_processor import *
from db_services import DBManager

# [보안] Streamlit Secrets
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

# --- 표준 카테고리 정의 ---
DIRECT_INPUT_LABEL = "직접 입력"
DOMAIN_MAP = {
    "기술지식": {
        "측정기기": ["TOC", "TN", "TP", "일반항목", "VOCs", "물벼룩", "황산화", "미생물", "발광박테리아", "기타"],
        "채수시설": ["펌프", "레듀샤", "호스", "커플링", "캡록", "여과 필터", "기타"],
        "전처리/반응조": ["공통"], "통신/데이터": ["공통"], "전기/제어": ["공통"], "소모품/시약": ["공통"]
    },
    "행정절차": { "점검/보고": ["공통"], "구매/신청": ["공통"], "안전/규정": ["공통"], "매뉴얼/지침": ["공통"] },
    "복지생활": { "맛집/식당": ["공통"], "카페/편의": ["공통"], "주차/교통": ["공통"], "기상/재난": ["공통"] }
}

def get_embedding(text):
    result = genai.embed_content(model="models/text-embedding-004", content=clean_text_for_db(text), task_type="retrieval_document")
    return result['embedding']

# --- UI Layout (가이드 박스 스타일 복구) ---
st.set_page_config(page_title="금강수계 AI V135", layout="wide", initial_sidebar_state="collapsed")
st.markdown("""<style>
    .fixed-header { position: fixed; top: 0; left: 0; width: 100%; background-color: #004a99; color: white; padding: 10px 0; z-index: 999; text-align: center; }
    .main .block-container { padding-top: 5rem !important; }
    .meta-bar { background-color: rgba(128, 128, 128, 0.1); border-left: 5px solid #004a99; padding: 8px; border-radius: 4px; font-size: 0.8rem; margin-bottom: 10px; display: flex; gap: 15px; }
    .guide-box { background-color: #f8fafc; border: 1px solid #e2e8f0; padding: 12px; border-radius: 8px; font-size: 0.85rem; color: #475569; margin-bottom: 15px; line-height: 1.5; }
    .centered-text { text-align: center; }
</style><div class="fixed-header">🌊 금강수계 수질자동측정망 AI V135</div>""", unsafe_allow_html=True)

# 메뉴 선택 (중앙 배치)
_, menu_col, _ = st.columns([1, 2, 1])
with menu_col:
    menu = ["🔍 통합 지식 검색", "📝 지식 등록", "📄 문서(매뉴얼) 등록", "🛠️ 데이터 전체 관리"]
    mode = st.selectbox("메뉴 선택", menu, label_visibility="collapsed")

st.divider()

# --- 1. 통합 검색 (가이드 박스 설명 복구 및 센터 정렬) ---
if mode == "🔍 통합 지식 검색":
    _, main_col, _ = st.columns([1, 2, 1])
    
    with main_col:
        s_mode = st.radio("검색 모드", ["업무기술 🛠️", "생활정보 🍴"], horizontal=True, label_visibility="collapsed")
        
        # [V135 핵심] 임계값 설명 가이드 박스 복구
        u_threshold = st.slider("정밀도(임계값) 설정", 0.0, 1.0, 0.5, 0.05)
        st.markdown(f"""
        <div class="guide-box">
            🎯 <b>검색 모드: {"정밀 타격" if u_threshold > 0.6 else ("균형 잡힌 검색" if u_threshold >= 0.4 else "포괄적 탐색")}</b><br>
            • <b>높은 값(0.7~0.9):</b> 모델명(TN-2060 등)이나 전문 용어를 정확히 찾을 때 적합합니다.<br>
            • <b>낮은 값(0.1~0.3):</b> 질문과 단어는 다르지만 '의미'가 유사한 노하우를 폭넓게 찾습니다.
        </div>
        """, unsafe_allow_html=True)
        
        user_q = st.text_input("질문 입력", placeholder="질문이나 모델명을 입력하세요", label_visibility="collapsed")
        search_btn = st.button("🔍 지식 검색 실행", use_container_width=True)

    if user_q and (search_btn or user_q):
        with st.spinner("지식고를 정밀하게 분석 중..."):
            target_doms = ["기술지식", "기술자산"] if "업무" in s_mode else ["복지생활"]
            q_vec = get_embedding(user_q)
            blacklist = db.get_blacklist_ids(user_q)
            penalties = db.get_penalty_counts()
            
            results = db.match_manual_db(q_vec, u_threshold) + db.match_knowledge_db(q_vec, u_threshold)
            final = []
            for d in results:
                u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
                if u_key not in blacklist and d.get('domain') in target_doms and not d.get('review_required') and d.get('semantic_version') == 1:
                    d['final_score'] = (d.get('similarity') or 0) - (penalties.get(u_key, 0) * 0.05)
                    final.append(d)
            
            final = sorted(final, key=lambda x: x['final_score'], reverse=True)
            
            _, res_col, _ = st.columns([0.5, 3, 0.5])
            with res_col:
                if final:
                    st.subheader("🤖 AI 정밀 요약 답변")
                    st.info(ai_model.generate_content(f"질문: {user_q} 데이터: {final[:12]}").text)
                    for d in final[:5]:
                        with st.expander(f"[{d.get('model_name','공통')}] 상세 내용"):
                            st.markdown(f'<div class="meta-bar"><span>📁 출처: {d.get("file_name","개별지식")}</span><span>🧪 항목: {d.get("measurement_item","공통")}</span></div>', unsafe_allow_html=True)
                            st.write(d.get('content') or d.get('solution'))
                else: st.warning("🔍 일치하는 승인된 지식이 없습니다. 임계값을 낮추어 보십시오.")

# --- 4. 데이터 전체 관리 (중앙 레이아웃 및 모든 기능 유지) ---
elif mode == "🛠️ 데이터 전체 관리":
    _, tab_col, _ = st.columns([0.1, 3, 0.1])
    with tab_col:
        tabs = st.tabs(["🧹 시맨틱 최신화", "🚨 수동 분류실", "🏗️ 지식 재건축", "🏷️ 라벨 승인"])
        
        with tabs[3]: # 라벨 승인 (일괄 처리 로직 포함)
            st.subheader("🏷️ AI 라벨링 최종 승인")
            t_sel = st.radio("테이블 선택", ["경험", "매뉴얼"], horizontal=True)
            t_name = "knowledge_base" if t_sel == "경험" else "manual_base"
            
            st.markdown('<div style="background-color:#f0f9ff; padding:20px; border-radius:10px; border:1px solid #bae6fd;">', unsafe_allow_html=True)
            st.write("📂 **파일 단위 일괄 승인**")
            all_staging = db.supabase.table(t_name).select("file_name").eq("semantic_version", 2).execute().data
            staging_files = sorted(list(set([r['file_name'] for r in all_staging if r.get('file_name')])))
            
            if staging_files:
                cf1, cf2 = st.columns([0.7, 0.3])
                target_f = cf1.selectbox("승인할 파일 선택", options=staging_files, label_visibility="collapsed")
                if cf2.button("🚀 전체 승인", use_container_width=True):
                    if db.bulk_approve_file(t_name, target_f):
                        st.toast(f"'{target_f}' 승인 완료!"); time.sleep(1); st.rerun()
            else: st.write("대기 중인 파일이 없습니다.")
            st.markdown('</div>', unsafe_allow_html=True)
            
            st.write("🔍 **개별 지식 검토**")
            staging = db.supabase.table(t_name).select("*").eq("semantic_version", 2).limit(2).execute().data
            if not staging: st.success("🎉 모든 검토 완료!")
            else:
                for r in staging:
                    with st.form(key=f"apprv_{r['id']}"):
                        st.write(f"ID {r['id']}: {r.get('content') or r.get('solution')[:400]}")
                        c1, c2, c3 = st.columns(3)
                        a_mfr = c1.text_input("제조사", value=r.get('manufacturer','미지정'), key=f"mfr_{r['id']}")
                        a_mod = c2.text_input("모델명", value=r.get('model_name','공통'), key=f"mod_{r['id']}")
                        a_itm = c3.text_input("항목", value=r.get('measurement_item','공통'), key=f"itm_{r['id']}")
                        if st.form_submit_button("✅ 개별 승인"):
                            db.supabase.table(t_name).update({"manufacturer": a_mfr, "model_name": a_mod, "measurement_item": a_itm, "semantic_version": 1}).eq("id", r['id']).execute()
                            st.rerun()

# --- 2, 3 메뉴 (센터 레이아웃 적용 전문) ---
elif mode == "📄 문서(매뉴얼) 등록":
    _, up_col, _ = st.columns([1, 2, 1])
    with up_col:
        up_f = st.file_uploader("PDF 업로드", type=["pdf"])
        if up_f and st.button("🚀 지능형 학습 시작", use_container_width=True):
            pdf_r = PyPDF2.PdfReader(io.BytesIO(up_f.read()))
            all_t = "\n".join([p.extract_text() for p in pdf_r.pages if p.extract_text()])
            chunks = semantic_split_v135(all_t)
            for chunk in chunks:
                meta = extract_metadata_ai(ai_model, chunk)
                db.supabase.table("manual_base").insert({
                    "domain": "기술지식", "content": clean_text_for_db(chunk), "file_name": up_f.name,
                    "manufacturer": meta.get('manufacturer','미지정'), "model_name": meta.get('model_name','미지정'),
                    "measurement_item": meta.get('measurement_item','공통'), "embedding": get_embedding(chunk), "semantic_version": 2
                }).execute()
            st.success("학습 완료!"); st.rerun()

elif mode == "📝 지식 등록":
    _, reg_col, _ = st.columns([1, 2, 1])
    with reg_col:
        with st.form("reg_v135"):
            f_dom = st.selectbox("도메인", list(DOMAIN_MAP.keys()))
            f_iss = st.text_input("제목")
            f_sol = st.text_area("내용")
            if st.form_submit_button("💾 저장하기", use_container_width=True):
                db.supabase.table("knowledge_base").insert({"domain": f_dom, "issue": f_iss, "solution": f_sol, "embedding": get_embedding(f_iss), "semantic_version": 1}).execute()
                st.success("등록 완료!")
