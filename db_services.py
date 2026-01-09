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
            payload = {
                "manufacturer": str(mfr).strip(),
                "model_name": str(model).strip(),
                "measurement_item": str(item).strip(),
                "semantic_version": 1,
                "review_required": False
            }
            res = self.supabase.table(table_name).update(payload).eq("id", row_id).execute()
            if not res.data:
                return False, "대상 데이터를 찾을 수 없거나 RLS 정책 위반입니다."
            return True, "성공"
        except Exception as e:
            return False, str(e)

    # [V151 추가] 동일 파일 미분류 데이터 일괄 라벨링
    def update_file_labels(self, table_name, file_name, mfr, model, item):
        try:
            payload = {
                "manufacturer": str(mfr).strip(),
                "model_name": str(model).strip(),
                "measurement_item": str(item).strip(),
                "semantic_version": 1,
                "review_required": False
            }
            # 파일명이 일치하고, 아직 분류되지 않은(NULL, 빈값, 미지정) 데이터만 타겟팅
            res = self.supabase.table(table_name).update(payload)\
                .eq("file_name", file_name)\
                .or_(f'manufacturer.eq.미지정,manufacturer.is.null,manufacturer.eq.""')\
                .execute()
            return True, f"{len(res.data)}건 일괄 분류 완료"
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
