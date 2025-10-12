import sqlite3

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

# --- 기존 테이블 삭제 ---
cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("DROP TABLE IF EXISTS departments")
cursor.execute("DROP TABLE IF EXISTS positions")
cursor.execute("DROP TABLE IF EXISTS email_domains")
# cursor.execute("DROP TABLE IF EXISTS statuses") # statuses 테이블 관련 줄 삭제

# --- 부서, 직급, 이메일 도메인 테이블 생성 및 데이터 추가 ---
# (departments, positions, email_domains 테이블 생성 코드는 기존과 동일)
cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO departments (name) VALUES (?)", [('인사팀',), ('개발팀',), ('디자인팀',), ('마케팅팀',)])

cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO positions (name) VALUES (?)", [('사원',), ('주임',), ('대리',), ('과장',), ('팀장',)])

cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", [('company.com',), ('gmail.com',), ('naver.com',)])
print("Necessary tables created and populated.")

# --- ★ employees 테이블에서 status 컬럼 제거 ---
cursor.execute("""
CREATE TABLE employees (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    department TEXT NOT NULL,
    position TEXT NOT NULL,
    hire_date DATE NOT NULL,
    phone_number TEXT,
    email TEXT,
    address TEXT,
    gender TEXT
);
""")
print("Table 'employees' created without status column.")

conn.commit()
conn.close()