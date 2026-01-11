from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    def keep_alive(self):
        try: self.supabase.table("knowledge_base").select("id").limit(1).execute()
        except: pass

    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    def save_relevance_feedback(self, query, doc_id, t_name, score, query_vec=None):
        try:
            payload = {
                "query_text": query.strip(),
                "doc_id": doc_id,
                "table_name": t_name,
                "relevance_score": score
            }
            if query_vec:
                payload["query_embedding"] = query_vec
            
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False

    def get_semantic_context_blacklist(self, query_vec):
        try:
            res = self.supabase.rpc("match_relevance_feedback_batch", {
                "input_embedding": query_vec,
                "match_threshold": 0.95
            }).execute()
            
            if res.data:
                return {(item['table_name'], item['doc_id']) for item in res.data if item['relevance_score'] < 0}
            return set()
        except: return set()

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    # [V198 핵심] 쌍끌이 SQL (Dual-Keyword SQL)
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        try:
            target_item = intent.get('target_item', '공통')
            
            # 1. AI 벡터 검색
            vector_results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            # 2. SQL 키워드 강제 검색 (Space & No-Space 동시 공략)
            keyword_results = []
            
            # 검색할 키워드 후보군 생성
            search_candidates = set()
            if target_item and target_item not in ['공통', '미지정', 'none', 'unknown']:
                search_candidates.add(target_item.strip()) # 원본 (예: 채수 펌프)
                search_candidates.add(target_item.replace(" ", "")) # 붙여쓰기 (예: 채수펌프)
            
            # [안전망] 타겟이 '공통'이면 사용자 질문에서 직접 명사 추정 (2글자 이상)
            # (예: "채수펌프 교체..." -> "채수펌프"가 target_item에 안 잡혔을 경우 대비)
            if not search_candidates:
                words = query_text.split()
                for w in words:
                    if len(w) >= 2 and w not in ['알려줘', '어떻게', '교체', '방법', '준비물']:
                        search_candidates.add(w)
            
            if search_candidates:
                t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"
                query_builder = self.supabase.table(t_name).select("*")
                
                # OR 조건 생성 (모든 후보 키워드에 대해 ILIKE 적용)
                # measurement_item, model_name, content(issue/solution) 전부 뒤짐
                or_conditions = []
                for kw in search_candidates:
                    if not kw: continue
                    if t_name == "manual_base":
                        or_conditions.append(f"measurement_item.ilike.%{kw}%")
                        or_conditions.append(f"model_name.ilike.%{kw}%")
                        or_conditions.append(f"content.ilike.%{kw}%")
                    else:
                        or_conditions.append(f"measurement_item.ilike.%{kw}%")
                        or_conditions.append(f"issue.ilike.%{kw}%")
                        or_conditions.append(f"solution.ilike.%{kw}%")
                
                if or_conditions:
                    # 콤마로 연결하여 하나의 거대한 OR 필터 완성
                    final_filter = ",".join(or_conditions)
                    res = query_builder.or_(final_filter).limit(10).execute()
                    
                    if res.data:
                        for d in res.data:
                            d['similarity'] = 0.99 # 강제 소환 가산점
                            keyword_results.append(d)

            # 3. 결과 병합
            merged_map = {}
            for d in vector_results: merged_map[d['id']] = d
            for d in keyword_results: merged_map[d['id']] = d # SQL 결과 우선
                
            final_results_list = list(merged_map.values())
            
            # 4. 필터링 로직 (기존 유지)
            filtered_results = []
            keywords = [k for k in query_text.split() if len(k) > 1]
            t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"

            for d in final_results_list:
                if context_blacklist and (t_name, d['id']) in context_blacklist:
                    continue
                
                final_score = d.get('similarity') or 0
                
                content = (d.get('content') or d.get('solution') or "").lower()
                for kw in keywords:
                    if kw.lower() in content: final_score += 0.1
                
                d['similarity'] = final_score
                filtered_results.append(d)
                
            return filtered_results
        except Exception as e:
            return []

    # (이하 기존 함수 보존)
    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {"author": author, "title": title, "content": content, "manufacturer": mfr, "model_name": model, "measurement_item": item}
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {"title": title, "content": content, "manufacturer": mfr, "model_name": model, "measurement_item": item}
            res = self.supabase.table("community_posts").update(payload).eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def delete_community_post(self, post_id):
        try:
            res = self.supabase.table("community_posts").delete().eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def get_comments(self, post_id):
        try: return self.supabase.table("community_comments").select("*").eq("post_id", post_id).order("created_at").execute().data
        except: return []

    def add_comment(self, post_id, author, content):
        try:
            res = self.supabase.table("community_comments").insert({"post_id": post_id, "author": author, "content": content}).execute()
            return True if res.data else False
        except: return False

    def promote_to_knowledge(self, issue, solution, mfr, model, item):
        try:
            from logic_ai import get_embedding
            payload = {"domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), "semantic_version": 1, "is_verified": True, "manufacturer": str(mfr).strip() or "미지정", "model_name": str(model).strip() or "미지정", "measurement_item": str(item).strip() or "공통"}
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("file_name", file_name).or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').execute()
            return True, f"{len(res.data)}건 일괄 분류 완료"
        except Exception as e: return False, str(e)

    def update_vector(self, table_name, row_id, vec):
        try: self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute(); return True
        except: return False

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
