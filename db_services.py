# db_knowledge.py와 db_collab.py를 임포트하여 통합합니다.
from db_knowledge import DBKnowledge
from db_collab import DBCollab

class DBManager(DBKnowledge, DBCollab):
    def __init__(self, supabase_client):
        # DBKnowledge의 __init__을 호출하여 supabase 클라이언트 설정
        super().__init__(supabase_client)
        # DBCollab은 별도 init이 필요 없지만, 필요시 메서드를 여기서 오버라이딩 가능
