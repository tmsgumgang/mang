import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V196] SQL 검증 필터(SQL-Verified Filter):
    1. 사용자가 구체적 명사(Target Item)를 찾을 때,
    2. 문서에 해당 명사가 '텍스트'로 존재하지 않으면,
    3. AI 유사도 점수가 아무리 높아도(0.95 미만) 가차 없이 탈락시킴.
       (TN 장비가 '교체' 유사성으로 끼어드는 것을 원천 봉쇄)
    """
    filtered = []
    
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    t_item = normalize_model_name(raw_t_item)
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general']
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        # 검색 대상 텍스트 통합 (내용 + 제목 + 항목명)
        d_content_full_raw = (
            d_mfr_raw + " " + d_model_raw + " " + d_item_raw + " " + 
            str(d.get('content') or '') + " " + str(d.get('solution') or '')
        ).lower()
        normalized_content = d_content_full_raw.replace(" ", "")

        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d_item_raw)
        
        # [V196] 하이브리드 검색(SQL)으로 찾은 문서는 이미 검증됨 (점수 > 0.98)
        similarity = d.get('similarity') or 0
        is_hybrid_hit = (similarity > 0.98)

        if strict_mode:
            # 1. [핵심] SQL 검증 로직 (SQL-Verification)
            # 타겟이 명확한데(채수펌프), 문서에 그 글자가 없고, SQL로 찾은 것도 아니라면?
            if is_specific_target and not is_hybrid_hit:
                if normalized_target not in normalized_content:
                    # [V196 강화] AI 유사도가 0.95(초고득점) 미만이면 무조건 탈락
                    # (기존 0.82 -> 0.95 상향: TN 장비 등이 여기서 다 걸러짐)
                    if similarity < 0.95:
                        continue 

            # 2. 아이템 카테고리 체크
            if is_specific_target:
                is_doc_common = any(k in d_item for k in generic_keywords) or d_item == ""
                # 하이브리드 히트면 카테고리 불일치도 넘어감 (키워드가 있으니까)
                if not is_doc_common and t_item not in d_item and d_item not in t_item and not is_hybrid_hit:
                    # 키워드 없으면 점수 0.95 미만 탈락
                    if similarity < 0.95: 
                        continue

            # 3. 모델명 방화벽
            if t_model != '미지정':
                is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""
                if not is_doc_model_common and d_model != '' and t_model not in d_model and d_model not in t_model and not is_hybrid_hit:
                     if similarity < 0.95:
                         continue

        score = similarity
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        # 키워드 가산점
        if is_specific_target and (raw_t_item.lower() in d_item_raw.lower() or raw_t_item.lower() in d_model_raw.lower()):
            score += 0.2

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    # (V195 오케스트레이션 유지 - V196 필터 적용)
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

    # 1단계: 엄격 모드 (V196 SQL 검증 필터 가동)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # 2단계: 결과 0건이면 유연 모드 (품질 점수 0.65 이상)
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
