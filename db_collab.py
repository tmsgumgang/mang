# db_collab.py
from datetime import datetime

class DBCollab:
    """
    [Extension] 게시판, 댓글, 커뮤니티 기능 전담 모듈
    - DBManager가 이 클래스를 상속받아 사용합니다.
    - 검색 로직(지능)과 분리되어 있어 안전합니다.
    """
    
    # ---------------------------------------------------------
    # [Helper] 독립적인 텍스트 처리 (검색 로직 의존성 제거)
    # ---------------------------------------------------------
    def _collab_normalize_tags(self, raw_tags):
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

    def _collab_clean_text(self, text):
        if not text or str(text).lower() in ['none', 'nan', 'null', '미지정']:
            return "미지정"
        return str(text).strip()

    # ---------------------------------------------------------
    # [Community] 게시판 읽기/쓰기/수정/삭제
    # ---------------------------------------------------------
    def get_community_posts(self):
        try: 
            return self.supabase.table("community_posts").select("*").order("created_at", desc=True).execute().data
        except: return []

    def add_community_post(self, author, title, content, mfr, model, item):
        try:
            payload = {
                "author": author, 
                "title": title, 
                "content": content, 
                "manufacturer": self._collab_clean_text(mfr), 
                "model_name": self._collab_clean_text(model), 
                "measurement_item": self._collab_normalize_tags(item)
            }
            res = self.supabase.table("community_posts").insert(payload).execute()
            return True if res.data else False
        except: return False

    def update_community_post(self, post_id, title, content, mfr, model, item):
        try:
            payload = {
                "title": title, 
                "content": content, 
                "manufacturer": self._collab_clean_text(mfr), 
                "model_name": self._collab_clean_text(model), 
                "measurement_item": self._collab_normalize_tags(item)
            }
            res = self.supabase.table("community_posts").update(payload).eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    def delete_community_post(self, post_id):
        try: 
            res = self.supabase.table("community_posts").delete().eq("id", post_id).execute()
            return True if res.data else False
        except: return False

    # ---------------------------------------------------------
    # [Comments] 댓글 기능
    # ---------------------------------------------------------
    def get_comments(self, post_id):
        try: 
            return self.supabase.table("community_comments").select("*").eq("post_id", post_id).order("created_at").execute().data
        except: return []

    def add_comment(self, post_id, author, content):
        try: 
            res = self.supabase.table("community_comments").insert({
                "post_id": post_id, 
                "author": author, 
                "content": content
            }).execute()
            return True if res.data else False
        except: return False

    # ---------------------------------------------------------
    # [Knowledge Integration] 지식 승격 (Collab -> Knowledge)
    # ---------------------------------------------------------
    def promote_to_knowledge(self, issue, solution, mfr, model, item, author="익명"):
        try:
            # 순환 참조 방지를 위해 함수 내부 import
            from logic_ai import get_embedding
            
            payload = {
                "domain": "기술지식", 
                "issue": issue, 
                "solution": solution, 
                "embedding": get_embedding(f"증상: {issue}\n해결: {solution}"), 
                "semantic_version": 1, 
                "is_verified": True, 
                "manufacturer": self._collab_clean_text(mfr), 
                "model_name": self._collab_clean_text(model), 
                "measurement_item": self._collab_normalize_tags(item), 
                "registered_by": author 
            }
            res = self.supabase.table("knowledge_base").insert(payload).execute()
            return (True, "성공") if res.data else (False, "실패")
        except Exception as e: return (False, str(e))
