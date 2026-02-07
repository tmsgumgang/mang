from collections import Counter
import re

class DBKnowledge:
    """
    [Core Brain] 챗봇의 지능, 지식 검색, RAG, 메타데이터 조회를 담당합니다.
    V309: HAAS-4000 같은 모델명 검색 누락 방지 및 Graph RAG 기능 완벽 복구
    """
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # =========================================================
    # [Helper] 데이터 정규화
    # =========================================================
    def _normalize_tags(self, raw_tags):
        if not raw_tags or str(raw_tags).lower() in ['none', 'nan', 'null']:
            return "공통"
        tags = [t.strip() for t in str(raw_tags).split(',')]
        seen = set()
        clean_tags = []
        for tag in tags:
            if tag and tag not in seen:
                clean_tags.append(tag)
                seen.add(tag)
        return ", ".join(clean_tags) if clean_tags else "공통"

    def _clean_text(self, text):
        if not text or str(text).lower() in ['none', 'nan', 'null', '미지정']:
            return "미지정"
        return str(text).strip()

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    # =========================================================
    # [Core] 검색 알고리즘 (지능 핵심)
    # =========================================================
    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    def get_semantic_context_blacklist(self, query_vec):
        try:
            res = self.supabase.rpc("match_relevance_feedback_batch", {
                "input_embedding": query_vec, "match_threshold": 0.95
            }).execute()
            if res.data:
                return {(item['table_name'], item['doc_id']) for item in res.data if item['relevance_score'] < 0}
            return set()
        except: return set()

    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        """
        [V309 핵심 수정] 검색어 조합 로직 강화
        - 의도(Intent) 분석 결과와 별개로, 사용자가 입력한 핵심 키워드(모델명 등)를 
          DB에서 직접 검색(OR 조건)하여 누락을 방지합니다.
        """
        try:
            # 1. Vector Search (임베딩 검색)
            vector_results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            # 2. Keyword Search (키워드 강제 소환)
            search_candidates = set()
            
            # (1) 의도된 타겟 모델명/항목 추가
            if intent.get('target_model') and intent['target_model'] not in ['미지정', '공통', 'none']:
                search_candidates.add(intent['target_model'].strip())
            if intent.get('target_item') and intent['target_item'] not in ['미지정', '공통', 'none']:
                search_candidates.add(intent['target_item'].strip())
                
            # (2) [복구된 로직] 사용자 질문의 핵심 단어 추출 (모델명 누락 방지)
            clean_q = re.sub(r'[^\w\s-]', ' ', query_text)
            words = clean_q.split()
            ignore_words = ['알려줘', '어떻게', '교체', '방법', '준비물', '해줘', '있어', '나요', '인가요', '늘리는', '법', '조절']
            
            for w in words:
                if len(w) >= 2 and w not in ignore_words:
                    search_candidates.add(w)
            
            keyword_results = []
            if search_candidates:
                t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"
                
                # 핵심 키워드(최대 5개)에 대해 DB 직접 검색
                for kw in list(search_candidates)[:5]:
                    if not kw: continue
                    try:
                        # 모델명, 항목, 내용 어디든 포함되면 가져옴
                        or_filter = f"model_name.ilike.%{kw}%,measurement_item.ilike.%{kw}%,content.ilike.%{kw}%"
                        if t_name == "knowledge_base":
                             or_filter = f"model_name.ilike.%{kw}%,measurement_item.ilike.%{kw}%,issue.ilike.%{kw}%,solution.ilike.%{kw}%"
                        
                        # 상위 10개만 조회 (속도 최적화)
                        res = self.supabase.table(t_name).select("*").or_(or_filter).limit(10).execute()
                        if res.data:
                            for d in res.data:
                                d['similarity'] = 0.99 # 키워드로 찾은 건 신뢰도 최상
                                keyword_results.append(d)
                    except: continue

            # 3. 결과 병합 (Vector + Keyword)
            merged_map = {}
            for d in vector_results: merged_map[d['id']] = d
            for d in keyword_results: merged_map[d['id']] = d 
                
            final_results_list = list(merged_map.values())
            filtered_results = []
            
            # 4. 점수 보정 (Re-scoring)
            keywords_list = [k.lower() for k in query_text.split() if len(k) > 1]
            t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"

            for d in final_results_list:
                if context_blacklist and (t_name, d['id']) in context_blacklist: continue
                
                final_score = d.get('similarity') or 0
                doc_full_text = (str(d.get('manufacturer','')) + str(d.get('model_name','')) + str(d.get('content','') or d.get('solution',''))).lower()
                
                for kw in keywords_list:
                    if kw in doc_full_text: final_score += 0.05
                    # [중요] 모델명에 키워드가 있으면 강력한 가산점 (HAAS-4000 구출)
                    if kw in str(d.get('model_name','')).lower(): final_score += 0.2
                
                d['similarity'] = min(final_score, 1.0)
                filtered_results.append(d)
                
            return filtered_results
        except Exception as e:
            print(f"DB Search Error: {e}")
            return []

    # -------------------------------------------------------------------------
    # [Step 3] 구원투수: 키워드 폴백 (utils_search.py에서 호출됨)
    # -------------------------------------------------------------------------
    def search_keyword_fallback(self, query_text):
        """[비상용] 모든 검색 실패 시 가장 긴 단어(모델명 추정)로 전수 조사"""
        keywords = [k for k in query_text.split() if len(k) >= 2]
        if not keywords: return []
        
        target_keyword = max(keywords, key=len)
        try:
            # 매뉴얼뿐만 아니라 지식노트까지 확장 검색하면 더 좋지만, 
            # 일단 사용자님의 원본 코드대로 매뉴얼 우선 검색을 유지합니다.
            res = self.supabase.table("manual_base").select("*").or_(f"content.ilike.%{target_keyword}%,model_name.ilike.%{target_keyword}%").limit(5).execute()
            docs = res.data
            for d in docs: 
                d['similarity'] = 0.98  # 면책 특권 점수 부여
                d['source_table'] = 'manual_base'
                d['is_verified'] = False 
            return docs
        except: return []

    # =========================================================
    # [Knowledge Graph] 지식 그래프 (utils_search.py 등에서 호출됨)
    # =========================================================
    def save_knowledge_triples(self, doc_id, triples):
        if not triples: return False
        try:
            data = []
            for t in triples:
                if t.get('source') and t.get('target'):
                    data.append({"source": self._clean_text(t['source']), "relation": t.get('relation', 'related_to'), "target": self._clean_text(t['target']), "doc_id": doc_id})
            if data: self.supabase.table("knowledge_graph").insert(data).execute(); return True
            return False
        except: return False

    def search_graph_relations(self, keyword):
        try: return self.supabase.table("knowledge_graph").select("*").or_(f"source.ilike.%{keyword}%,target.ilike.%{keyword}%").limit(20).execute().data
        except: return []

    def update_graph_triple(self, rel_id, new_source, new_relation, new_target):
        try:
            payload = {"source": self._clean_text(new_source), "relation": new_relation, "target": self._clean_text(new_target)}
            res = self.supabase.table("knowledge_graph").update(payload).eq("id", rel_id).execute()
            return True if res.data else False
        except: return False

    def delete_graph_triple(self, rel_id):
        try: self.supabase.table("knowledge_graph").delete().eq("id", rel_id).execute(); return True
        except: return False

    def bulk_rename_graph_node(self, old_name, new_name, target_scope="all"):
        try:
            count = 0
            if target_scope in ["source", "all"]:
                res = self.supabase.table("knowledge_graph").update({"source": self._clean_text(new_name)}).eq("source", old_name).execute()
                if res.data: count += len(res.data)
            if target_scope in ["target", "all"]:
                res = self.supabase.table("knowledge_graph").update({"target": self._clean_text(new_name)}).eq("target", old_name).execute()
                if res.data: count += len(res.data)
            return True, count
        except: return False, 0

    # =========================================================
    # [Metadata Utils] 챗봇이 참조하는 메타데이터 (지능의 원천)
    # =========================================================
    def get_doc_metadata_by_id(self, doc_id, source_type):
        try:
            t_name = "knowledge_base" if source_type == "knowledge" else "manual_base"
            res = self.supabase.table(t_name).select("manufacturer, model_name, measurement_item").eq("id", doc_id).execute()
            if res.data: return res.data[0]
            return {}
        except: return {}

    def search_inventory_for_chat(self, query_text):
        try:
            stop_words = ['재고', '수량', '몇개', '몇', '개', '있어', '있나요', '알려줘', '확인', '조회', '어디', '있니', '현황', '보여줘', '소모품']
            keywords = [k for k in query_text.split() if k not in stop_words and len(k) >= 2]
            if not keywords: return None
            res = self.supabase.table("inventory_items").select("*").or_(",".join([f"item_name.ilike.%{kw}%" for kw in keywords])).execute()
            if not res.data: return f"🔍 **'{', '.join(keywords)}'**에 대한 재고 정보가 없습니다."
            msg = f"📦 **재고 검색 결과 ({len(res.data)}건):**\n"
            for item in res.data[:10]: msg += f"- [{item.get('category')}] **{item.get('item_name')}**: {item.get('current_qty')}개 ({item.get('location')})\n"
            return msg
        except Exception as e: return f"재고 검색 오류: {str(e)}"

    # =========================================================
    # [Knowledge Manage] 지식 관리 (Admin 기능)
    # =========================================================
    def search_knowledge_for_admin(self, keyword):
        try: return self.supabase.table("knowledge_base").select("*").or_(f"issue.ilike.%{keyword}%,solution.ilike.%{keyword}%").order("created_at", desc=True).limit(20).execute().data
        except: return []

    def update_knowledge_item(self, doc_id, new_issue, new_sol, mfr, model, item):
        try:
            from logic_ai import get_embedding
            payload = {"issue": new_issue, "solution": new_sol, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item), "embedding": get_embedding(f"증상: {new_issue}\n해결: {new_sol}"), "semantic_version": 2}
            res = self.supabase.table("knowledge_base").update(payload).eq("id", doc_id).execute()
            return True if res.data else False
        except: return False

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
    
    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {"manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("file_name", file_name).or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').execute()
            return True, f"{len(res.data)}건 일괄 분류 완료"
        except Exception as e: return False, str(e)
    
    def promote_to_knowledge(self, issue, solution, mfr, model, item, author="익명"):
        try:
            from logic_ai import get_embedding
            payload = {"domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), "semantic_version": 1, "is_verified": True, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item), "registered_by": author}
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
    
    def update_vector(self, table_name, row_id, vec):
        try: self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute(); return True
        except: return False

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
    
    def save_relevance_feedback(self, query, doc_id, t_name, score, query_vec=None, reason=None):
        try:
            payload = {
                "query_text": query.strip(), "doc_id": doc_id, "table_name": t_name,
                "relevance_score": score, "reason": reason
            }
            if query_vec: payload["query_embedding"] = query_vec
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False
