import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V192] 키워드 스나이핑(Keyword Sniping) 필터링:
    1. 사용자가 찾는 핵심 명사(Item)가 문서에 '텍스트'로 존재하지 않으면 무조건 탈락.
    2. '공통' 문서라도 핵심 명사가 없으면 탈락 (면책 특권 폐지).
    3. 명사 일치 여부를 최우선으로 판단.
    """
    filtered = []
    
    # 의도(Target) 분석
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    
    # [V192] 핵심 키워드(Raw) 확보
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    t_item = normalize_model_name(raw_t_item)
    
    # 제외할 무의미한 키워드 (이게 타겟이면 키워드 검증 스킵)
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general']
    
    # 타겟 아이템이 유효한 구체적 명사인지 확인
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        # 문서 데이터 준비
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        # 검색 대상 텍스트 통합 (내용 + 제목 + 항목명)
        d_content_full = (
            d_mfr_raw + " " + 
            d_model_raw + " " + 
            d_item_raw + " " + 
            str(d.get('content') or '') + " " + 
            str(d.get('solution') or '')
        ).lower()

        # 정규화된 메타데이터
        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d_item_raw)
        
        # --- [V192 강력한 방화벽] ---
        if strict_mode:
            # 1. [핵심] 키워드 스나이핑 (Keyword Sniping)
            # 사용자가 구체적인 명사(예: 채수펌프)를 찾는데, 문서 전체에 그 단어가 없으면 탈락
            if is_specific_target:
                # 띄어쓰기 무시하고 포함 여부 확인 (채수 펌프 vs 채수펌프)
                normalized_target = raw_t_item.replace(" ", "").lower()
                normalized_content = d_content_full.replace(" ", "")
                
                if normalized_target not in normalized_content:
                    continue # [즉시 차단] 내용에 '채수펌프' 글자 없으면 집에 가라.

            # 2. 아이템(Item) 카테고리 불일치 차단
            # 문서가 명확히 다른 아이템(예: TN)으로 분류되어 있으면 탈락
            if is_specific_target:
                is_doc_common = any(k in d_item for k in generic_keywords) or d_item == ""
                if not is_doc_common and t_item not in d_item and d_item not in t_item:
                    continue

            # 3. 모델명 방화벽 (기존 유지)
            # 단, 키워드 스나이핑을 통과했다면 모델명은 조금 관대해도 됨 (부품일 수 있으므로)
            if t_model != '미지정':
                is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""
                if not is_doc_model_common and d_model != '' and t_model not in d_model and d_model not in t_model:
                     continue

        # --- [점수 계산] ---
        score = (d.get('similarity') or 0)
        
        # 블랙리스트 감점
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        # [V192] 타겟 키워드가 제목/메타데이터에 있으면 가산점 (내용에만 있는 것보다 우대)
        if is_specific_target and (raw_t_item.lower() in d_item_raw.lower() or raw_t_item.lower() in d_model_raw.lower()):
            score += 0.2

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V192] 키워드 스나이핑 오케스트레이터:
    1차 검색에서 사용자가 입력한 핵심 명사가 포함되지 않은 문서는 
    '벡터 유사도'가 아무리 높아도(동사가 맞아도) 절대 가져오지 않음.
    """
    # 1. 초기 진입
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. 배치 필터링
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # 3. DB 조회 (출처 태깅 포함)
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    all_docs = m_res + k_res

    # 4. [V192] 2단계 필터링 (Fallback Strategy)
    # Step 1: 엄격 모드 - 키워드 스나이핑 가동 (채수펌프 없으면 0건 나옴)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # Step 2: 결과가 0건이면 유연 모드 (혹시 오타일 수 있으니)
    if not raw_candidates:
        # 단, 유연 모드에서도 너무 뚱딴지같은 건 빼기 위해 점수컷을 높임
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.4]

    # 5. 빠른 리랭킹
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
