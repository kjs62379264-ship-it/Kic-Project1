import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta

conn = sqlite3.connect('employees.db')
cursor = conn.cursor()

# --- 1. 모든 테이블 삭제 ---
cursor.execute("DROP TABLE IF EXISTS employees")
cursor.execute("DROP TABLE IF EXISTS departments")
cursor.execute("DROP TABLE IF EXISTS positions")
cursor.execute("DROP TABLE IF EXISTS email_domains")
cursor.execute("DROP TABLE IF EXISTS attendance")
cursor.execute("DROP TABLE IF EXISTS notices")
cursor.execute("DROP TABLE IF EXISTS users")
cursor.execute("DROP TABLE IF EXISTS salary")
cursor.execute("DROP TABLE IF EXISTS allowances")
cursor.execute("DROP TABLE IF EXISTS deductions")
# ✨ [추가] 휴가 요청 테이블 삭제
cursor.execute("DROP TABLE IF EXISTS leave_requests")

print("기존 테이블 모두 삭제 완료.")

# --- 2. 기본 설정 테이블 생성 ---
departments_list = [
    ('인사팀', 'HR'), ('개발팀', 'DV'), ('디자인팀', 'DS'), ('마케팅팀', 'MK'), ('영업팀', 'SL'), ('재무팀', 'FN')
]
positions_list = [
    ('사원',), ('주임',), ('대리',), ('과장',), ('팀장',)
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
    status TEXT DEFAULT '재직' NOT NULL, profile_image TEXT
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
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
cursor.execute("""
CREATE TABLE notices (
    id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);""")
cursor.execute("""
CREATE TABLE salary (
    employee_id TEXT PRIMARY KEY,
    annual_salary INTEGER NOT NULL,
    monthly_base INTEGER NOT NULL,
    start_date DATE NOT NULL,
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
cursor.execute("""
CREATE TABLE allowances (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    is_monthly BOOLEAN NOT NULL DEFAULT 1,
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
cursor.execute("""
CREATE TABLE deductions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    employee_id TEXT NOT NULL,
    type TEXT NOT NULL,
    amount INTEGER NOT NULL,
    is_rate BOOLEAN NOT NULL DEFAULT 0,
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
# ✨ [추가] 휴가 요청 테이블
cursor.execute("""
CREATE TABLE leave_requests (
    id INTEGER PRIMARY KEY AUTOINCREMENT, 
    employee_id TEXT NOT NULL,
    leave_type TEXT NOT NULL,
    start_date DATE NOT NULL,
    end_date DATE NOT NULL,
    reason TEXT,
    request_date DATETIME DEFAULT CURRENT_TIMESTAMP,
    # '미승인', '승인', '반려'
    status TEXT NOT NULL DEFAULT '미승인', 
    FOREIGN KEY (employee_id) REFERENCES employees (id)
);""")
print("모든 테이블 생성 완료 (급여, 휴가 요청 테이블 포함).")


# --- 4. 초기 데이터 삽입 ---

# (1) 직원 정보 (employees)
employees_data = [
    ('25HR0001', '홍길동', '인사팀', '과장', '2025-01-10', '010-1234-5678', 'hong@company.com', '서울시 강남구', '남성', '재직', 'profile_5.jpg'),
    ('25DV0001', '김개발', '개발팀', '대리', '2025-03-15', '010-2222-3333', 'kim@company.com', '경기도 성남시', '여성', '재직', 'profile_2.jpg'),
    ('25DS0001', '이디자인', '디자인팀', '주임', '2025-02-01', '010-4444-5555', 'lee@company.com', '서울시 마포구', '여성', '재직', 'profile_3.jpg'),
    ('25MK0001', '박마케', '마케팅팀', '사원', '2025-04-20', '010-7777-8888', 'park@company.com', '인천시 연수구', '남성', '재직', 'profile_4.jpg'),
    ('admin', '관리자', '-', '관리자', '2025-01-01', '010-0000-0000', 'sys@company.com', '본사', '남성', '재직', 'profile_1.jpg'),
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

default_password_hash = generate_password_hash('1234')
for emp_data in employees_data[5:]: 
    emp_id = emp_data[0]
    if emp_id != 'admin':
        users_data.append((emp_id, emp_id, default_password_hash, 'user'))

cursor.executemany("""
    INSERT INTO users (employee_id, username, password_hash, role)
    VALUES (?, ?, ?, ?)
""", users_data)

# (3) 샘플 공지사항
cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('환영합니다!', '인사관리 시스템이 오픈되었습니다.'))


# (4) 급여 테이블 (salary) 초기 데이터
employees_to_salary = [emp[0] for emp in employees_data]
salary_data = []
for emp_id in employees_to_salary:
    base_salary = 60000000 if emp_id == 'admin' else 36000000
    monthly_base = base_salary // 12
    salary_data.append((emp_id, base_salary, monthly_base, '2025-01-01'))

cursor.executemany("""
    INSERT INTO salary (employee_id, annual_salary, monthly_base, start_date)
    VALUES (?, ?, ?, ?)
""", salary_data)
print("초기 급여 정보 삽입 완료.")

# (5) 수당 테이블 (allowances) 초기 데이터
allowances_data = []
for emp_id in employees_to_salary:
    allowances_data.append((emp_id, '식대', 100000, 1))
    allowances_data.append((emp_id, '교통비', 50000, 1))
    if emp_id == 'admin' or emp_id == '25HR0001':
        allowances_data.append((emp_id, '직책수당', 300000, 1))

cursor.executemany("""
    INSERT INTO allowances (employee_id, type, amount, is_monthly)
    VALUES (?, ?, ?, ?)
""", allowances_data)
print("초기 수당 정보 삽입 완료.")

# (6) 공제 테이블 (deductions) 초기 데이터
deductions_data = [
    (emp_id, '국민연금', 450, 1) for emp_id in employees_to_salary
] + [
    (emp_id, '건강보험', 3545, 1) for emp_id in employees_to_salary
] + [
    (emp_id, '고용보험', 90, 1) for emp_id in employees_to_salary
] + [
    (emp_id, '소득세', 120000, 0) for emp_id in employees_to_salary
]

cursor.executemany("""
    INSERT INTO deductions (employee_id, type, amount, is_rate)
    VALUES (?, ?, ?, ?)
""", deductions_data)
print("초기 공제 정보 삽입 완료.")

# (7) 샘플 근태 기록 (attendance) 추가
today = datetime.now().date()
yesterday = today - timedelta(days=1)
two_days_ago = today - timedelta(days=2)
three_days_ago = today - timedelta(days=3)

attendance_data = [
    ('25HR0001', yesterday.strftime('%Y-%m-%d'), '08:50:00', '18:00:00', '정상'),
    ('25HR0001', two_days_ago.strftime('%Y-%m-%d'), '09:05:00', '18:00:00', '지각'), 
    ('25DV0001', yesterday.strftime('%Y-%m-%d'), '09:03:00', '18:00:00', '지각'), 
    ('25DV0001', three_days_ago.strftime('%Y-%m-%d'), '08:45:00', '19:30:00', '정상'),
    ('25DV0001', today.strftime('%Y-%m-%d'), '08:58:00', None, '정상'), # 오늘 근무중 테스트용
]

cursor.executemany("""
    INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status)
    VALUES (?, ?, ?, ?, ?)
""", attendance_data)
print("샘플 근태 기록 삽입 완료.")


# (8) 샘플 휴가 요청 (leave_requests) 추가
vacation_data = [
    # 미승인 요청 (김개발)
    ('25DV0001', '연차', '2025-11-20', '2025-11-20', '가족 행사 참석', '미승인'),
    # 승인된 요청 (홍길동)
    ('25HR0001', '병가', '2025-12-05', '2025-12-06', '수술 후 회복', '승인'),
    # 반려된 요청 (이디자인)
    ('25DS0001', '오후 반차', '2025-11-15', '2025-11-15', '병원 검진', '반려'),
]
for emp_id, type, start, end, reason, status in vacation_data:
    cursor.execute("""
        INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, reason, status)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (emp_id, type, start, end, reason, status))
print("샘플 휴가 요청 삽입 완료.")


conn.commit()
conn.close()

print(f"데이터베이스 초기화가 성공적으로 완료되었습니다. 총 직원 수 (시스템 관리자 포함): {len(employees_data)}")