import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    """
    [V188] 모델명 완전 정규화 헬퍼 함수
    공백, 하이픈(-), 언더바(_)를 모두 제거하여 'TOC-4200'과 'TOC 4200'을 동일하게 취급
    """
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V188] 모델명 완전 정규화(Canonical Normalization) 오케스트레이터:
    특수문자가 섞여 있어도 본질적인 모델명이 같으면 동일한 것으로 간주하여 방화벽 통과.
    """
    
    # 1. [V185 유지] 초병렬 초기 진입
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    # [V184 유지] Intent 안전장치
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. [V183 유지] 병렬 배치 필터링
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

    # 4. 후보군 압축 및 V188 정규화 방화벽 가동
    raw_candidates = []
    
    # [V188 핵심] 타겟 메타데이터 완전 정규화 (하이픈, 공백 제거)
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    t_item = normalize_model_name(intent.get('target_item') or '공통')

    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            # [V188 핵심] 문서 메타데이터도 동일하게 완전 정규화
            d_mfr = normalize_model_name(d.get('manufacturer') or '')
            d_model = normalize_model_name(d.get('model_name') or '')
            d_item = normalize_model_name(d.get('measurement_item') or '')
            
            # ---------------------------------------------------------
            # [V187/188] 모델명/제조사 불일치 즉시 차단 (Zero Tolerance)
            # 이제 'toc4200'과 'toc4200'으로 비교하므로 하이픈 유무 상관없이 통과됨
            # ---------------------------------------------------------
            if t_model != '미지정' and d_model != '' and t_model not in d_model and d_model not in t_model:
                continue 
            
            if t_mfr != '미지정' and d_mfr != '' and t_mfr not in d_mfr:
                continue

            # 점수 계산 로직 (V184 유지)
            score = (d.get('similarity') or 0)
            
            if t_item != '공통' and t_item != 'none' and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 상위 8개 선정
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. [V186 유지] 빠른 리랭킹
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
