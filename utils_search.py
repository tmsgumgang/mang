import streamlit as st
import time
import json
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
    [V309] 필터링 로직: Graph RAG 소환 문서 & 라벨링 일치 문서 보호 정책
    - 그래프가 소환한 문서(유사도 0.95)는 무조건 통과
    - 모델명이 일치하는 문서는 키워드가 없어도 통과
    """
    filtered = []
    
    # 1. Intent 정규화
    t_mfr = normalize_model_name(intent.get('target_mfr') or '미지정')
    raw_t_model = str(intent.get('target_model') or '미지정')
    t_model = normalize_model_name(raw_t_model)
    
    raw_t_item = str(intent.get('target_item') or '공통').strip()
    normalized_target = raw_t_item.replace(" ", "").lower()
    t_item = normalize_model_name(raw_t_item)
    
    generic_keywords = ['공통', '미지정', '알수없음', 'none', 'general', '기타']
    is_model_locked = (t_model not in generic_keywords) and (len(t_model) > 1)
    is_specific_target = (t_item not in generic_keywords) and (len(t_item) > 1)
    
    major_categories = ['tn', 'tp', 'toc', 'cod', 'ph', 'ss', '채수펌프', '채수기']

    for d in candidates:
        u_key = f"{'EXP' if 'solution' in d else 'MAN'}_{d.get('id')}"
        
        # [과거 지능 복원] 그래프가 소환한 문서(0.95)나 그래프 자체(0.90~0.99)는 프리패스
        similarity = d.get('similarity') or 0
        is_force_pass = (similarity >= 0.85) or (d.get('source_table') == 'knowledge_graph')

        # 2. 문서 데이터 정규화
        d_mfr_raw = str(d.get('manufacturer') or '')
        d_model_raw = str(d.get('model_name') or '')
        d_item_raw = str(d.get('measurement_item') or '')
        
        d_model = normalize_model_name(d_model_raw)
        
        # 문서가 '공통' 모델인지 확인
        is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""
        
        # [V305 유지] 라벨링 일치 여부 판단 (생존권 부여)
        is_label_match = False
        if is_model_locked and d_model:
            # 질문한 모델명(HAAS-4000)이 문서 모델명에 포함되면 라벨 일치로 간주
            if t_model in d_model or d_model in t_model:
                is_label_match = True

        if strict_mode and not is_force_pass:
            # 1. 모델 독점 모드 체크
            if is_model_locked and not is_doc_model_common:
                # 모델명이 다르고, 라벨링 매치도 아니면 탈락
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
                                # 라벨링이 일치하면 카테고리가 좀 달라도 봐줌
                                if not is_label_match and similarity < 0.85: 
                                    is_identity_mismatch = True
                                    break
                if is_identity_mismatch: continue

            # 3. 키워드 검증 (유연화)
            if is_specific_target:
                d_content_full = (d_mfr_raw + d_model_raw + d_item_raw + str(d.get('content') or '')).lower().replace(" ", "")
                if normalized_target not in d_content_full:
                    # 라벨이 일치하면 키워드가 없어도 통과!
                    if not is_label_match:
                        if similarity < 0.75: continue 

        # 점수 계산 및 포맷팅
        score = similarity
        if d.get('is_verified'): score += 0.15
        
        # 모델명 일치 시 가산점
        if is_label_match:
            score += 0.3

        filtered.append({**d, 'final_score': score, 'u_key': u_key})
        
    return sorted(filtered, key=lambda x: x['final_score'], reverse=True)[:8]

# =============================================================================
# [Main] 통합 검색 오케스트레이터
# =============================================================================
def perform_unified_search(ai_model, db, user_q, u_threshold):
    """
    1. [Vector] 임베딩 검색
    2. [Graph RAG] 그래프 관계 검색 및 **원본 문서 강제 소환(Summon)**
    3. [Labeling] 메타데이터(제조사/모델) 강제 주입
    4. [Rerank] AI 재순위 산정
    """
    
    # 1. 의도 분석 및 임베딩 (병렬)
    with ThreadPoolExecutor() as executor:
        future_vec = executor.submit(get_embedding, user_q)
        future_intent = executor.submit(analyze_search_intent, ai_model, user_q)
        q_vec = future_vec.result()
        intent = future_intent.result()
    
    if not intent: intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}

    # 2. DB 검색 실행 (Vector Search)
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, u_threshold, intent, user_q, None)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, u_threshold, intent, user_q, None)
        m_res = future_m.result()
        k_res = future_k.result()

    # 3. [Graph RAG] 그래프 지식 검색 & 원본 소환 (핵심 복구)
    keywords = [k for k in user_q.split() if len(k) >= 2]
    graph_docs = []
    
    # 원본 문서 ID를 수집할 저장소 (중복 방지)
    summon_ids = {'manual': set(), 'knowledge': set()}
    
    if keywords:
        for kw in set(keywords):
            rels = db.search_graph_relations(kw)
            if rels:
                for rel in rels:
                    # A. 그래프 텍스트 생성
                    content = f"[지식그래프] {rel['source']} --({rel['relation']})--> {rel['target']}"
                    graph_docs.append({
                        'id': f"g_{rel['id']}", 
                        'content': content, 
                        'source_table': 'knowledge_graph', 
                        'similarity': 0.90, # 그래프 자체 점수
                        'manufacturer': '지식그래프',
                        'model_name': '공통'
                    })
                    
                    # B. [과거 지능 복원] 원본 문서 ID 수집 (Source Tracking)
                    if rel.get('doc_id'):
                        # source_type 필드가 없으면 기본적으로 manual로 가정
                        s_type = rel.get('source_type', 'manual') 
                        if s_type == 'knowledge': summon_ids['knowledge'].add(rel['doc_id'])
                        else: summon_ids['manual'].add(rel['doc_id'])

    # 3.5 [Summoning] 수집된 ID로 원본 문서 강제 조회 (Vector 검색 실패 보완)
    summoned_docs = []
    
    # (1) 매뉴얼 소환
    if summon_ids['manual']:
        try:
            ids = list(summon_ids['manual'])[:5] # 너무 많으면 상위 5개만
            res = db.supabase.table("manual_base").select("*").in_("id", ids).execute()
            if res.data:
                for d in res.data:
                    d['similarity'] = 0.95 # [면책 특권] 그래프 보증수표 점수 부여
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
                    d['similarity'] = 0.95 # [면책 특권]
                    d['source_table'] = 'knowledge_base'
                    summoned_docs.append(d)
        except Exception: pass

    # 4. 결과 통합 (그래프 + 소환된 문서 + 벡터 검색 결과)
    # 소환된 문서를 벡터 결과보다 앞에 배치하여 우선순위 확보
    raw_results = summoned_docs + m_res + k_res
    enriched_results = []
    
    # 5. [Labeling] 메타데이터 강제 주입
    for r in raw_results:
        # 이미 있으면 패스, 없으면 채워넣기
        if not r.get('manufacturer') or not r.get('model_name'):
            source = r.get('source_table', 'manual_base')
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
    # Strict 모드로 하되, summoned_docs(0.95)는 통과됨
    filtered_candidates = filter_candidates_logic(unique_pool, intent, {}, strict_mode=True)
    
    # 결과 부족 시 완화
    if len(filtered_candidates) < 2:
        fallback_candidates = filter_candidates_logic(unique_pool, intent, {}, strict_mode=False)
        existing_ids = {f"{c.get('source_table')}_{c['id']}" for c in filtered_candidates}
        for fc in fallback_candidates:
            fid = f"{fc.get('source_table')}_{fc['id']}"
            if fid not in existing_ids:
                filtered_candidates.append(fc)

    ranked_results = quick_rerank_ai(ai_model, user_q, filtered_candidates, intent)
    
    return ranked_results, intent, q_vec
