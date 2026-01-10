import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V179] 통합 지능 엔진 오케스트레이터:
    검색, 필터링, 리랭킹, 요약을 하나의 흐름으로 통합하여 속도 극대화
    """
    # 1. 의도 분석 및 벡터 생성 (캐싱 적용됨)
    intent = analyze_search_intent(ai_model, user_q)
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        
    q_vec = get_embedding(user_q)
    
    # 2. 병렬 DB 조회 (Parallel Execution - V177 유지)
    penalties = db.get_penalty_counts()
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q)
        m_res = future_m.result()
        k_res = future_k.result()
    
    # 3. 파이썬 레벨 하드 필터링 (V174 지능 보존)
    raw_candidates = []
    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            score = (d.get('similarity') or 0)
            
            # 브랜드/항목 불일치 시 강력한 페널티 (Hard Filter)
            t_mfr = intent.get('target_mfr', '').lower()
            d_mfr = str(d.get('manufacturer', '')).lower()
            if t_mfr and t_mfr not in d_mfr:
                score -= 5.0
            
            t_item = intent.get('target_item', '').lower()
            d_item = str(d.get('measurement_item', '')).lower()
            if t_item and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 4. 정렬 및 상위 후보군 선별 (Top 8)
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. [V179 핵심] 통합 엔진 호출 (리랭킹 + 요약 동시 처리)
    # 이제 별도의 요약 버튼 클릭 없이 검색과 동시에 결과가 나옵니다.
    final_results, instant_summary = unified_rerank_and_summary_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, instant_summary, intent
