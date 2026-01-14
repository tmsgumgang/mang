import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    """
    [V188] 모델명 정규화 헬퍼
    공백, 하이픈, 언더바를 제거하여 비교 (예: TOC-4200 == toc4200)
    """
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V201] 모델 독점 모드(Model Exclusive Lock) 필터링 로직:
    1. 사용자가 특정 모델(예: TOC-4200)을 지목하면 '독점 모드'가 켜짐.
    2. 독점 모드에서는 문서의 모델명이 타겟과 다르거나 '공통'이 아니면,
       내용 유사도(Vector Score)가 아무리 높아도 무조건 탈락시킴. (HAAS 차단 핵심)
    3. 타겟 모델과 정확히 일치하는 문서는 +10점 가산점으로 최상단 고정.
    """
    filtered = []
    
    # 1. Intent(의도) 데이터 정규화
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    raw_t_model = str(intent.get('target_model') or '미지정')
    t_model = normalize_model_name(raw_t_model)
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    t_item = normalize_model_name(raw_t_item)
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general', '기타']
    
    # 모델명이 특정되었는지 확인 (독점 모드 트리거 조건)
    is_model_locked = (t_model not in generic_keywords) and (len(t_model) > 1)
    
    # 아이템명이 특정되었는지 확인
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)
    
    # 상호 배타적 메이저 카테고리 (섞이면 안 되는 장비들)
    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        # 2. 문서(Doc) 데이터 정규화
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
        
        similarity = d.get('similarity') or 0
        is_hybrid_hit = (similarity > 0.98) # V195: SQL 키워드로 강제 소환된 문서

        # 문서가 '공통' 모델인지 확인 (빈 문자열 포함)
        is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""

        if strict_mode:
            # ---------------------------------------------------------------
            # [V201 핵심] 모델 독점 모드 (Model Exclusive Lock)
            # 조건: 사용자가 모델을 특정했고(TOC-4200), 문서 모델이 '공통'이 아닐 때
            # ---------------------------------------------------------------
            if is_model_locked and not is_doc_model_common:
                # 문서 모델명과 타겟 모델명이 다르면? (부분 포함도 안 되면)
                if d_model != '' and t_model not in d_model and d_model not in t_model:
                    # [V201 결단] 유사도 점수 확인 로직 삭제 -> 무조건 차단 (Hard Reject)
                    continue 

            # [V197] 카테고리 교차 검증 (Category Cross-Check)
            if is_specific_target:
                doc_identity = d_item_raw.lower() + " " + d_model_raw.lower()
                is_identity_mismatch = False
                for cat in major_categories:
                    if cat in doc_identity:
                        # 타겟 키워드와 다르면 차단 (예: TN 문서는 채수펌프 검색 시 차단)
                        if cat not in raw_t_item.lower() and raw_t_item.lower() not in cat:
                             # 예외: '채수'와 '채수기' 등 유의어는 허용
                             if not (('채수' in cat and '채수' in raw_t_item.lower()) or 
                                     ('펌프' in cat and '펌프' in raw_t_item.lower())):
                                 # 단, SQL이 명시적으로 찾은 건(Hybrid Hit) 분류 오류 가능성 있으므로 살려둠
                                 if not is_hybrid_hit:
                                     is_identity_mismatch = True
                                     break
                if is_identity_mismatch: continue

            # [V198] SQL 검증 및 키워드 확인
            # 타겟이 명확한데, 문서에 그 단어가 없고, SQL로 찾은 것도 아니면 차단
            if is_specific_target and not is_hybrid_hit:
                if normalized_target not in normalized_content:
                    # 점수가 아주 높지 않으면(0.95 미만) 탈락
                    if similarity < 0.95:
                        continue 

            # [V196] 모델명 일반 방화벽 (독점 모드 외의 일반적인 모델명 불일치 체크)
            if t_model != '미지정':
                if not is_doc_model_common and d_model != '' and t_model not in d_model and d_model not in t_model and not is_hybrid_hit:
                      if similarity < 0.95:
                          continue

        score = similarity
        
        # 블랙리스트 감점
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        # ---------------------------------------------------------------
        # [V201 핵심] 타겟 모델 일치 시 강력한 부스트 (Target Boost)
        # TOC-4200을 찾으면, TOC-4200 문서에 +10점을 줘서 무조건 1등으로 만듦
        # ---------------------------------------------------------------
        if is_model_locked and (t_model in d_model or d_model in t_model):
            score += 10.0 

        # 키워드 가산점
        if is_specific_target and (raw_t_item.lower() in d_item_raw.lower() or raw_t_item.lower() in d_model_raw.lower()):
            score += 0.2

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V202] 2단 그물망 통합 검색 오케스트레이터
    1. 1단계: 의도(Intent) 기반 정밀 검색 (기존 V201)
    2. 2단계: 결과 부족 시(3건 미만), 의도 필터 해제 후 광범위 검색 (Fallback)
    3. 중복 제거 및 최종 리랭킹
    """
    # 1. 초기 진입 (병렬 처리)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # [V194] 임계값 동적 조절: 구체적 검색 시 문턱을 낮춰서(0.2) 데이터를 많이 가져옴
    is_specific_search = (intent.get('target_item') != '공통') or (intent.get('target_model') != '미지정')
    effective_threshold = 0.2 if is_specific_search else u_threshold

    # 2. 메타데이터 조회 (병렬)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # 3. [Step 1] DB 조회 (정밀 검색 - Intent 필터 적용)
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # 4. [Step 2] 결과 부족 시 광범위 검색 (Fallback Strategy)
    # 정밀 검색 결과가 3개 미만이면, 라벨이 없거나 불분명한 문서를 찾기 위해 필터 해제
    if len(m_res) + len(k_res) < 3:
        # print("⚠️ 1단계 검색 결과 부족 -> 2단계 광범위 검색 가동")
        relaxed_intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        
        with ThreadPoolExecutor() as executor:
            # 의도가 제거된 relaxed_intent로 다시 검색 (순수 벡터 유사도 위주)
            future_m_broad = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            future_k_broad = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            m_res_broad = future_m_broad.result()
            k_res_broad = future_k_broad.result()
            
        # 결과 합치기
        m_res = m_res + m_res_broad
        k_res = k_res + k_res_broad

    # 5. 데이터 통합 및 중복 제거
    # 출처 태깅
    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    combined_raw = m_res + k_res
    
    # ID 기반 중복 제거 (정밀 검색과 광범위 검색에서 중복된 문서 제거)
    all_docs = []
    seen_uids = set()
    for doc in combined_raw:
        # manual_1과 knowledge_1은 다르므로 출처+ID로 구분
        uid = f"{doc['source_table']}_{doc['id']}"
        if uid not in seen_uids:
            seen_uids.add(uid)
            all_docs.append(doc)

    # 6. [V201] 1단계: 엄격 모드 (모델 독점 필터 가동)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # 7. 2단계: 결과 0건이면 유연 모드 (Fallback)
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        # 너무 낮은 점수는 제외
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    # 8. 최종 리랭킹
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
