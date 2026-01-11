import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V197] 카테고리 교차 검증(Category Cross-Check):
    1. 타겟이 명확한데(채수펌프), 문서가 다른 특정 카테고리(TN, TOC 등)에 속하면 무조건 차단.
    2. '공통' 라벨이 붙어 있어도, 모델명에 타 카테고리명이 포함되면 차단 (위장 공통 적발).
    3. 텍스트 내용보다 메타데이터(항목/모델명)의 불일치를 최우선 거부 사유로 삼음.
    """
    filtered = []
    
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    t_item = normalize_model_name(raw_t_item)
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general', '기타']
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)

    # 상호 배타적인 주요 장비 카테고리 목록
    # (여기에 포함된 단어가 서로 다르면 절대 섞이면 안 됨)
    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        # 검색 대상 텍스트 통합
        d_content_full_raw = (
            d_mfr_raw + " " + d_model_raw + " " + d_item_raw + " " + 
            str(d.get('content') or '') + " " + str(d.get('solution') or '')
        ).lower()
        normalized_content = d_content_full_raw.replace(" ", "")

        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d_item_raw)
        
        similarity = d.get('similarity') or 0
        is_hybrid_hit = (similarity > 0.98) # SQL로 강제 소환된 녀석

        if strict_mode:
            # ---------------------------------------------------------------
            # [V197 핵심] 카테고리 교차 검증 (Cross-Check Logic)
            # 타겟 아이템이 명확할 때, 문서가 '다른' 메이저 카테고리에 속하는지 검사
            # ---------------------------------------------------------------
            if is_specific_target:
                # 1. 문서의 진짜 정체 파악 (항목 + 모델명 분석)
                doc_identity = d_item_raw.lower() + " " + d_model_raw.lower()
                
                # 타겟이 '채수펌프'인데, 문서가 'TN'이나 'TOC' 정체성을 가지면 차단
                # (단, 타겟 키워드 자체가 문서 정체성에 포함되면 통과 - 예: TN 펌프)
                is_identity_mismatch = False
                
                for cat in major_categories:
                    # 문서가 이 카테고리(cat) 속성을 가지고 있는데
                    if cat in doc_identity:
                        # 사용자가 찾는 타겟(raw_t_item)과는 전혀 다른 카테고리라면?
                        # (예: cat='tn' 있고, target='채수펌프' 일 때 -> 둘이 다르면 차단)
                        # 단순 문자열 비교가 아니라 의미적 불일치를 봐야 함
                        if cat not in raw_t_item.lower() and raw_t_item.lower() not in cat:
                             # 여기서 '채수펌프'와 '채수기'는 비슷하므로 봐줘야 함 (예외처리 필요)
                             if not (('채수' in cat and '채수' in raw_t_item.lower()) or 
                                     ('펌프' in cat and '펌프' in raw_t_item.lower())):
                                 is_identity_mismatch = True
                                 break
                
                if is_identity_mismatch:
                    continue # [즉시 차단] 너는 TN이잖아! 채수펌프 찾는데 왜 와?

            # 2. SQL 검증 (기존 유지)
            if is_specific_target and not is_hybrid_hit:
                if normalized_target not in normalized_content:
                    if similarity < 0.95:
                        continue 

            # 3. 아이템 카테고리 단순 불일치 체크 (기존 유지)
            if is_specific_target:
                is_doc_common = any(k in d_item for k in generic_keywords) or d_item == ""
                if not is_doc_common and t_item not in d_item and d_item not in t_item and not is_hybrid_hit:
                    if similarity < 0.95: 
                        continue

            # 4. 모델명 방화벽 (기존 유지)
            if t_model != '미지정':
                is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""
                if not is_doc_model_common and d_model != '' and t_model not in d_model and d_model not in t_model and not is_hybrid_hit:
                     if similarity < 0.95:
                         continue

        score = similarity
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        if is_specific_target and (raw_t_item.lower() in d_item_raw.lower() or raw_t_item.lower() in d_model_raw.lower()):
            score += 0.2

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    # (V195/196 오케스트레이션 로직 100% 동일하게 유지)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    is_specific_search = (intent.get('target_item') != '공통') or (intent.get('target_model') != '미지정')
    effective_threshold = 0.2 if is_specific_search else u_threshold

    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    all_docs = m_res + k_res

    # 1단계: 엄격 모드 (V197 카테고리 교차 검증)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # 2단계: 결과 0건이면 유연 모드
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
