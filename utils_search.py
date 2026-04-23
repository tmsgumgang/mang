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
    - [V248] 그래프가 소환한 원본 문서(점수 0.95)도 프리패스 권한 부여
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
        if d.get('semantic_version') != 1 and d.get('source_table') != 'knowledge_graph': # [V239] 그래프 데이터는 버전체크 패스
            if d.get('semantic_version') != 1 and d.get('semantic_version') != 2: # V237부터 semantic_version 2 사용함
                continue

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
        # [V248 NEW] 그래프가 소환한 문서는 점수가 0.95로 고정됨 -> 프리패스 대상
        is_graph_summon = (similarity == 0.95)

        # 문서가 '공통' 모델인지 확인
        is_doc_model_common = any(k in d_model_raw.lower() for k in generic_keywords) or d_model == ""

        if strict_mode:
            # ---------------------------------------------------------------
            # [V205 핵심] 키워드 히트(강제발굴) 데이터는 필터 검사를 면제
            # [V239 추가] 지식 그래프(knowledge_graph) 데이터도 면제 (유사도 0.99)
            # [V248 추가] 그래프 소환 문서(is_graph_summon)도 면제
            # ---------------------------------------------------------------
            if not is_keyword_hit and not is_graph_summon and d.get('source_table') != 'knowledge_graph':
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
    [V248] 4단 하이브리드 검색 (Graph + Vector + Metadata + Keyword)
    - 그래프에서 발견된 지식의 '원본 문서'를 강제 소환하여 결과에 포함 (Missing Link 해결)
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
    # [Step 0] 🕸️ 지식 그래프(Graph RAG) 동시 수색 & 원본 ID 확보 (V248 NEW)
    # -----------------------------------------------------------
    keywords = [k for k in user_q.split() if len(k) >= 2]
    if intent.get('target_item') and intent.get('target_item') != '공통':
        keywords.append(intent.get('target_item'))
    
    graph_docs = []
    # [V248] 원본 문서 ID를 추적하기 위한 집합
    graph_source_ids = {'manual': set(), 'knowledge': set()} 

    if keywords:
        graph_relations = []
        for kw in set(keywords):
            # db_services에 있는 그래프 검색 함수 호출
            rels = db.search_graph_relations(kw)
            if rels: graph_relations.extend(rels)
        
        # 중복 제거 및 원본 ID 추출
        if graph_relations:
            unique_graphs = []
            seen_graphs = set()
            for rel in graph_relations:
                # 1. 그래프 노드 데이터 저장
                g_key = f"{rel['source']}_{rel['relation']}_{rel['target']}"
                if g_key not in seen_graphs:
                    seen_graphs.add(g_key)
                    unique_graphs.append(rel)
                
                # 2. [V248 핵심] 원본 문서 ID 수집 (나중에 강제 소환)
                if rel.get('doc_id'):
                    s_type = rel.get('source_type', 'manual') # 기본값 manual
                    if s_type == 'knowledge': graph_source_ids['knowledge'].add(rel['doc_id'])
                    else: graph_source_ids['manual'].add(rel['doc_id'])
            
            # 그래프 데이터를 하나의 '가상 문서'로 압축
            if unique_graphs:
                graph_text = "💡 [Graph DB 인과관계 분석결과]\n"
                for rel in unique_graphs[:7]: # 너무 길어지지 않게 7개 제한
                    rel_type = rel['relation']
                    raw_label = REL_MAP.get(rel_type, rel_type)
                    rel_korean = raw_label.split(" (")[0]  # 괄호 설명 제거, 한국어 핵심만
                    
                    graph_text += f"- [{rel['source']}]는(은) [{rel['target']}]의 '{rel_korean}'.\n"

                graph_docs.append({
                    'id': 999999, # 임시 ID
                    'source_table': 'knowledge_graph',
                    'manufacturer': intent.get('target_mfr', '공통'),
                    'model_name': intent.get('target_model', '공통'),
                    'measurement_item': intent.get('target_item', '공통'),
                    'content': graph_text,
                    'similarity': 0.99, # 신뢰도 최상
                    'is_verified': True,
                    'semantic_version': 2
                })

    # -----------------------------------------------------------
    # [Step 1] 정밀 검색 (인덱스/필터 기반)
    # -----------------------------------------------------------
    with ThreadPoolExecutor() as executor:
        future_m = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, intent, user_q, context_blacklist)
        future_k = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, intent, user_q, context_blacklist)
        m_res = future_m.result()
        k_res = future_k.result()

    # -----------------------------------------------------------
    # [Step 1.5] 🎣 그래프 원본 문서 강제 소환 (V248 NEW)
    # -----------------------------------------------------------
    # 벡터 검색에서 놓쳤더라도, 그래프에 연결된 문서는 무조건 가져옵니다.
    summoned_docs = []
    
    # 매뉴얼 원본 소환
    if graph_source_ids['manual']:
        try:
            ids = list(graph_source_ids['manual'])[:5] # 너무 많으면 5개만
            res = db.supabase.table("manual_base").select("*").in_("id", ids).execute()
            if res.data:
                for d in res.data:
                    d['similarity'] = 0.95 # 높은 점수 부여 (그래프 증거물)
                    d['source_table'] = 'manual_base'
                    summoned_docs.append(d)
        except Exception as e: print(f"Manual Summon Error: {e}")

    # 지식 원본 소환
    if graph_source_ids['knowledge']:
        try:
            ids = list(graph_source_ids['knowledge'])[:5]
            res = db.supabase.table("knowledge_base").select("*").in_("id", ids).execute()
            if res.data:
                for d in res.data:
                    d['similarity'] = 0.95
                    d['source_table'] = 'knowledge_base'
                    summoned_docs.append(d)
        except Exception as e: print(f"Knowledge Summon Error: {e}")

    # 소환된 문서를 기존 결과에 병합
    m_res += summoned_docs 

    # -----------------------------------------------------------
    # [Step 2] 광범위 검색 (인덱스 무시, 벡터 유사도 기반)
    # -----------------------------------------------------------
    if len(m_res) + len(k_res) < 3:
        relaxed_intent = {"target_mfr": "미지정", "target_model": "미지정", "target_item": "공통"}
        with ThreadPoolExecutor() as executor:
            future_m_broad = executor.submit(db.match_filtered_db, "match_manual", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            future_k_broad = executor.submit(db.match_filtered_db, "match_knowledge", q_vec, effective_threshold, relaxed_intent, user_q, context_blacklist)
            m_res += future_m_broad.result()
            k_res += future_k_broad.result()

    # -----------------------------------------------------------
    # [Step 3] 키워드 강제 발굴 (최후의 보루)
    # -----------------------------------------------------------
    if len(m_res) + len(k_res) < 3:
        keyword_docs = db.search_keyword_fallback(user_q) 
        if keyword_docs:
            m_res += keyword_docs 

    # 4. 데이터 통합
    for r in m_res: 
        if 'source_table' not in r: r['source_table'] = 'manual_base'
    for r in k_res: 
        if 'source_table' not in r: r['source_table'] = 'knowledge_base'
    
    # [중요] 그래프 결과를 맨 앞에 배치
    combined_raw = graph_docs + m_res + k_res
    
    # ID 기반 중복 제거 (소환된 문서와 벡터 검색 문서가 겹칠 수 있음)
    all_docs = []
    seen_uids = set()
    for doc in combined_raw:
        uid = f"{doc.get('source_table')}_{doc['id']}"
        if uid not in seen_uids:
            seen_uids.add(uid)
            all_docs.append(doc)

    # 5. 필터링 및 리랭킹
    raw_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=True)
    
    if not raw_candidates:
        fallback_candidates = filter_candidates_logic(all_docs, intent, penalties, strict_mode=False)
        raw_candidates = [d for d in fallback_candidates if d['final_score'] > 0.65]

    # 최종 순위 결정 (LLM Rerank)
    final_results = quick_rerank_ai(ai_model, user_q, raw_candidates, intent)
    
    return final_results, intent, q_vec
