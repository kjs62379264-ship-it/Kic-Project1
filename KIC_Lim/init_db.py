import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, date, timedelta

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

# --- 1. 모든 테이블 삭제 (새로 추가된 테이블 포함) ---
cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("DROP TABLE IF EXISTS departments")
cursor.execute("DROP TABLE IF EXISTS positions")
cursor.execute("DROP TABLE IF EXISTS email_domains")
cursor.execute("DROP TABLE IF EXISTS attendance")
cursor.execute("DROP TABLE IF EXISTS notices")
cursor.execute("DROP TABLE IF EXISTS users")
cursor.execute("DROP TABLE IF EXISTS salaries")
cursor.execute("DROP TABLE IF EXISTS payroll_records")
cursor.execute("DROP TABLE IF EXISTS leave_requests") # ✨ 근태 요청 테이블

print("기존 테이블 모두 삭제 완료.")

# --- 2. 기본 설정 테이블 생성 ---
departments_list = [
    ('인사팀', 'HR'), ('개발팀', 'DV'), ('디자인팀', 'DS'), ('마케팅팀', 'MK'), ('영업팀', 'SL'), ('재무팀', 'FN'), ('시스템', 'SYS')
]
positions_list = [
    ('사원',), ('주임',), ('대리',), ('과장',), ('팀장',), ('관리자',)
]
email_domains_list = [
    ('company.com',), ('gmail.com',), ('naver.com',), ('kakao.com',)
]

cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO departments (name, code) VALUES (?, ?)", departments_list)
cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO positions (name) VALUES (?)", positions_list)
cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", email_domains_list)

# --- 3. 메인 테이블 생성 ---
cursor.execute("""
CREATE TABLE employees (
    id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL, position TEXT NOT NULL,
    hire_date DATE NOT NULL, phone_number TEXT, email TEXT, address TEXT, gender TEXT,
    status TEXT DEFAULT '재직' NOT NULL, profile_image TEXT DEFAULT 'default.jpg' 
);""")
cursor.execute("""
CREATE TABLE users (
    employee_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL,
    role TEXT NOT NULL DEFAULT 'user', FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
cursor.execute("""
CREATE TABLE attendance (
    id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, record_date DATE NOT NULL,
    clock_in_time DATETIME, clock_out_time DATETIME, attendance_status TEXT,
    UNIQUE (employee_id, record_date),
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
cursor.execute("""
CREATE TABLE notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);""")
cursor.execute("""
CREATE TABLE salaries (
    employee_id TEXT PRIMARY KEY,
    base_salary INTEGER NOT NULL,
    contract_type TEXT NOT NULL,
    payment_cycle TEXT NOT NULL,
    allowance INTEGER DEFAULT 0,
    tax_rate REAL DEFAULT 0.05,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
""")
cursor.execute("""
CREATE TABLE payroll_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    pay_date TEXT NOT NULL, -- YYYY-MM 형식으로 저장
    gross_pay INTEGER NOT NULL,
    deductions INTEGER NOT NULL,
    net_pay INTEGER NOT NULL,
    bonus INTEGER DEFAULT 0,
    allowance INTEGER DEFAULT 0, -- 수당 기록
    memo TEXT,
    UNIQUE (employee_id, pay_date),
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
""")
cursor.execute("""
CREATE TABLE leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    request_type TEXT NOT NULL, -- '연차', '오전 반차', '외근', '출장' 등
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    status TEXT DEFAULT '미승인' NOT NULL, -- '미승인', '승인', '반려'
    requested_at DATETIME DEFAULT CURRENT_TIMESTAMP,
    FOREIGN KEY (employee_id) REFERENCES employees(id)
);
""")
print("모든 테이블 생성 완료.")

# --- 4. 초기 데이터 삽입 ---

# (1) 직원 정보 (employees) - 모든 사진을 profile_1.jpg로 통일
employees_data = [
    ('25HR0001', '홍길동', '인사팀', '과장', '2025-01-10', '010-1234-5678', 'hong@company.com', '서울시 강남구', '남성', '재직', 'profile_1.jpg'),
    ('25DV0001', '김개발', '개발팀', '대리', '2025-03-15', '010-2222-3333', 'kim@company.com', '경기도 성남시', '여성', '재직', 'profile_1.jpg'),
    ('25DS0001', '이디자인', '디자인팀', '주임', '2025-02-01', '010-4444-5555', 'lee@company.com', '서울시 마포구', '여성', '재직', 'profile_1.jpg'),
    ('25MK0001', '박마케', '마케팅팀', '사원', '2025-04-20', '010-7777-8888', 'park@company.com', '인천시 연수구', '남성', '재직', 'profile_1.jpg'),
    ('admin', '시스템 관리자', '시스템', '관리자', '2025-01-01', '010-0000-0000', 'sys@company.com', '본사', '남성', '재직', 'default.jpg'),
]
cursor.executemany("""
    INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status, profile_image)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", employees_data)

# (2) 로그인 정보 (users)
users_data = [
    ('25HR0001', '25HR0001', generate_password_hash('1234'), 'admin'),
    ('25DV0001', '25DV0001', generate_password_hash('1234'), 'user'),
    ('25DS0001', '25DS0001', generate_password_hash('1234'), 'user'),
    ('25MK0001', '25MK0001', generate_password_hash('1234'), 'user'),
    ('admin', 'admin', generate_password_hash('0000'), 'admin'),
]
cursor.executemany("""
    INSERT INTO users (employee_id, username, password_hash, role)
    VALUES (?, ?, ?, ?)
""", users_data)

# (3) 샘플 기본 급여 정보 (salaries)
salaries_data = [
    ('25HR0001', 50000000, '정규직', '월급', 200000, 0.08), 
    ('25DV0001', 45000000, '정규직', '월급', 200000, 0.07), 
    ('25DS0001', 35000000, '정규직', '월급', 150000, 0.05), 
    ('25MK0001', 30000000, '계약직', '월급', 150000, 0.05), 
]
cursor.executemany("""
    INSERT INTO salaries (employee_id, base_salary, contract_type, payment_cycle, allowance, tax_rate)
    VALUES (?, ?, ?, ?, ?, ?)
""", salaries_data)

# (4) 샘플 공지사항
cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('[중요] 인사관리 시스템 업데이트 안내', '2025년 11월부로 근태 및 급여 관리 시스템이 전면 개편됩니다. 직원의 근태 요청은 시스템을 통해 진행해 주시기 바랍니다. 문의 사항은 인사팀으로 연락주세요.'))

# (5) 샘플 근태 요청 (leave_requests)
today = date.today().strftime('%Y-%m-%d')
future_date = (date.today() + timedelta(days=7)).strftime('%Y-%m-%d')

leave_requests_data = [
    ('25DV0001', '연차', future_date, future_date, '개인 일정'), # 미승인으로 남김
    ('25MK0001', '외근', today, today, '외부 미팅'), # 승인
    ('25DS0001', '오후 반차', today, today, '병원 방문'), # 승인
]
for emp_id, req_type, s_date, e_date, reason in leave_requests_data:
    status = '승인' if req_type not in ['연차'] else '미승인'
    cursor.execute("""
        INSERT INTO leave_requests (employee_id, request_type, start_date, end_date, reason, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (emp_id, req_type, s_date, e_date, reason, status))


print("초기 데이터 삽입 완료.")

conn.commit()
conn.close()

print(f"데이터베이스 초기화가 성공적으로 완료되었습니다. 총 직원 수 (시스템 관리자 제외): {len(employees_data) - 1}")