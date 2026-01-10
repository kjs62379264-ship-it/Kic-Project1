import sqlite3

# 1. 사용 중인 DB 파일에 연결
conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

print("DB에 연결되었습니다. activity_logs 테이블 생성을 시작합니다...")

# 2. activity_logs 테이블 생성 쿼리 실행
# (IF NOT EXISTS가 있어서 이미 있으면 건너뛰고, 없으면 만듭니다)
cursor.execute("""
CREATE TABLE IF NOT EXISTS activity_logs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT,
    user_name TEXT,
    action_type TEXT,
    target_category TEXT,
    details TEXT,
    ip_address TEXT,
    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
);
""")

# 3. 변경사항 저장 및 종료
conn.commit()
conn.close()

print("✅ 성공! 'activity_logs' 테이블이 안전하게 추가되었습니다.")