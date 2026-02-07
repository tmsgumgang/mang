from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # =========================================================
    # [Helper] 데이터 정규화 및 공통 기능
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
                "query_text": query.strip(), "doc_id": doc_id, "table_name": t_name,
                "relevance_score": score, "reason": reason
            }
            if query_vec: payload["query_embedding"] = query_vec
            self.supabase.table("relevance_feedback").insert(payload).execute()
            return True
        except: return False

    def get_semantic_context_blacklist(self, query_vec):
        try:
            res = self.supabase.rpc("match_relevance_feedback_batch", {
                "input_embedding": query_vec, "match_threshold": 0.95
            }).execute()
            if res.data:
                return {(item['table_name'], item['doc_id']) for item in res.data if item['relevance_score'] < 0}
            return set()
        except: return set()

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {
                "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model),
                "measurement_item": self._normalize_tags(item), "semantic_version": 1, "review_required": False
            }
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def match_filtered_db(self, rpc_name, query_vec, threshold, intent, query_text, context_blacklist=None):
        try:
            target_item = intent.get('target_item', '공통')
            vector_results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            keyword_results = []
            search_candidates = set()
            if target_item and target_item not in ['공통', '미지정', 'none', 'unknown']:
                search_candidates.add(target_item.strip()); search_candidates.add(target_item.replace(" ", ""))
            if not search_candidates:
                words = query_text.split()
                for w in words:
                    if len(w) >= 2 and w not in ['알려줘', '어떻게', '교체', '방법', '준비물']: search_candidates.add(w)
            if search_candidates:
                t_name = "manual_base" if "manual" in rpc_name else "knowledge_base"
                query_builder = self.supabase.table(t_name).select("*")
                or_conditions = []
                for kw in search_candidates:
                    if not kw: continue
                    if t_name == "manual_base":
                        or_conditions.append(f"measurement_item.ilike.%{kw}%"); or_conditions.append(f"model_name.ilike.%{kw}%"); or_conditions.append(f"content.ilike.%{kw}%")
                    else:
                        or_conditions.append(f"measurement_item.ilike.%{kw}%"); or_conditions.append(f"issue.ilike.%{kw}%"); or_conditions.append(f"solution.ilike.%{kw}%")
                if or_conditions:
                    res = query_builder.or_(",".join(or_conditions)).limit(10).execute()
                    if res.data:
                        for d in res.data: d['similarity'] = 0.99; keyword_results.append(d)
            merged_map = {}
            for d in vector_results: merged_map[d['id']] = d
            for d in keyword_results: merged_map[d['id']] = d 
            final_list = list(merged_map.values()); filtered = []
            keywords = [k for k in query_text.split() if len(k) > 1]
            for d in final_list:
                if context_blacklist and (t_name, d['id']) in context_blacklist: continue
                score = d.get('similarity') or 0; content = (d.get('content') or d.get('solution') or "").lower()
                for kw in keywords:
                    if kw.lower() in content: score += 0.1
                d['similarity'] = score; filtered.append(d)
            return filtered
        except: return []

    def search_keyword_fallback(self, query_text):
        keywords = [k for k in query_text.split() if len(k) >= 2]
        if not keywords: return []
        target = max(keywords, key=len)
        try:
            res = self.supabase.table("manual_base").select("*").or_(f"content.ilike.%{target}%,model_name.ilike.%{target}%").limit(5).execute()
            docs = res.data
            for d in docs: d['similarity'] = 0.98; d['source_table'] = 'manual_base'; d['is_verified'] = False 
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
                "semantic_version": 1, "is_verified": True, "registered_by": author,
                "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model), "measurement_item": self._normalize_tags(item)
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {
                "manufacturer": self._clean_text(mfr), "model_name": self._clean_text(model),
                "measurement_item": self._normalize_tags(item), "semantic_version": 1, "review_required": False
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
    # [Inventory] 재고관리
    # =========================================================
    def get_inventory_items(self):
        try: return self.supabase.table("inventory_items").select("*").order("category").order("item_name").execute().data
        except: return []

    def check_item_exists(self, name, model):
        try:
            res = self.supabase.table("inventory_items").select("*").eq("item_name", name).eq("model_name", model).execute()
            return res.data[0] if res.data else None
        except: return None

    def update_inventory_general(self, item_id, updates, worker):
        try:
            current = self.supabase.table("inventory_items").select("*").eq("id", item_id).execute()
            if not current.data: return False, "항목 없음"
            old_qty = current.data[0].get('current_qty', 0)
            self.supabase.table("inventory_items").update(updates).eq("id", item_id).execute()
            if 'current_qty' in updates:
                new_qty = updates['current_qty']
                if old_qty != new_qty:
                    diff = new_qty - old_qty
                    self.log_inventory_change(item_id, "입고" if diff > 0 else "출고", abs(diff), worker, f"직접 수정 ({old_qty}→{new_qty})")
            return True, "성공"
        except Exception as e: return False, str(e)

    def add_inventory_item(self, cat, name, model, loc, mfr, measure_val, desc, initial_qty, worker):
        try:
            payload = {
                "category": cat, "item_name": name, "model_name": model, "location": loc,
                "manufacturer": self._clean_text(mfr), "measurement_item": self._normalize_tags(measure_val),
                "description": self._clean_text(desc), "current_qty": 0 
            }
            res = self.supabase.table("inventory_items").insert(payload).execute()
            if res.data:
                if initial_qty > 0: self.log_inventory_change(res.data[0]['id'], "입고", initial_qty, worker, "신규 등록 (초기재고)")
                return True, "성공"
            return False, "응답 없음"
        except Exception as e: return False, str(e)

    def log_inventory_change(self, item_id, c_type, qty, worker, reason):
        try:
            payload = {"item_id": item_id, "change_type": c_type, "quantity": qty, "worker_name": worker, "reason": reason}
            self.supabase.table("inventory_logs").insert(payload).execute()
            return True
        except: return False

    def delete_inventory_item(self, item_id):
        try: self.supabase.table("inventory_items").delete().eq("id", item_id).execute(); return True
        except: return False
    
    def get_inventory_logs(self, item_id=None):
        try:
            q = self.supabase.table("inventory_logs").select("*, inventory_items(item_name)").order("created_at", desc=True).limit(50)
            if item_id: q = q.eq("item_id", item_id)
            return q.execute().data
        except: return []

    # =========================================================
    # [V287 Update] 🤝 협업 기능 (정밀 관리 및 안정화)
    # =========================================================
    
    def get_schedules(self, include_completed=True):
        """ 실시간 일정 조회 """
        try:
            query = self.supabase.table("collab_schedules").select("*").order("start_time", desc=False)
            if not include_completed:
                query = query.eq("status", "진행중")
            res = query.execute()
            return res.data if res.data else []
        except Exception as e:
            print(f"Fetch Error: {e}")
            return []

    def get_task_stats(self):
        """ 실시간 통계 계산 """
        try:
            res = self.supabase.table("collab_schedules").select("status").execute()
            if not res or not res.data: return {"total": 0, "pending": 0, "completed": 0}
            stats = Counter([r['status'] for r in res.data])
            return {"total": len(res.data), "pending": stats.get("진행중", 0), "completed": stats.get("완료", 0)}
        except: return {"total": 0, "pending": 0, "completed": 0}

    def add_schedule(self, title, start_dt, end_dt, cat, desc, user, location, assignee=None, sub_tasks=None):
        """ 일정 등록 (데이터 누락 방지 강화) """
        try:
            payload = {
                "title": title, "start_time": start_dt, "end_time": end_dt,
                "category": cat, "description": desc, "created_by": user,
                "location": location, "assignee": assignee, 
                "status": "진행중",
                "sub_tasks": sub_tasks if sub_tasks is not None else []
            }
            res = self.supabase.table("collab_schedules").insert(payload).execute()
            return True if res.data else False
        except Exception as e:
            print(f"Insert Error: {e}")
            return False

    def update_schedule(self, sch_id, **kwargs):
        """ 일정 업데이트 (kwargs 사용으로 인자 자유도 극대화) """
        try:
            if not kwargs: return False
            res = self.supabase.table("collab_schedules").update(kwargs).eq("id", sch_id).execute()
            return True if res.data else False
        except Exception as e:
            print(f"Update Error: {e}")
            return False

    def delete_schedule(self, sch_id):
        try:
            self.supabase.table("collab_schedules").delete().eq("id", sch_id).execute()
            return True
        except: return False

    def set_duty_worker(self, date_str, name):
        try:
            payload = {"date": date_str, "worker_name": name}
            self.supabase.table("duty_roster").upsert(payload, on_conflict="date").execute()
            return True
        except: return False

    def get_duty_roster(self):
        try:
            res = self.supabase.table("duty_roster").select("*").execute()
            return res.data if res.data else []
        except: return []

    def get_contacts(self):
        try: return self.supabase.table("collab_contacts").select("*").order("company_name").execute().data
        except: return []

    def add_contact(self, company, name, phone, email, tags, memo, rank):
        try:
            payload = {"company_name": company, "person_name": name, "phone": phone, "email": email, "tags": tags, "memo": memo, "rank": rank}
            res = self.supabase.table("collab_contacts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_contact(self, contact_id, **kwargs):
        try:
            if not kwargs: return False
            res = self.supabase.table("collab_contacts").update(kwargs).eq("id", contact_id).execute()
            return True if res.data else False
        except: return False

    def delete_contact(self, contact_id):
        try: self.supabase.table("collab_contacts").delete().eq("id", contact_id).execute(); return True
        except: return False
