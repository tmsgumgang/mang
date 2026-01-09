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

    # [V149] 에러 발생 시 구체적인 메시지를 반환하도록 개선
    def update_record_labels(self, table_name, row_id, mfr, model, item):
        try:
            res = self.supabase.table(table_name).update({
                "manufacturer": mfr, "model_name": model, "measurement_item": item,
                "semantic_version": 1, "review_required": False
            }).eq("id", row_id).execute()
            
            # 업데이트된 데이터가 없으면 RLS 정책 문제일 가능성이 큼
            if not res.data:
                return False, "대상 데이터를 찾을 수 없거나 RLS 권한이 없습니다."
            return True, "성공"
        except Exception as e:
            return False, str(e)

    def delete_record(self, table_name, row_id):
        try:
            res = self.supabase.table(table_name).delete().eq("id", row_id).execute()
            if not res.data:
                return False, "삭제 권한이 없거나 이미 삭제된 데이터입니다."
            return True, "성공"
        except Exception as e:
            return False, str(e)

    def match_filtered_db(self, rpc_name, query_vec, threshold, intent):
        try:
            results = self.supabase.rpc(rpc_name, {"query_embedding": query_vec, "match_threshold": threshold, "match_count": 40}).execute().data or []
            target_m = intent.get('target_model')
            if target_m:
                for d in results:
                    if target_m.lower() in str(d.get('model_name','')).lower():
                        d['similarity'] = (d.get('similarity') or 0) + 0.3
            return results
        except: return []

    def bulk_approve_file(self, table_name, file_name):
        try:
            self.supabase.table(table_name).update({"semantic_version": 1, "review_required": False}).eq("file_name", file_name).eq("semantic_version", 2).execute()
            return True
        except: return False

    def update_vector(self, table_name, row_id, vec):
        try:
            self.supabase.table(table_name).update({"embedding": vec}).eq("id", row_id).execute()
            return True
        except: return False
