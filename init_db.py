import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime

def init_database():
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # ---------------------------------------------------------
    # 1. 모든 테이블 삭제 (초기화) - 참조 관계 역순으로 삭제
    # ---------------------------------------------------------
    cursor.execute("DROP TABLE IF EXISTS salary_payments")
    cursor.execute("DROP TABLE IF EXISTS fixed_deductions")
    cursor.execute("DROP TABLE IF EXISTS fixed_allowances")
    cursor.execute("DROP TABLE IF EXISTS salary_contracts")
    cursor.execute("DROP TABLE IF EXISTS vacation_requests")
    cursor.execute("DROP TABLE IF EXISTS notices")
    cursor.execute("DROP TABLE IF EXISTS attendance")
    cursor.execute("DROP TABLE IF EXISTS users")
    cursor.execute("DROP TABLE IF EXISTS employees")
    cursor.execute("DROP TABLE IF EXISTS email_domains")
    cursor.execute("DROP TABLE IF EXISTS positions")
    cursor.execute("DROP TABLE IF EXISTS departments")

    print("기존 테이블 모두 삭제 완료.")

    # ---------------------------------------------------------
    # 2. 기본 설정 테이블 생성 (부서, 직급, 도메인)
    # ---------------------------------------------------------
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

    # ---------------------------------------------------------
    # 3. 인사/근태 메인 테이블 생성
    # ---------------------------------------------------------
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
    CREATE TABLE vacation_requests (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id TEXT NOT NULL,                  
        name TEXT NOT NULL,                     
        department TEXT NOT NULL,               
        request_type TEXT NOT NULL,             
        start_date TEXT NOT NULL,               
        end_date TEXT NOT NULL,                 
        reason TEXT,                            
        request_date DATETIME DEFAULT CURRENT_TIMESTAMP, 
        status TEXT NOT NULL DEFAULT '대기',      
        FOREIGN KEY (user_id) REFERENCES employees (id)
    );""")

    # ---------------------------------------------------------
    # 4. ✨ [신규] 급여 관리 전용 테이블 생성
    # ---------------------------------------------------------
    
    # (1) 연봉 계약 정보 (기본급 관리)
    cursor.execute("""
    CREATE TABLE salary_contracts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        base_salary INTEGER NOT NULL,      -- 월 기본급
        annual_salary INTEGER NOT NULL,    -- 연봉 총액
        bank_name TEXT,                    -- 급여 계좌 은행명
        account_number TEXT,               -- 급여 계좌 번호
        created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")

    # (2) 고정 수당 항목 (식대, 직책수당 등 매월 고정 지급)
    cursor.execute("""
    CREATE TABLE fixed_allowances (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        allowance_name TEXT NOT NULL,      -- 수당명
        amount INTEGER NOT NULL,           -- 금액
        is_taxable BOOLEAN DEFAULT 1,      -- 과세 여부 (1: 과세, 0: 비과세)
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")

    # (3) 고정 공제 항목 (일반적인 4대보험 외에 별도로 떼는 금액, 예: 사우회비, 가불금 상환)
    cursor.execute("""
    CREATE TABLE fixed_deductions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        deduction_name TEXT NOT NULL,      -- 공제명
        amount INTEGER NOT NULL,           -- 금액
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")

    # (4) 급여 지급 기록 (매월 확정된 급여 대장 아카이브)
    cursor.execute("""
    CREATE TABLE salary_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        employee_id TEXT NOT NULL,
        payment_year INTEGER NOT NULL,     -- 귀속 년도
        payment_month INTEGER NOT NULL,    -- 귀속 월
        payment_date DATE NOT NULL,        -- 지급일
        
        total_base INTEGER NOT NULL,       -- 기본급 지급액
        total_allowance INTEGER NOT NULL,  -- 수당 합계
        total_deduction INTEGER NOT NULL,  -- 공제 합계 (세금 + 4대보험 + 기타)
        net_salary INTEGER NOT NULL,       -- 실 수령액
        
        national_pension INTEGER DEFAULT 0, -- 국민연금
        health_insurance INTEGER DEFAULT 0, -- 건강보험
        care_insurance INTEGER DEFAULT 0,   -- 장기요양보험
        employment_insurance INTEGER DEFAULT 0, -- 고용보험
        income_tax INTEGER DEFAULT 0,       -- 소득세
        local_tax INTEGER DEFAULT 0,        -- 지방소득세
        
        is_finalized BOOLEAN DEFAULT 0,     -- 마감 여부
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")

    # (5) ✨ [신규] 급여/세금 요율 설정 테이블 (단 1개의 행만 사용)
    cursor.execute("""
    CREATE TABLE payroll_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        national_pension_rate REAL DEFAULT 4.5,    -- 국민연금 (4.5%)
        health_insurance_rate REAL DEFAULT 3.545,  -- 건강보험 (3.545%)
        care_insurance_rate REAL DEFAULT 12.95,    -- 장기요양 (건강보험의 12.95%)
        employment_insurance_rate REAL DEFAULT 0.9 -- 고용보험 (0.9%)
    );""")
    
    # 기본값 삽입 (2024/2025년 기준)
    cursor.execute("INSERT INTO payroll_rates (id) VALUES (1)")
    
    print("급여 요율 테이블 생성 완료.")

    print("모든 테이블 생성 완료.")

    # ---------------------------------------------------------
    # 5. 초기 데이터 삽입
    # ---------------------------------------------------------

    # (1) 직원 정보
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

    # (2) 로그인 정보
    users_data = [
        ('25HR0001', '25HR0001', generate_password_hash('1234'), 'admin'), # 인사팀장급은 admin 권한 부여
        ('25DV0001', '25DV0001', generate_password_hash('1234'), 'user'),
        ('25DS0001', '25DS0001', generate_password_hash('1234'), 'user'),
        ('25MK0001', '25MK0001', generate_password_hash('1234'), 'user'),
        ('admin', 'admin', generate_password_hash('0000'), 'admin'),
    ]
    cursor.executemany("""
        INSERT INTO users (employee_id, username, password_hash, role)
        VALUES (?, ?, ?, ?)
    """, users_data)

    # (3) 공지사항
    cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('환영합니다!', '인사관리 시스템이 오픈되었습니다.'))

    # (4) ✨ [신규] 급여 계약 정보 샘플 (연봉/기본급)
    salary_contracts_data = [
        ('25HR0001', 4166660, 50000000, '국민은행', '123-456-7890'), # 홍길동 (연봉 5000)
        ('25DV0001', 3333330, 40000000, '신한은행', '110-222-333333'), # 김개발 (연봉 4000)
        ('25DS0001', 2500000, 30000000, '카카오뱅크', '3333-01-1234567'), # 이디자인 (연봉 3000)
        ('admin', 5000000, 60000000, '농협', '302-1234-5678-91'), # 관리자
    ]
    cursor.executemany("""
        INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number)
        VALUES (?, ?, ?, ?, ?)
    """, salary_contracts_data)

    # (5) ✨ [신규] 고정 수당 정보 샘플
    allowance_data = [
        ('25HR0001', '식대', 200000, 0),      # 비과세
        ('25HR0001', '직책수당', 300000, 1),  # 과세
        ('25DV0001', '식대', 200000, 0),
        ('25DS0001', '식대', 200000, 0),
    ]
    cursor.executemany("""
        INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable)
        VALUES (?, ?, ?, ?)
    """, allowance_data)

    print("초기 데이터 삽입 완료.")

    conn.commit()
    conn.close()

if __name__ == '__main__':
    init_database()
    print("DB 초기화 스크립트 실행 완료.")