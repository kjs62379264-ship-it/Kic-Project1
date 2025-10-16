import sqlite3

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

# --- 기존 테이블 삭제 ---
cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("DROP TABLE IF EXISTS departments")
cursor.execute("DROP TABLE IF EXISTS positions")
cursor.execute("DROP TABLE IF EXISTS email_domains")
cursor.execute("DROP TABLE IF EXISTS attendance") # ✨ [추가] attendance 테이블 삭제 구문

# --- 부서, 직급, 이메일 도메인 테이블 생성 및 데이터 추가 ---
cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO departments (name, code) VALUES (?, ?)", [
    ('인사팀', 'HR'), 
    ('개발팀', 'DV'), 
    ('디자인팀', 'DS'), 
    ('마케팅팀', 'MK')
])
cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO positions (name) VALUES (?)", [('사원',), ('주임',), ('대리',), ('과장',), ('팀장',)])
cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", [('company.com',), ('gmail.com',), ('naver.com',)])
print("Necessary tables created and populated.")

# --- employees 테이블 생성 ---
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
    gender TEXT,
    status TEXT DEFAULT '재직' NOT NULL 
);
""")
print("Table 'employees' created with status column.")

# ✨ [추가] 출퇴근 기록을 위한 attendance 테이블 생성
cursor.execute("""
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    record_date DATE NOT NULL,
    clock_in_time DATETIME,
    clock_out_time DATETIME,
    attendance_status TEXT,  -- '정상', '지각', '결근' 등
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);
""")
print("Table 'attendance' created.")


conn.commit()
conn.close()
