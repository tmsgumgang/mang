import streamlit as st
import time
import json
import re
from concurrent.futures import ThreadPoolExecutor
from logic_ai import *

# =============================================================================
# [Helper] 정규화 및 필터링
# =============================================================================
def normalize_model_name(text):
    if not text: return ""
    return str(text).lower().replace(" ", "").replace("-", "").replace("_", "")

def filter_candidates_logic(candidates, intent, penalties, strict_mode=True):
    """
    [V313] 필터링 로직 강화: 그래프 소환 문서(0.95)는 확실하게 프리패스
    """
    filtered = []
    
    # 1. Intent 정규화
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    raw_t_model = str(intent.get('target_model') or '미지정')
    t_model = normalize_model_name(raw_t_model)
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general', '기타']
    is_model_locked = (t_model not in generic_keywords) and (len(t_model) > 1)
    is_specific_target = (normalized_target not in generic_keywords) and (len(normalized_target) > 1)
    
    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        similarity = d.get('similarity') or 0
        
        # [핵심 수정] 0.94점 이상(소환된 문서)이면 무조건 통과 (검사 로직 건너뜀)
        is_force_pass = (similarity >= 0.94) or (d.get('source_table') == 'knowledge_graph')
        
        if is_force_pass:
            score = similarity
            if d.get('is_verified'): score += 0.15
            filtered.append({**d, 'final_score': score, 'u_key': u_key})
            continue # <--- 여기서 바로 다음 문서로! (검문 검색 생략)

        # ----------------------------------------------------------------
        # 아래는 일반 문서만 검사
        # ----------------------------------------------------------------
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        d_model = normalize_model_name(d_model_raw)
        is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""
        
        # 라벨링 일치 여부
        is_label_match = False
        if is_model_locked and d_model:
            if t_model in d_model or d_model in t_model:
                is_label_match = True

        if strict_mode:
            # 1. 모델명 불일치 차단
            if is_model_locked and not is_doc_model_common:
                if not is_label_match:
                     if d_model and (t_model not in d_model and d_model not in t_model):
                         if similarity < 0.80: continue 

            # 2. 카테고리 교차 검증
            if is_specific_target:
                doc_identity = d_item_raw.lower() + " " + d_model_raw.lower()
                is_identity_mismatch = False
                for cat in major_categories:
                    if cat in doc_identity:
                        if cat not in raw_t_item.lower() and raw_t_item.lower() not in cat:
                            if not (('채수' in cat and '채수' in raw_t_item.lower()) or 
                                    ('펌프' in cat and '펌프' in raw_t_item.lower())):
                                if not is_label_match and similarity < 0.85: 
                                    is_identity_mismatch = True
                                    break
                if is_identity_mismatch: continue

            # 3. 키워드 검증
            if is_specific_target:
                d_content_full = (d_mfr_raw + d_model_raw + d_item_raw + str(d.get('content') or '')).lower().replace(" ", "")
                if normalized_target not in d_content_full:
                    if not is_label_match:
                        if similarity < 0.75: continue 

        # 점수 계산
        score = similarity
        if d.get('is_verified'): score += 0.15
        if is_label_match: score += 0.3

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

# =============================================================================
# [Main] 통합 검색 오케스트레이터
# =============================================================================
def perform_unified_search(ai_model, db, user_q, u_threshold):
    # 1. 의도 분석 및 임베딩
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent: intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. [Graph RAG] 키워드 확장 및 그래프 검색 (여기가 핵심)
    # 기본 단어 분리
    keywords = set([k for k in user_q.split() if len(k) >= 2])
    
    # [수정] 모델명 및 하이픈 분리 단어 추가 (HAAS-4000 -> HAAS, 4000)
    if intent.get('target_model') and intent.get('target_model') != '미지정':
        t_model = intent.get('target_model').strip()
        keywords.add(t_model)
        if '-' in t_model:
            keywords.update(t_model.split('-'))
            
    graph_docs = []
    summon_ids = {'manual': set(), 'knowledge': set()} 

    if keywords:
        for kw in keywords:
            # DBManager에 함수가 있다고 가정
            if hasattr(db, 'search_graph_relations'):
                rels = db.search_graph_relations(kw)
                if rels:
                    for rel in rels:
                        content = f"[지식그래프] {rel['source']} --({rel['relation']})--> {rel['target']}"
                        graph_docs.append({
                            'id': f"g_{rel['id']}", 
                            'content': content, 
                            'source_table': 'knowledge_graph', 
                            'similarity': 0.99, 
                            'manufacturer': '지식그래프',
                            'model_name': '공통'
                        })
                        
                        # 원본 문서 ID 수집
                        if rel.get('doc_id'):
                            s_type = rel.get('source_type', 'manual') 
                            if s_type == 'knowledge': summon_ids['knowledge'].add(rel['doc_id'])
                            else: summon_ids['manual'].add(rel['doc_id'])

    # 3. 벡터 검색 실행
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, None)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, None)
        m_res = future_m.result()
        k_res = future_k.result()

    # 3.5 [Summoning] 원본 문서 강제 소환 (Step 1.5)
    summoned_docs = []
    
    # (1) 매뉴얼 소환
    if summon_ids['manual']:
        try:
            ids = list(summon_ids['manual'])[:5]
            # 안전하게 db.supabase 호출
            res = db.supabase.table("manual_base").select("*").in_("id", ids).execute()
            if res.data:
                for d in res.data:
                    d['similarity'] = 0.95 # [면책 특권 점수]
                    d['source_table'] = 'manual_base'
                    summoned_docs.append(d)
        except Exception: pass

    # (2) 지식노트 소환
    if summon_ids['knowledge']:
        try:
            ids = list(summon_ids['knowledge'])[:5]
            res = db.supabase.table("knowledge_base").select("*").in_("id", ids).execute()
            if res.data:
                for d in res.data:
                    d['similarity'] = 0.95 # [면책 특권 점수]
                    d['source_table'] = 'knowledge_base'
                    summoned_docs.append(d)
        except Exception: pass

    # 소환된 문서를 결과에 추가
    m_res += summoned_docs

    # 4. 결과 통합
    raw_results = summoned_docs + m_res + k_res # 소환된 놈이 우선
    enriched_results = []
    
    # 5. 메타데이터 보강
    for r in raw_results:
        if not r.get('manufacturer') or not r.get('model_name'):
            source = r.get('source_table', 'manual_base')
            if hasattr(db, 'get_doc_metadata_by_id'):
                meta = db.get_doc_metadata_by_id(r['id'], 'knowledge' if source == 'knowledge_base' else 'manual')
                if meta:
                    r['manufacturer'] = meta.get('manufacturer', '미지정')
                    r['model_name'] = meta.get('model_name', '공통')
                    r['measurement_item'] = meta.get('measurement_item', '공통')
        enriched_results.append(r)

    # 6. 중복 제거
    final_pool = graph_docs[:3] + enriched_results 
    unique_pool = []
    seen_ids = set()
    for d in final_pool:
        uid = f"{d.get('source_table')}_{d.get('id')}"
        if uid not in seen_ids:
            seen_ids.add(uid)
            unique_pool.append(d)

    # 7. 필터링 및 리랭킹
    filtered_candidates = filter_candidates_logic(unique_pool, intent, {}, strict_mode=True)
    
    if len(filtered_candidates) < 2:
        fallback_candidates = filter_candidates_logic(unique_pool, intent, {}, strict_mode=False)
        existing_ids = {f"{c.get('source_table')}_{c['id']}" for c in filtered_candidates}
        for fc in fallback_candidates:
            fid = f"{fc.get('source_table')}_{fc['id']}"
            if fid not in existing_ids:
                filtered_candidates.append(fc)

    ranked_results = quick_rerank_ai(ai_model, user_q, filtered_candidates, intent)
    
    return ranked_results, intent, q_vec
