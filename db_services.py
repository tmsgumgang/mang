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

    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        try:
            target_item = intent.get('target_item')
            target_model = intent.get('target_model')
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            filtered_results = []
            for d in results:
                score_adj = 0
                if target_item and target_item.lower() in str(d.get('measurement_item', '')).lower(): score_adj += 0.5
                elif target_item: score_adj -= 0.3
                if target_model and target_model.lower() in str(d.get('model_name', '')).lower(): score_adj += 0.4
                d['similarity'] = (d.get('similarity') or 0) + score_adj
                filtered_results.append(d)
            return filtered_results
        except: return []

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))

    def get_community_posts(self):
        try:
            res = self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute()
            return res.data if res.data else []
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
        try:
            res = self.supabase.table("community_comments").select("*").eq("post_id", post_id).order("created_at").execute()
            return res.data if res.data else []
        except: return []

    def add_comment(self, post_id, author, content):
        try:
            res = self.supabase.table("community_comments").insert({"post_id": post_id, "author": author, "content": content}).execute()
            return True if res.data else False
        except: return False

    # [V167] 지식 승격 시 실시간 벡터 임베딩 생성 로직 포함
    def promote_to_knowledge(self, issue, solution, mfr, model, item):
        try:
            from logic_ai import get_embedding # 실시간 벡터 추출
            payload = {
                "domain": "기술지식",
                "issue": issue,
                "solution": solution,
                "embedding": get_embedding(issue), # 검색을 위한 벡터 데이터 생성
                "semantic_version": 1,
                "is_verified": True,
                "manufacturer": str(mfr).strip() or "미지정",
                "model_name": str(model).strip() or "미지정",
                "measurement_item": str(item).strip() or "공통"
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            if res.data: return True, "성공"
            else: return False, "DB 저장 실패"
        except Exception as e:
            return False, str(e)

    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {"manufacturer": str(mfr).strip(), "model_name": str(model).strip(), "measurement_item": str(item).strip(), "semantic_version": 1, "review_required": False}
            res = self.supabase.table(table_name).update(payload).eq("file_name", file_name).or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""').execute()
            return True, f"{len(res.data)}건 일괄 분류 완료"
        except Exception as e: return False, str(e)

    def update_vector(self, table_name, row_id, vec):
        try:
            self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute()
            return True
        except: return False
