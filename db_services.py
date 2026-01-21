from collections import Counter

class DBManager:
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

    def get_penalty_counts(self):
        try:
            res = self.supabase.table("knowledge_blacklist").select("source_id").execute()
            return Counter([r['source_id'] for r in res.data])
        except: return {}

    def save_relevance_feedback(self, query, doc_id, t_name, score, query_vec=None, reason=None):
        try:
            payload = {
                "query_text": query.strip(),
                "doc_id": doc_id,
                "table_name": t_name,
                "relevance_score": score,
                "reason": reason
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
            clean_mfr = self._clean_text(mfr)
            clean_model = self._clean_text(model)
            clean_item = self._normalize_tags(item)
            payload = {
                "manufacturer": clean_mfr, 
                "model_name": clean_model, 
                "measurement_item": clean_item, 
                "semantic_version": 1, 
                "review_required": False
            }
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    # [V198] 검색 엔진
    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        try:
            target_item = intent.get('target_item', '공통')
            vector_results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            
            keyword_results = []
            search_candidates = set()
            if target_item and target_item not in ['공통', '미지정', 'none', 'unknown']:
                search_candidates.add(target_item.strip())
                search_candidates.add(target_item.replace(" ", ""))
            
            if not search_candidates:
                words = query_text.split()
                for w in words:
                    if len(w) >= 2 and w not in ['알려줘', '어떻게', '교체', '방법', '준비물']:
                        search_candidates.add(w)
            
            if search_candidates:
                t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"
                query_builder = self.supabase.table(t_name).select("*")
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
                    final_filter = ",".join(or_conditions)
                    res = query_builder.or_(final_filter).limit(10).execute()
                    if res.data:
                        for d in res.data:
                            d['similarity'] = 0.99
                            keyword_results.append(d)

            merged_map = {}
            for d in vector_results: merged_map[d['id']] = d
            for d in keyword_results: merged_map[d['id']] = d 
                
            final_results_list = list(merged_map.values())
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
        except Exception as e: return []

    def search_keyword_fallback(self, query_text):
        keywords = [k for k in query_text.split() if len(k) >= 2]
        if not keywords: return []
        target_keyword = max(keywords, key=len)
        try:
            response = self.supabase.table("manual_base").select("*").or_(f"content.ilike.%{target_keyword}%,model_name.ilike.%{target_keyword}%").limit(5).execute()
            docs = response.data
            for d in docs:
                d['similarity'] = 0.98; d['source_table'] = 'manual_base'; d['is_verified'] = False 
            return docs
        except: return []

    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {"author": author, "title": title, "content": content, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item)}
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {"title": title, "content": content, "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item)}
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

    def promote_to_knowledge(self, issue, solution, mfr, model, item, author="익명"):
        try:
            from logic_ai import get_embedding
            payload = {
                "domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), 
                "semantic_version": 1, "is_verified": True, 
                "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item),
                "registered_by": author 
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            clean_mfr = self._clean_text(mfr)
            clean_model = self._clean_text(model)
            clean_item = self._normalize_tags(item)
            payload = {
                "manufacturer": clean_mfr, 
                "model_name": clean_model, 
                "measurement_item": clean_item, 
                "semantic_version": 1, 
                "review_required": False
            }
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

    # =========================================================
    # [V220] 📦 소모품 재고관리 (Inventory)
    # =========================================================
    def get_inventory_items(self):
        try:
            return self.supabase.table("inventory_items").select("*").order("category").order("item_name").execute().data
        except: return []

    # [수정] .select() 제거, 에러 메시지 반환
    def add_inventory_item(self, cat, name, model, loc, desc, initial_qty, worker):
        try:
            clean_mfr = self._clean_text(desc) 
            
            payload = {
                "category": cat,
                "item_name": name,
                "model_name": model,
                "location": loc,
                "description": desc,
                "current_qty": 0 
            }
            # [Fix] .select() 제거 -> 'SyncQueryRequestBuilder' 에러 해결
            res = self.supabase.table("inventory_items").insert(payload).execute()
            
            if res.data:
                new_item_id = res.data[0]['id']
                if initial_qty > 0:
                    self.log_inventory_change(new_item_id, "입고", initial_qty, worker, "신규 품목 등록 (초기 재고)")
                return True, "성공"
            return False, "데이터베이스가 응답하지 않습니다."
        except Exception as e: 
            return False, str(e)

    def log_inventory_change(self, item_id, c_type, qty, worker, reason):
        try:
            payload = {
                "item_id": item_id,
                "change_type": c_type,
                "quantity": qty,
                "worker_name": worker,
                "reason": reason
            }
            res = self.supabase.table("inventory_logs").insert(payload).execute()
            return True if res.data else False
        except Exception as e:
            print(f"Inventory Log Error: {e}")
            return False

    def delete_inventory_item(self, item_id):
        try:
            self.supabase.table("inventory_items").delete().eq("id", item_id).execute()
            return True
        except: return False
    
    def get_inventory_logs(self, item_id=None):
        try:
            query = self.supabase.table("inventory_logs").select("*, inventory_items(item_name)").order("created_at", desc=True).limit(50)
            if item_id:
                query = query.eq("item_id", item_id)
            return query.execute().data
        except: return []
