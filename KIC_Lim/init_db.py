import sqlite3
from werkzeug.security import generate_password_hash 

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

# --- 기존 테이블 삭제 ---
cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("DROP TABLE IF EXISTS departments")
cursor.execute("DROP TABLE IF EXISTS positions")
cursor.execute("DROP TABLE IF EXISTS email_domains")
cursor.execute("DROP TABLE IF EXISTS attendance") 
cursor.execute("DROP TABLE IF EXISTS users") 

# --- 필수 테이블 재정의 및 데이터 추가 ---
cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO departments (name, code) VALUES (?, ?)", [
    ('인사팀', 'HR'), 
    ('개발팀', 'DV'), 
    ('디자인팀', 'DS'), 
    ('마케팅팀', 'MK')
])
cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO positions (name) VALUES (?)", [('사원',), ('주임',), ('대리',), ('과장',), ('팀장',), ('관리자',)])
cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", [('company.com',), ('gmail.com',), ('naver.com',)])

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

# --- attendance 테이블 생성 ---
cursor.execute("""
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    record_date DATE NOT NULL,
    clock_in_time DATETIME,
    clock_out_time DATETIME,
    attendance_status TEXT,
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);
""")

# ✨ [핵심 수정] users 테이블에 role 컬럼 추가
cursor.execute("""
CREATE TABLE users (
    employee_id TEXT PRIMARY KEY,
    username TEXT UNIQUE NOT NULL, 
    password_hash TEXT NOT NULL, 
    role TEXT NOT NULL DEFAULT 'staff',  -- 'admin' 또는 'staff'
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);
""")

# --- 테스트 직원 데이터 삽입 ---
# 1. 관리자 계정용 직원 (인사팀)
cursor.execute("""
    INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('25HR0001', '관리자', '인사팀', '관리자', '2025-01-01', '010-0000-0000', 'admin@company.com', '서울시', '남성'))

# 2. 일반 직원 계정용 직원 (개발팀)
cursor.execute("""
    INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender) 
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
""", ('25DV0002', '일반직원', '개발팀', '사원', '2025-03-01', '010-1111-1111', 'staff@company.com', '부산시', '여성'))


# --- 테스트 사용자 계정 삽입 ---
admin_password_hash = generate_password_hash("1234")
staff_password_hash = generate_password_hash("1111")

# ✨ [핵심 수정] 관리자 계정
cursor.execute("""
    INSERT INTO users (employee_id, username, password_hash, role)
    VALUES (?, ?, ?, ?)
""", ('25HR0001', 'admin', admin_password_hash, 'admin'))

# ✨ [핵심 수정] 일반 직원 계정
cursor.execute("""
    INSERT INTO users (employee_id, username, password_hash, role)
    VALUES (?, ?, ?, ?)
""", ('25DV0002', 'staff', staff_password_hash, 'staff'))

print("Admin user 'admin' (PW: 1234, Role: admin) and Staff user 'staff' (PW: 1111, Role: staff) created.")

conn.commit()
conn.close()
