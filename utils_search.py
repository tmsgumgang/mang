import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V187] 모델명 방화벽(Zero Tolerance) 탑재 오케스트레이터:
    사용자가 특정 모델을 언급하면, 불일치하는 지식은 점수 감점이 아니라 '즉시 제외' 처리.
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

    # 4. 후보군 압축 및 방화벽 가동 (Firewall Logic)
    raw_candidates = []
    
    # 비교를 위한 타겟 메타데이터 정규화
    t_mfr = str(intent.get('target_mfr') or '미지정').lower().replace(" ", "")
    t_model = str(intent.get('target_model') or '미지정').lower().replace(" ", "")
    t_item = str(intent.get('target_item') or '공통').lower().replace(" ", "")

    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            # 문서 메타데이터 정규화
            d_mfr = str(d.get('manufacturer') or '').lower().replace(" ", "")
            d_model = str(d.get('model_name') or '').lower().replace(" ", "")
            d_item = str(d.get('measurement_item') or '').lower().replace(" ", "")
            
            # ---------------------------------------------------------
            # [V187 핵심] 모델명 불일치 즉시 차단 (Zero Tolerance Firewall)
            # 조건: 사용자가 모델을 특정했고(미지정 아님), 문서에도 모델명이 있는데, 서로 포함 관계가 아닐 때
            # ---------------------------------------------------------
            if t_model != '미지정' and d_model != '' and t_model not in d_model and d_model not in t_model:
                continue  # [강력 차단] 점수 계산조차 하지 않고 루프 건너뜀
            
            # [V187 추가] 제조사 불일치 즉시 차단
            if t_mfr != '미지정' and d_mfr != '' and t_mfr not in d_mfr:
                continue

            # ---------------------------------------------------------
            # 아래는 기존 점수 계산 로직 (살아남은 후보들 간의 순위 경쟁)
            # ---------------------------------------------------------
            score = (d.get('similarity') or 0)
            
            # 항목(Item)은 조금 유연하게 처리 (측정항목 이름이 다양할 수 있으므로 감점 방식 유지)
            if t_item != '공통' and t_item != 'none' and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 상위 8개 선정
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. [V186 유지] 빠른 리랭킹 후 반환
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
