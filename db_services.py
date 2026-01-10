from collections import Counter

class DBManager:
    def __init__(self, supabase_client):
        self.supabase = supabase_client

    # [기본 관리 로직]
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

    # [커뮤니티 및 지식화 로직 복구]
    def get_community_posts(self):
        try: return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content):
        try: return self.supabase.table("community_posts").insert({"author": author, "title": title, "content": content}).execute()
        except: return None

    def get_comments(self, post_id):
        try: return self.supabase.table("community_comments").select("*").eq("post_id", post_id).order("created_at").execute().data
        except: return []

    def add_comment(self, post_id, author, content):
        try: return self.supabase.table("community_comments").insert({"post_id": post_id, "author": author, "content": content}).execute()
        except: return None

    def promote_to_knowledge(self, issue, solution):
        try:
            # 커뮤니티 답변을 경험 지식으로 등록
            from logic_ai import get_embedding
            payload = {"domain": "기술지식", "issue": issue, "solution": solution, "embedding": get_embedding(issue), "semantic_version": 1, "is_verified": True}
            self.supabase.table("knowledge_base").insert(payload).execute()
            return True
        except: return False

    # [매뉴얼 관리 로직]
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
