import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime

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
print("모든 테이블 생성 완료.")

# --- 4. 초기 데이터 삽입 ---

# (1) 직원 정보 (employees)
employees_data = [
    # 기존 5명
    ('25HR0001', '홍길동', '인사팀', '과장', '2025-01-10', '010-1234-5678', 'hong@company.com', '서울시 강남구', '남성', '재직', 'profile_1.jpg'),
    ('25DV0001', '김개발', '개발팀', '대리', '2025-03-15', '010-2222-3333', 'kim@company.com', '경기도 성남시', '여성', '재직', 'profile_2.jpg'),
    ('25DS0001', '이디자인', '디자인팀', '주임', '2025-02-01', '010-4444-5555', 'lee@company.com', '서울시 마포구', '여성', '재직', 'profile_3.jpg'),
    ('25MK0001', '박마케', '마케팅팀', '사원', '2025-04-20', '010-7777-8888', 'park@company.com', '인천시 연수구', '남성', '재직', 'profile_4.jpg'),
    ('admin', '시스템 관리자', '시스템', '관리자', '2025-01-01', '010-0000-0000', 'sys@company.com', '본사', '남성', '재직', 'default.jpg'),
]

'''
# ✨ 더미 직원 20명 정보 추가
dummy_departments = [d[0] for d in departments_list if d[0] != '시스템']
dummy_positions = [p[0] for p in positions_list if p[0] not in ('관리자', '팀장')] # 팀장 제외
dummy_genders = ['남성', '여성']
'''

# 부서별 카운터 초기화 (기존 ID 다음 번호부터 시작하도록)
dept_counters = {'HR': 1, 'DV': 1, 'DS': 1, 'MK': 1, 'SL': 0, 'FN': 0}

'''
for i in range(1, 21):
    emp_number = i + 4 # 기존 직원 4명 다음부터 번호 매기기
    dept = dummy_departments[(i-1) % len(dummy_departments)] # 부서를 순환하며 배정
    pos = dummy_positions[(i-1) % len(dummy_positions)]     # 직급을 순환하며 배정
    gender = dummy_genders[(i-1) % len(dummy_genders)]       # 성별을 순환하며 배정

    # 사번 생성 (예: 25SL0001, 25FN0001, 25HR0002 ...)
    dept_code = next(code for name, code in departments_list if name == dept)
    dept_counters[dept_code] += 1
    emp_id = f"25{dept_code}{dept_counters[dept_code]:04d}"

    name = f"테스트{emp_number}"
    hire_y = 2024 + (i % 2) # 입사년도 2024 또는 2025
    hire_m = (i % 12) + 1   # 입사월 1~12
    hire_d = (i % 28) + 1   # 입사일 1~28
    hire_date = f"{hire_y}-{hire_m:02d}-{hire_d:02d}"
    phone = f"010-{1000+i:04d}-{1000+i:04d}"
    email = f"test{emp_number}@company.com"
    address = f"테스트 주소 {emp_number}"
    profile_img = f"dummy_{i}.jpg" # 프로필 이미지 파일명 (실제 파일은 없음)

    employees_data.append((emp_id, name, dept, pos, hire_date, phone, email, address, gender, '재직', profile_img))
'''

cursor.executemany("""
    INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status, profile_image)
    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
""", employees_data)

# (2) 로그인 정보 (users)
users_data = [
    # 기존 5명
    ('25HR0001', '25HR0001', generate_password_hash('1234'), 'admin'),
    ('25DV0001', '25DV0001', generate_password_hash('1234'), 'user'),
    ('25DS0001', '25DS0001', generate_password_hash('1234'), 'user'),
    ('25MK0001', '25MK0001', generate_password_hash('1234'), 'user'),
    ('admin', 'admin', generate_password_hash('0000'), 'admin'),
]

# ✨ 추가된 20명에 대한 user 데이터 생성 (모두 role='user', pw='1234')
default_password_hash = generate_password_hash('1234')
for emp_data in employees_data[5:]: # 기존 5명 제외
    emp_id = emp_data[0]
    # 'admin' 계정은 이미 users_data에 있으므로 건너뜀
    if emp_id != 'admin':
        users_data.append((emp_id, emp_id, default_password_hash, 'user'))

cursor.executemany("""
    INSERT INTO users (employee_id, username, password_hash, role)
    VALUES (?, ?, ?, ?)
""", users_data)

# (3) 샘플 공지사항
cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('환영합니다!', '인사관리 시스템이 오픈되었습니다.'))

print("초기 데이터 삽입 완료.")

conn.commit()
conn.close()

print(f"데이터베이스 초기화가 성공적으로 완료되었습니다. 총 직원 수 (시스템 관리자 제외): {len(employees_data) - 1}")