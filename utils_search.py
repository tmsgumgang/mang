import time
import json
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

def normalize_model_name(text):
    """
    [V188] 모델명 완전 정규화 헬퍼 함수
    """
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    [V189] 데이터 출처 실명제(Source Identity) 오케스트레이터:
    검색 결과가 어느 테이블에서 왔는지 'source_table' 키로 명확히 마킹하여
    정보 교정 시 업데이트 실패(테이블 혼동)를 원천 차단함.
    """
    
    # 1. [V185] 초병렬 초기 진입
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    # [V184] Intent 안전장치
    if not intent or not isinstance(intent, dict):
        intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. [V183] 병렬 배치 필터링
    with ThreadPoolExecutor() as executor:
        future_blacklist = executor.submit(db.get_semantic_context_blacklist, q_vec)
        future_penalties = executor.submit(db.get_penalty_counts)
        
        context_blacklist = future_blacklist.result()
        penalties = future_penalties.result()

    # 3. [V183] 병렬 DB 조회
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # [V189 핵심] 데이터 출처 꼬리표(Tagging) 부착
    # 이제 시스템은 추측하지 않고 이 태그를 보고 업데이트할 테이블을 찾습니다.
    for r in m_res: r['source_table'] = 'manual_base'
    for r in k_res: r['source_table'] = 'knowledge_base'

    # 4. 후보군 압축 및 방화벽 가동
    raw_candidates = []
    
    # V188 정규화 로직 유지
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    t_model = normalize_model_name(intent.get('target_model') or '미지정')
    t_item = normalize_model_name(intent.get('target_item') or '공통')

    for d in (m_res + k_res):
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        if d.get('semantic_version') == 1:
            # 문서 메타데이터 정규화
            d_mfr = normalize_model_name(d.get('manufacturer') or '')
            d_model = normalize_model_name(d.get('model_name') or '')
            d_item = normalize_model_name(d.get('measurement_item') or '')
            
            # V187/188 방화벽 (Zero Tolerance)
            if t_model != '미지정' and d_model != '' and t_model not in d_model and d_model not in t_model:
                continue 
            if t_mfr != '미지정' and d_mfr != '' and t_mfr not in d_mfr:
                continue

            # 점수 계산
            score = (d.get('similarity') or 0)
            if t_item != '공통' and t_item != 'none' and t_item not in d_item:
                score -= 3.0
            
            score -= (penalties.get(u_key, 0) * 0.1)
            if d.get('is_verified'): score += 0.15
            
            raw_candidates.append({**d, 'final_score': score, 'u_key': u_key})
    
    # 상위 8개 선정
    raw_candidates = sorted(raw_candidates, key=lambda x: x['final_score'], reverse=True)[:8]
    
    # 5. [V186] 빠른 리랭킹
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
