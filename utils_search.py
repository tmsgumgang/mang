import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V191] 명사 우선 법칙(Noun-First) 필터링 로직:
    1. 항목(Item) 불일치 시 감점이 아니라 '즉시 차단' (Strict Mode)
    2. 타겟 명사(Target Item)가 문서 내용에 없으면 '키워드 앵커링' 실패로 차단
    """
    filtered = []
    
    # 의도(Target) 정규화
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    
    # [V191] 타겟 항목은 정규화하되, 키워드 검색을 위해 원본도 유지
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    t_item = normalize_model_name(raw_t_item)
    
    # '공통'으로 간주할 키워드 목록
    safe_keywords = ['공통', 'general', 'common', 'none', 'unknown', '미지정', '미분류', '기타']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        # 문서(Doc) 정규화
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_content_raw = (str(d.get('content') or '') + str(d.get('solution') or '')).lower()
        
        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d.get('measurement_item') or '')
        
        is_common_doc = any(k in d_model_raw.lower() for k in safe_keywords) or (d_model == "")
        
        # --- [V191 강화된 방화벽 로직] ---
        if strict_mode:
            # 1. 모델명 방화벽 (기존 유지)
            if t_model != '미지정' and not is_common_doc:
                if d_model != '' and t_model not in d_model and d_model not in t_model:
                    continue
            
            # 2. 제조사 방화벽 (기존 유지)
            if t_mfr != '미지정':
                is_common_mfr = any(k in d_mfr_raw.lower() for k in safe_keywords)
                if d_mfr != '' and not is_common_mfr and t_mfr not in d_mfr:
                    continue
            
            # 3. [V191 핵심] 항목(Item) 방화벽: 감점이 아니라 '즉시 차단'으로 변경
            # 조건: 사용자가 명확한 항목(예: 채수펌프)을 요구했고, 문서도 명확한 다른 항목(예: TN)을 가질 때
            if t_item != '공통' and t_item != 'none' and t_item != '미지정':
                 is_doc_item_common = any(k in d_item for k in safe_keywords) or d_item == ""
                 # 문서 항목이 공통이 아니고, 타겟 항목과 전혀 겹치지 않으면 탈락
                 if not is_doc_item_common and t_item not in d_item and d_item not in t_item:
                     continue
            
            # 4. [V191 핵심] 키워드 앵커링 (Content Check)
            # 조건: 타겟 항목(예: 채수펌프)이 정해져 있는데, 문서 내용 어디에도 그 단어가 없다면 탈락
            # (단, 문서 모델명이나 항목명에 포함되어 있으면 통과)
            if t_item != '공통' and t_item != 'none' and t_item != '미지정':
                 keyword_found = (raw_t_item in d_content_raw) or (t_item in d_item) or (t_item in d_model)
                 if not keyword_found:
                     continue

        # --- [점수 계산] ---
        score = (d.get('similarity') or 0)
        
        # 블랙리스트 감점
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        if is_common_doc and t_model != '미지정':
            score -= 0.5 

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V191] 명사 우선 법칙 오케스트레이터:
    엄격 모드에서 항목(Item) 불일치 문서를 철저히 배제하고,
    검색 결과가 없을 때만 유연 모드로 전환하여 '관련성 없는 문서'의 난입을 막음.
    """
    # 1. 초기 진입 (병렬)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. 배치 필터링 및 DB 조회 (병렬)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    all_docs = m_res + k_res

    # 3. [V191] 2단계 필터링 (Fallback Strategy)
    # Step 1: 엄격 모드 (Strict) - 항목 불일치 및 키워드 미포함 문서 즉시 차단
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # Step 2: 결과가 0건이면 유연 모드 (Relaxed)
    if not raw_candidates:
        raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)

    # 4. 빠른 리랭킹
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
