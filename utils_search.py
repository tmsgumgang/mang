import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V190] 후보군 필터링 코어 로직
    strict_mode=True: 방화벽 가동 (불일치 시 차단, 단 '공통'은 허용)
    strict_mode=False: 방화벽 해제 (점수 감점만 적용)
    """
    filtered = []
    
    # 의도(Target) 정규화
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    t_item = normalize_model_name(intent.get('target_item') or '공통')
    
    # '공통'으로 간주할 키워드 목록
    safe_keywords = ['공통', 'general', 'common', 'none', 'unknown', '미지정', '미분류', '기타']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        # 문서(Doc) 정규화
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        
        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d.get('measurement_item') or '')
        
        # [V190 핵심] 공통 지식 프리패스 여부 확인
        is_common_doc = any(k in d_model_raw.lower() for k in safe_keywords) or (d_model == "")
        
        # --- [방화벽 로직] ---
        if strict_mode:
            # 1. 모델명 방화벽 (공통 문서는 통과)
            if t_model != '미지정' and not is_common_doc:
                # 타겟 모델이 문서에 없고, 문서 모델이 타겟에 없으면 차단
                if d_model != '' and t_model not in d_model and d_model not in t_model:
                    continue
            
            # 2. 제조사 방화벽
            if t_mfr != '미지정':
                is_common_mfr = any(k in d_mfr_raw.lower() for k in safe_keywords)
                if d_mfr != '' and not is_common_mfr and t_mfr not in d_mfr:
                    continue
        
        # --- [점수 계산] ---
        score = (d.get('similarity') or 0)
        
        # 항목(Item) 불일치 감점
        if t_item != '공통' and t_item != 'none' and t_item not in d_item:
            score -= 3.0
        
        # 블랙리스트 감점
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        # [V190] 공통 문서는 사용자가 특정 모델을 찾을 때 우선순위가 약간 밀리도록 조정 (특화 문서 우대)
        if is_common_doc and t_model != '미지정':
            score -= 0.5 

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V190] 유연한 방화벽 오케스트레이터:
    1차로 엄격하게 찾고, 결과가 없으면 2차로 유연하게 찾습니다.
    """
    # 1. 초기 진입 (병렬)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. 배치 필터링 및 DB 조회 (병렬)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # V189 출처 태깅
    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    all_docs = m_res + k_res

    # 3. [V190] 2단계 필터링 전략 (Fallback Strategy)
    # Step 1: 엄격 모드 (Strict) - 방화벽 가동
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # Step 2: 결과가 0건이면 유연 모드 (Relaxed) - 방화벽 해제, 점수 경쟁
    if not raw_candidates:
        raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)

    # 4. 빠른 리랭킹 (V186 유지)
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
