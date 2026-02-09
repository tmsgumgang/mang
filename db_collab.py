from collections import Counter
from datetime import datetime

class DBCollab:
    """
    [Extension] 현장 협업 통합 모듈 (Inventory + Schedule + Contact + Community)
    - DBManager가 이 클래스를 상속받아 사용합니다.
    """
    
    # =========================================================
    # [Inventory] 재고관리 (관리자용 CRUD) - 원본 복구
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
                    self.log_inventory_change(item_id, "입고" if diff > 0 else "출고", abs(diff), worker, f"직접 수정 ({old_qty} -> {new_qty})")
            return True, "성공"
        except Exception as e: return False, str(e)

    def add_inventory_item(self, cat, name, model, loc, mfr, measure_val, desc, initial_qty, worker):
        try:
            payload = {
                "category": cat, "item_name": name, "model_name": model, "location": loc,
                "manufacturer": str(mfr).strip(), "measurement_item": str(measure_val).strip(),
                "description": str(desc).strip(), "current_qty": 0 
            }
            res = self.supabase.table("inventory_items").insert(payload).execute()
            if res.data:
                if initial_qty > 0: self.log_inventory_change(res.data[0]['id'], "입고", initial_qty, worker, "신규 등록")
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

    def update_inventory_qty(self, item_id, new_qty, worker):
        try:
            current = self.supabase.table("inventory_items").select("current_qty").eq("id", item_id).execute()
            old_qty = current.data[0]['current_qty'] if current.data else 0
            
            if old_qty == new_qty: return True, "변경 없음"

            self.supabase.table("inventory_items").update({"current_qty": new_qty}).eq("id", item_id).execute()
            
            diff = new_qty - old_qty
            log_type = "입고" if diff > 0 else "출고"
            reason = f"엑셀 갱신 ({old_qty} → {new_qty})"
            
            self.log_inventory_change(item_id, log_type, abs(diff), worker, reason)
            return True, "갱신 성공"
        except Exception as e:
            return False, str(e)

    # =========================================================
    # [Collab] 일정 및 당직 (Schedule) - 원본 복구
    # =========================================================
    def get_schedules(self, include_completed=True):
        try:
            query = self.supabase.table("collab_schedules").select("*").order("start_time", desc=False)
            if not include_completed: query = query.eq("status", "진행중")
            res = query.execute()
            return res.data if res.data else []
        except: return []

    def get_task_stats(self):
        try:
            res = self.supabase.table("collab_schedules").select("status").execute()
            if not res or not res.data: return {"total": 0, "pending": 0, "completed": 0}
            stats = Counter([r['status'] for r in res.data])
            return {"total": len(res.data), "pending": stats.get("진행중", 0), "completed": stats.get("완료", 0)}
        except: return {"total": 0, "pending": 0, "completed": 0}

    def add_schedule(self, title, start_dt, end_dt, cat, desc, user, location, assignee=None, sub_tasks=None):
        try:
            payload = {
                "title": title, "start_time": start_dt, "end_time": end_dt,
                "category": cat, "description": desc, "created_by": user,
                "location": location, "assignee": assignee, "status": "진행중",
                "sub_tasks": sub_tasks if sub_tasks is not None else []
            }
            res = self.supabase.table("collab_schedules").insert(payload).execute()
            return (True, None) if res.data else (False, "응답 없음")
        except Exception as e: return (False, str(e))

    def update_schedule(self, sch_id, **kwargs):
        try:
            if not kwargs: return (True, None)
            res = self.supabase.table("collab_schedules").update(kwargs).eq("id", sch_id).execute()
            return (True, None) if res.data else (False, "응답 없음")
        except Exception as e: return (False, str(e))

    def delete_schedule(self, sch_id):
        try: self.supabase.table("collab_schedules").delete().eq("id", sch_id).execute(); return True
        except: return False

    def get_duty_roster(self):
        try:
            res = self.supabase.table("duty_roster").select("*").execute()
            return res.data if res.data else []
        except: return []

    def set_duty_worker(self, date_str, name):
        try:
            self.supabase.table("duty_roster").upsert({"date": date_str, "worker_name": name}, on_conflict="date").execute()
            return True
        except: return False

    def delete_duty_worker(self, duty_id):
        try: self.supabase.table("duty_roster").delete().eq("id", duty_id).execute(); return True
        except: return False

    # =========================================================
    # [Collab] 연락처 (Contact) - 원본 복구
    # =========================================================
    def get_contacts(self):
        try: return self.supabase.table("collab_contacts").select("*").order("company_name").execute().data or []
        except: return []

    def add_contact(self, company, name, phone, email, tags, memo, rank):
        try:
            payload = {"company_name": company, "person_name": name, "phone": phone, "email": email, "tags": tags, "memo": memo, "rank": rank}
            res = self.supabase.table("collab_contacts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_contact(self, contact_id, **kwargs):
        try:
            if not kwargs: return (True, None)
            res = self.supabase.table("collab_contacts").update(kwargs).eq("id", contact_id).execute()
            return (True, None) if res.data else (False, "응답 없음")
        except Exception as e: return (False, str(e))

    def delete_contact(self, contact_id):
        try: self.supabase.table("collab_contacts").delete().eq("id", contact_id).execute(); return True
        except: return False

    # =========================================================
    # [Community] 게시판 (Community) - [추가됨]
    # =========================================================
    def _collab_clean_text(self, text):
        if not text or str(text).lower() in ['none', 'nan', 'null', '미지정']: return "미지정"
        return str(text).strip()

    def _collab_normalize_tags(self, raw_tags):
        if not raw_tags or str(raw_tags).lower() in ['none', 'nan', 'null']: return "공통"
        tags = [t.strip() for t in str(raw_tags).split(',')]
        clean_tags = []
        for tag in tags:
            if tag and tag not in set(clean_tags): clean_tags.append(tag)
        return ", ".join(clean_tags) if clean_tags else "공통"

    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {"author": author, "title": title, "content": content, 
                       "manufacturer": self._collab_clean_text(mfr), 
                       "model_name": self._collab_clean_text(model), 
                       "measurement_item": self._collab_normalize_tags(item)}
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {"title": title, "content": content, 
                       "manufacturer": self._collab_clean_text(mfr), 
                       "model_name": self._collab_clean_text(model), 
                       "measurement_item": self._collab_normalize_tags(item)}
            res = self.supabase.table("community_posts").update(payload).eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def delete_community_post(self, post_id):
        try: self.supabase.table("community_posts").delete().eq("id", post_id).execute(); return True
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
            # 순환 참조 방지용 내부 import
            from logic_ai import get_embedding
            payload = {
                "domain": "기술지식", "issue": issue, "solution": solution, 
                "embedding": get_embedding(issue), "semantic_version": 1, "is_verified": True, 
                "manufacturer": self._collab_clean_text(mfr), "model_name": self._collab_clean_text(model), 
                "measurement_item": self._collab_normalize_tags(item), "registered_by": author
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
    
    def search_community_match(self, keyword):
        try:
            res = self.supabase.table("community_posts").select("*")\
                .or_(f"title.ilike.%{keyword}%,content.ilike.%{keyword}%")\
                .order("created_at", desc=True).limit(5).execute()
            results = []
            if res.data:
                for p in res.data:
                    results.append({
                        "id": p['id'],
                        "content": p['title'] + "\n" + p['content'][:100],
                        "source_table": "community_posts",
                        "similarity": 0.90,
                        "manufacturer": p.get('manufacturer', '게시판'),
                        "model_name": p.get('model_name', 'User'),
                        "measurement_item": p.get('measurement_item', 'Q&A'),
                        "is_verified": False
                    })
            return results
        except: return []
