import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    # (기존 로직 유지)
    filtered = []
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    t_item = normalize_model_name(raw_t_item)
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general']
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)

    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        d_content_full_raw = (d_mfr_raw + " " + d_model_raw + " " + d_item_raw + " " + str(d.get('content') or '') + " " + str(d.get('solution') or '')).lower()
        normalized_content = d_content_full_raw.replace(" ", "")

        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d_item_raw)
        
        similarity = d.get('similarity') or 0
        is_hybrid_hit = (similarity > 0.98) # SQL로 강제 소환된 녀석

        if strict_mode:
            # 카테고리 교차 검증 (V197)
            if is_specific_target:
                doc_identity = d_item_raw.lower() + " " + d_model_raw.lower()
                is_identity_mismatch = False
                for cat in major_categories:
                    if cat in doc_identity:
                        # 타겟 키워드와 다르면 차단 (단, 하이브리드 히트는 봐줌 -> SQL이 찾았으면 이유가 있겠지)
                        if cat not in raw_t_item.lower() and raw_t_item.lower() not in cat:
                             if not (('채수' in cat and '채수' in raw_t_item.lower()) or ('펌프' in cat and '펌프' in raw_t_item.lower())):
                                 # [V198 수정] SQL이 명시적으로 찾은 건 살려둠 (잘못된 분류일 수 있으므로)
                                 if not is_hybrid_hit:
                                     is_identity_mismatch = True
                                     break
                if is_identity_mismatch: continue

            # SQL 검증 및 키워드 확인
            if is_specific_target:
                # [V198 수정] 하이브리드 히트면 키워드 검사 패스 (이미 SQL이 확인했음)
                if not is_hybrid_hit:
                    if normalized_target not in normalized_content:
                        if similarity < 0.95:
                            continue 

            # 모델명 방화벽
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
    # (V197과 동일, 파일 전체 교체 권장)
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

    # 1단계: 엄격 모드 (V198 필터 - 하이브리드 히트 우대 강화)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # 2단계: 결과 0건이면 유연 모드
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
