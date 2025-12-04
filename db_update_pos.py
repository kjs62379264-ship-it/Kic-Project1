import sqlite3

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

try:
    cursor.execute("ALTER TABLE positions ADD COLUMN is_active BOOLEAN DEFAULT 1")
    print("직급 테이블에 is_active 컬럼 추가 완료.")
except:
    print("이미 컬럼이 존재합니다.")

conn.commit()
conn.close()