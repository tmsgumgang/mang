import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V184] 고속 지능형 오케스트레이터 (안전성 강화 패치):
    AttributeError 방지를 위한 메타데이터 Null 값 방어 로직 추가
    """
    # 1. 벡터 생성 및 의도 분석
    q_vec = get_embedding(user_q)
    intent = analyze_search_intent(ai_model, user_q)
    
    # [V180 안전장치] intent 무결성 확인
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. 병렬 처리: 블랙리스트 조회 및 페널티 계산 (V183 유지)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # 3. 병렬 DB 조회: 매뉴얼과 지식 동시 검색 (V183 유지)
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # 4. 상위 후보군 선별 및 하드 메타데이터 필터링
    raw_candidates = []
    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            score = (d.get('similarity') or 0)
            
            # [V184 핵심 수정] None 값 방어 로직 (str 변환 및 or 연산 추가)
            # AI가 None을 반환하더라도 '미지정' 문자열로 치환하여 에러 방지
            t_mfr = str(intent.get('target_mfr') or '미지정').lower()
            d_mfr = str(d.get('manufacturer') or '').lower()
            
            # 브랜드 불일치 시 강력한 페널티 (Hard Filter)
            if t_mfr != '미지정' and t_mfr != 'none' and t_mfr not in d_mfr:
                score -= 5.0
            
            t_item = str(intent.get('target_item') or '공통').lower()
            d_item = str(d.get('measurement_item') or '').lower()
            
            # 항목 불일치 시 페널티
            if t_item != '공통' and t_item != 'none' and t_item not in d_item:
                score -= 3.0
            
            # 블랙리스트 누적 페널티 반영
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. 통합 엔진 호출 (V179/183 유지)
    final_results, instant_summary = unified_rerank_and_summary_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, instant_summary, intent, q_vec
