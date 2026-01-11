import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V186] 스트리밍 지원 오케스트레이터:
    1. V185의 초병렬(Hyper-Parallel) 부트스트랩 유지
    2. 요약 생성을 여기서 하지 않고, 순위만 매겨서 즉시 반환 (UI에서 스트리밍하기 위함)
    """
    
    # 1. [V185 유지] 초병렬 초기 진입 (Embedding + Intent)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    # [V184 유지] Intent 안전장치
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. [V183 유지] 병렬 배치 필터링 (블랙리스트 조회)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # 3. [V183 유지] 병렬 DB 조회
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # 4. 후보군 압축 및 하드 메타데이터 필터링 (V184 로직 전면 보존)
    raw_candidates = []
    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            score = (d.get('similarity') or 0)
            
            # V184 None 값 방어 로직
            t_mfr = str(intent.get('target_mfr') or '미지정').lower()
            d_mfr = str(d.get('manufacturer') or '').lower()
            
            if t_mfr != '미지정' and t_mfr != 'none' and t_mfr not in d_mfr:
                score -= 5.0
            
            t_item = str(intent.get('target_item') or '공통').lower()
            d_item = str(d.get('measurement_item') or '').lower()
            
            if t_item != '공통' and t_item != 'none' and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 상위 8개 선정
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. [V186 변경] 요약 대기 없이 '빠른 리랭킹'만 수행 후 즉시 리턴
    # (요약은 UI에서 스트리밍으로 처리하여 체감 속도 0초 구현)
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
