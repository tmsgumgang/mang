# db_services.py 내부 메서드 수정

    def promote_to_knowledge(self, issue, solution, mfr, model, item, author="익명"): # [수정] author 파라미터 추가
        try:
            from logic_ai import get_embedding
            
            clean_mfr = self._clean_text(mfr)
            clean_model = self._clean_text(model)
            clean_item = self._normalize_tags(item)

            payload = {
                "domain": "기술지식", 
                "issue": issue, 
                "solution": solution, 
                "embedding": get_embedding(issue), 
                "semantic_version": 1, 
                "is_verified": True, 
                "manufacturer": clean_mfr, 
                "model_name": clean_model, 
                "measurement_item": clean_item,
                "author": author  # [NEW] 작성자 이름 저장 (Supabase 칼럼명 확인 필요)
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
