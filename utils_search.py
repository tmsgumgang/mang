import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V180] 통합 지능 엔진 오케스트레이터:
    AttributeError 방지를 위한 intent 유효성 검사 강화
    """
    # 1. 의도 분석 (V180 방어 로직 탑재)
    intent = analyze_search_intent(ai_model, user_q)
    
    # [V180] intent가 None이거나 dict가 아닐 경우 즉시 기본값 할당
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        
    q_vec = get_embedding(user_q)
    
    # 2. 병렬 DB 조회
    penalties = db.get_penalty_counts()
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q)
        m_res = future_m.result()
        k_res = future_k.result()
    
    # 3. 파이썬 레벨 하드 필터링
    raw_candidates = []
    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            score = (d.get('similarity') or 0)
            
            # [V180] intent.get() 호출 전 안전성 확보
            t_mfr = intent.get('target_mfr', '미지정').lower()
            d_mfr = str(d.get('manufacturer', '')).lower()
            if t_mfr != '미지정' and t_mfr not in d_mfr:
                score -= 5.0
            
            t_item = intent.get('target_item', '공통').lower()
            d_item = str(d.get('measurement_item', '')).lower()
            if t_item != '공통' and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 4. 정렬 및 후보 압축
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. 통합 엔진 호출 (리랭킹 + 요약)
    final_results, instant_summary = unified_rerank_and_summary_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, instant_summary, intent
