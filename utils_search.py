import time
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_hybrid_search(ai_model, db, user_q, u_threshold):
    """
    [V178] 검색의 핵심 프로세스를 UI와 분리하여 처리
    """
    # 1. 의도 분석 및 벡터 생성 (캐싱 적용됨)
    intent = analyze_search_intent(ai_model, user_q)
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        
    q_vec = get_embedding(user_q)
    
    # 2. 병렬 DB 조회 (Parallel Execution)
    penalties = db.get_penalty_counts()
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q)
        m_res = future_m.result()
        k_res = future_k.result()
    
    # 3. 파이썬 레벨 하드 필터링 (Speed Optimization)
    raw_candidates = []
    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            score = (d.get('similarity') or 0)
            
            # 브랜드/항목 불일치 시 강력한 페널티 (V174 지능 보존)
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
    
    # 4. 정렬 및 AI 리랭킹 후보 압축 (Top 8)
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. AI 리랭킹 (V177 캐싱 적용됨)
    final = rerank_results_ai(ai_model, user_q, raw_candidates, intent)
    
    return final, intent
