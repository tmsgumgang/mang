import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    """
    [V188] 모델명 정규화 헬퍼
    """
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V205] 필터링 로직 업데이트
    - 3단계 키워드 검색으로 발굴된 문서(점수 0.85)는 엄격한 필터링을 면제해주는 '프리패스' 권한 부여
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
    
    # 상호 배타적 메이저 카테고리
    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') != 1: continue

        # 2. 문서(Doc) 데이터 정규화
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        d_mfr = normalize_model_name(d_mfr_raw)
        d_model = normalize_model_name(d_model_raw)
        d_item = normalize_model_name(d_item_raw)
        
        similarity = d.get('similarity') or 0
        is_hybrid_hit = (similarity > 0.98) 
        
        # [NEW] 3단계 키워드 검색으로 찾은 문서는 점수가 0.85로 고정됨 -> 프리패스 대상
        is_keyword_hit = (similarity == 0.85)

        # 문서가 '공통' 모델인지 확인
        is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""

        if strict_mode:
            # ---------------------------------------------------------------
            # [V205 핵심] 키워드 히트(강제발굴) 데이터는 필터 검사를 면제
            # ---------------------------------------------------------------
            if not is_keyword_hit:
                # 1. 모델 독점 모드 체크
                if is_model_locked and not is_doc_model_common:
                    if d_model != '' and t_model not in d_model and d_model not in t_model:
                        continue 

                # 2. 카테고리 교차 검증
                if is_specific_target:
                    doc_identity = d_item_raw.lower() + " " + d_model_raw.lower()
                    is_identity_mismatch = False
                    for cat in major_categories:
                        if cat in doc_identity:
                            if cat not in raw_t_item.lower() and raw_t_item.lower() not in cat:
                                if not (('채수' in cat and '채수' in raw_t_item.lower()) or 
                                        ('펌프' in cat and '펌프' in raw_t_item.lower())):
                                    if not is_hybrid_hit:
                                        is_identity_mismatch = True
                                        break
                    if is_identity_mismatch: continue

                # 3. SQL 검증 및 키워드 확인
                # 타겟이 명확한데, 문서 내용에 그 단어가 없으면 탈락
                if is_specific_target and not is_hybrid_hit:
                    d_content_full = (d_mfr_raw + d_model_raw + d_item_raw + str(d.get('content') or '')).lower().replace(" ", "")
                    if normalized_target not in d_content_full:
                        if similarity < 0.95:
                            continue 

                # 4. 모델명 일반 방화벽
                if t_model != '미지정':
                    if not is_doc_model_common and d_model != '' and t_model not in d_model and d_model not in t_model and not is_hybrid_hit:
                        if similarity < 0.95:
                            continue

        score = similarity
        
        # 블랙리스트 감점
        score -= (penalties.get(u_key, 0) * 0.1)
        if d.get('is_verified'): score += 0.15
        
        # 타겟 모델 일치 시 가산점
        if is_model_locked and (t_model in d_model or d_model in t_model):
            score += 10.0 

        # 키워드 가산점
        if is_specific_target and (raw_t_item.lower() in d_item_raw.lower() or raw_t_item.lower() in d_model_raw.lower()):
            score += 0.2

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V205] 3단 순차 검색 프로토콜 (Triple-Safety Search)
    Step 1: AI Intent & Metadata Index Search (정밀)
    Step 2: Vector Similarity Search (광범위)
    Step 3: Keyword Text Search (강제 발굴 - Fallback)
    """
    # 1. 초기 진입 (병렬 처리)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    is_specific_search = (intent.get('target_item') != '공통') or (intent.get('target_model') != '미지정')
    effective_threshold = 0.2 if is_specific_search else u_threshold

    # 2. 메타데이터 조회 (병렬)
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # -----------------------------------------------------------
    # [Step 1] 정밀 검색 (인덱스/필터 기반)
    # -----------------------------------------------------------
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # -----------------------------------------------------------
    # [Step 2] 광범위 검색 (인덱스 무시, 벡터 유사도 기반)
    # -----------------------------------------------------------
    # 결과가 3개 미만이면, 필터를 떼고 내용만으로 다시 찾음
    if len(m_res) + len(k_res) < 3:
        # print("⚠️ 1단계 실패 -> 2단계 광범위 검색 가동")
        relaxed_intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        
        with ThreadPoolExecutor() as executor:
            future_m_broad = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            future_k_broad = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            
            # 리스트 확장
            m_res += future_m_broad.result()
            k_res += future_k_broad.result()

    # -----------------------------------------------------------
    # [Step 3] 키워드 강제 발굴 (최후의 보루 - Keyword Fallback)
    # -----------------------------------------------------------
    # 2단계까지 했는데도 결과가 영 시원찮으면(3개 미만), 텍스트 매칭으로 강제 수색
    if len(m_res) + len(k_res) < 3:
        # print("⚠️ 2단계 실패 -> 3단계 키워드 강제 수색 가동")
        # [NEW] db_services.py에 만든 함수 호출
        keyword_docs = db.search_keyword_fallback(user_q) 
        if keyword_docs:
            m_res += keyword_docs  # 결과에 강제 병합

    # 4. 데이터 통합 및 중복 제거
    # 출처 태깅
    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'
    
    combined_raw = m_res + k_res
    
    # ID 기반 중복 제거
    all_docs = []
    seen_uids = set()
    for doc in combined_raw:
        uid = f"{doc['source_table']}_{doc['id']}"
        if uid not in seen_uids:
            seen_uids.add(uid)
            all_docs.append(doc)

    # 5. 필터링 및 리랭킹
    # 1차 필터링 (엄격 모드)
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    # 결과가 없으면 유연 모드 (Fallback)
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    # 최종 순위 결정 (LLM Rerank)
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
