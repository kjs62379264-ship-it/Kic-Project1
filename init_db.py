import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

def init_database():
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # 1. 초기화
    tables = [
        "payroll_rates", "salary_payments", "fixed_deductions", "fixed_allowances",
        "salary_contracts", "vacation_requests", "notices", "attendance",
        "users", "employees", "email_domains", "positions", "departments"
    ]
    for table in tables:
        cursor.execute(f"DROP TABLE IF EXISTS {table}")
    print("기존 테이블 삭제 완료.")

    # 2. 기초 데이터
    departments_list = [('인사팀', 'HR'), ('개발팀', 'DV'), ('디자인팀', 'DS'), ('마케팅팀', 'MK'), ('영업팀', 'SL'), ('재무팀', 'FN')]
    positions_list = [('사원',), ('주임',), ('대리',), ('과장',), ('팀장',)]
    email_domains_list = [('company.com',), ('gmail.com',), ('naver.com',)]

    cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL, is_active BOOLEAN DEFAULT 1);")
    cursor.executemany("INSERT INTO departments (name, code) VALUES (?, ?)", departments_list)
    cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, is_active BOOLEAN DEFAULT 1);")
    cursor.executemany("INSERT INTO positions (name) VALUES (?)", positions_list)
    cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
    cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", email_domains_list)

    # 3. 메인 테이블
    cursor.execute("""
    CREATE TABLE employees (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL, position TEXT NOT NULL,
        hire_date DATE NOT NULL, birth_date DATE, 
        phone_number TEXT, email TEXT, address TEXT, gender TEXT,
        status TEXT DEFAULT '재직' NOT NULL, profile_image TEXT
    );""")
    cursor.execute("CREATE TABLE users (employee_id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password_hash TEXT NOT NULL, role TEXT NOT NULL DEFAULT 'user', FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("""
    CREATE TABLE attendance (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, record_date DATE NOT NULL, 
        clock_in_time DATETIME, clock_out_time DATETIME, attendance_status TEXT, note TEXT,
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")
    cursor.execute("CREATE TABLE notices (id INTEGER PRIMARY KEY AUTOINCREMENT, title TEXT NOT NULL, content TEXT NOT NULL, created_at DATETIME DEFAULT CURRENT_TIMESTAMP);")
    cursor.execute("CREATE TABLE vacation_requests (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id TEXT NOT NULL, name TEXT NOT NULL, department TEXT NOT NULL, request_type TEXT NOT NULL, start_date TEXT NOT NULL, end_date TEXT NOT NULL, reason TEXT, request_date DATETIME DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL DEFAULT '대기', FOREIGN KEY (user_id) REFERENCES employees (id));")

    # 4. 급여 테이블 (✅ 스키마 수정됨)
    cursor.execute("CREATE TABLE salary_contracts (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, base_salary INTEGER NOT NULL, annual_salary INTEGER NOT NULL, bank_name TEXT, account_number TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("CREATE TABLE fixed_allowances (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, allowance_name TEXT NOT NULL, amount INTEGER NOT NULL, is_taxable BOOLEAN DEFAULT 1, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("CREATE TABLE fixed_deductions (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, deduction_name TEXT NOT NULL, amount INTEGER NOT NULL, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    
    # ✅ [수정] salary_payments 테이블 컬럼 세분화
    cursor.execute("""
    CREATE TABLE salary_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, 
        employee_id TEXT NOT NULL, 
        payment_year INTEGER NOT NULL, 
        payment_month INTEGER NOT NULL, 
        payment_date DATE NOT NULL,
        
        total_base INTEGER NOT NULL,          -- 기본급
        
        allowance_other INTEGER DEFAULT 0,    -- ✅ 기타 수당 (기존 수당 합계)
        allowance_extended INTEGER DEFAULT 0, -- ✅ 연장 근무 수당
        allowance_night INTEGER DEFAULT 0,    -- ✅ 야간 근무 수당
        total_allowance INTEGER NOT NULL,     -- 수당 총합 (표시용)
        
        deduction_other INTEGER DEFAULT 0,    -- ✅ 기타 공제
        
        national_pension INTEGER DEFAULT 0, 
        health_insurance INTEGER DEFAULT 0, 
        care_insurance INTEGER DEFAULT 0, 
        employment_insurance INTEGER DEFAULT 0, 
        income_tax INTEGER DEFAULT 0, 
        local_tax INTEGER DEFAULT 0,
        
        total_deduction INTEGER NOT NULL,     -- 공제 총액
        net_salary INTEGER NOT NULL,          -- 실 수령액
        is_finalized BOOLEAN DEFAULT 0, 
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")
    
    cursor.execute("CREATE TABLE payroll_rates (id INTEGER PRIMARY KEY AUTOINCREMENT, national_pension_rate REAL DEFAULT 4.5, health_insurance_rate REAL DEFAULT 3.545, care_insurance_rate REAL DEFAULT 12.95, employment_insurance_rate REAL DEFAULT 0.9);")
    cursor.execute("INSERT INTO payroll_rates (id) VALUES (1)")

    # 5. 직원 데이터
    employees_data = [
        ('admin', '홍길동', '-', '관리자', '2025-01-01', '1985-01-01', '010-0000-0000', 'sys@company.com', '본사', '남성', '재직', 'profile_1.jpg'),
        ('25HR0001', '임찬규', '인사팀', '과장', '2025-01-10', '1992-11-20', '010-1234-5678', 'lim@company.com', '서울시 강남구', '남성', '재직', 'default.jpg'),
        ('25HR0002', '박지성', '인사팀', '팀장', '2025-01-02', '1981-02-25', '010-1000-0001', 'park@company.com', '서울시 강남구', '남성', '재직', 'default.jpg'),
        ('25HR0003', '김연경', '인사팀', '과장', '2025-02-10', '1988-02-26', '010-4000-0004', 'kimyk@company.com', '경기도 안산시', '여성', '재직', 'default.jpg'),
        ('25HR0004', '장미란', '인사팀', '대리', '2025-02-15', '1983-10-09', '010-8000-0008', 'rose@company.com', '경기도 고양시', '여성', '재직', 'default.jpg'),
        ('25HR0005', '차범근', '인사팀', '팀장', '2025-01-01', '1953-05-22', '010-8888-0017', 'cha@company.com', '경기도 화성시', '남성', '재직', 'default.jpg'),
        ('25DV0001', '김동현', '개발팀', '대리', '2025-03-15', '1981-11-17', '010-2222-3333', 'kimdh@company.com', '경기도 성남시', '남성', '재직', 'default.jpg'),
        ('25DV0002', '이상화', '개발팀', '과장', '2025-03-01', '1989-02-25', '010-6000-0006', 'lee@company.com', '서울시 동대문구', '여성', '재직', 'default.jpg'),
        ('25DV0003', '윤성빈', '개발팀', '대리', '2025-04-01', '1994-05-23', '010-9000-0009', 'yun@company.com', '경상남도 남해군', '남성', '재직', 'default.jpg'),
        ('25DV0004', '안세영', '개발팀', '주임', '2025-04-01', '2002-02-05', '010-3434-0020', 'ahnsy@company.com', '광주광역시', '여성', '재직', 'default.jpg'),
        ('25DV0005', '조구함', '개발팀', '주임', '2025-04-01', '1992-07-30', '010-5566-7788', 'cho@company.com', '강원도 춘천시', '남성', '재직', 'default.jpg'),
        ('25DS0001', '이승엽', '디자인팀', '주임', '2025-02-01', '1976-08-18', '010-4444-5555', 'leesy@company.com', '서울시 마포구', '남성', '재직', 'default.jpg'),
        ('25DS0002', '김제덕', '디자인팀', '사원', '2025-05-01', '2004-04-12', '010-2222-0011', 'duck@company.com', '경상북도 예천군', '남성', '재직', 'default.jpg'),
        ('25DS0003', '안산', '디자인팀', '주임', '2025-04-15', '2001-02-27', '010-3333-0012', 'ansan@company.com', '광주광역시 북구', '여성', '재직', 'default.jpg'),
        ('25DS0004', '여서정', '디자인팀', '주임', '2025-04-20', '2002-02-20', '010-7777-0016', 'yeo@company.com', '경기도 용인시', '여성', '재직', 'default.jpg'),
        ('25MK0001', '박찬호', '마케팅팀', '사원', '2025-04-20', '1973-06-29', '010-7777-8888', 'parkch@company.com', '인천시 연수구', '남성', '재직', 'default.jpg'),
        ('25MK0002', '김연아', '마케팅팀', '팀장', '2025-01-05', '1990-09-05', '010-2000-0002', 'yuna@company.com', '경기도 군포시', '여성', '재직', 'default.jpg'),
        ('25MK0003', '신유빈', '마케팅팀', '사원', '2025-05-10', '2004-07-05', '010-4444-0013', 'shin@company.com', '경기도 수원시', '여성', '재직', 'default.jpg'),
        ('25MK0004', '우상혁', '마케팅팀', '대리', '2025-03-20', '1996-04-23', '010-6666-0015', 'woo@company.com', '대전광역시 대덕구', '남성', '재직', 'default.jpg'),
        ('25MK0005', '허웅', '마케팅팀', '주임', '2025-04-05', '1993-08-05', '010-1212-0019', 'heo@company.com', '서울시 용산구', '남성', '재직', 'default.jpg'),
        ('25SL0001', '손흥민', '영업팀', '과장', '2025-02-01', '1992-07-08', '010-3000-0003', 'son@company.com', '강원도 춘천시', '남성', '재직', 'default.jpg'),
        ('25SL0002', '이정후', '영업팀', '대리', '2025-03-05', '1998-08-20', '010-7000-0007', 'hoo@company.com', '광주광역시 서구', '남성', '재직', 'default.jpg'),
        ('25SL0003', '황선우', '영업팀', '사원', '2025-05-12', '2003-05-21', '010-5555-0014', 'hwang@company.com', '경기도 수원시', '남성', '재직', 'default.jpg'),
        ('25SL0004', '김하성', '영업팀', '대리', '2025-03-10', '1995-10-17', '010-9999-0018', 'ha@company.com', '경기도 부천시', '남성', '재직', 'default.jpg'),
        ('25FN0001', '박세리', '재무팀', '팀장', '2025-01-01', '1977-09-28', '010-5000-0005', 'seri@company.com', '대전광역시 유성구', '여성', '재직', 'default.jpg'),
        ('25FN0002', '류현진', '재무팀', '과장', '2025-01-20', '1987-03-25', '010-1111-0010', 'ryu@company.com', '인천광역시 동구', '남성', '재직', 'default.jpg'),
    ]
    cursor.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", employees_data)

    users_data = []
    for emp in employees_data:
        role = 'admin' if emp[0] == 'admin' else 'user'
        users_data.append((emp[0], emp[0], generate_password_hash('1234'), role))
    cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users_data)

    cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('환영합니다!', '인사관리 시스템이 오픈되었습니다.'))
    cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", ('[필독] 12월 급여 지급 안내', '12월 급여는 10일(화)에 지급됩니다.'))

# ---------------------------------------------------------
    # 6. 급여 계약 및 수당 (데이터 저장)
    # ---------------------------------------------------------
    salary_base = {'사원': 32000000, '주임': 38000000, '대리': 45000000, '과장': 55000000, '팀장': 70000000, '관리자': 80000000}
    
    # ✅ [수정] 랜덤 은행 및 계좌번호 생성
    banks = ['국민은행', '신한은행', '우리은행', '하나은행', '농협', '카카오뱅크']
    
    salary_contracts_data = []
    allowance_data = []
    emp_salary_map = {} 

    for emp in employees_data:
        emp_id = emp[0]; pos = emp[3]
        
        # 연봉 계산
        base_annual = salary_base.get(pos, 30000000)
        annual = base_annual + (random.randint(0, 50) * 100000)
        monthly_base = annual // 12
        
        # ✅ [핵심] 랜덤 은행/계좌 생성
        bank = random.choice(banks)
        # 계좌번호 형식: XXX-XXXX-XXXXXX (랜덤)
        acc_num = f"{random.randint(100, 999)}-{random.randint(1000, 9999)}-{random.randint(100000, 999999)}"
        
        salary_contracts_data.append((emp_id, monthly_base, annual, bank, acc_num))
        
        # 수당 계산
        fixed_allowance = 200000 # 식대 기본
        allowance_data.append((emp_id, '식대', 200000, 0))
        
        if pos in ['과장', '팀장', '관리자']: 
            allowance_data.append((emp_id, '직책수당', 300000, 1))
            fixed_allowance += 300000
            
        emp_salary_map[emp_id] = {'base': monthly_base, 'fixed_allowance': fixed_allowance}

    cursor.executemany("INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number) VALUES (?, ?, ?, ?, ?)", salary_contracts_data)
    cursor.executemany("INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable) VALUES (?, ?, ?, ?)", allowance_data)

    # ---------------------------------------------------------
    # ⭐ [핵심] 2025년 급여 이력 자동 생성 (2월 ~ 12월) - 매달 다르게!
    # ---------------------------------------------------------
    print("급여 이력 데이터 생성 중 (2월~12월)...")
    salary_history_data = []

    for emp_id, info in emp_salary_map.items():
        base = info['base']
        fixed_allowance = info['fixed_allowance'] # 고정 수당 (식대+직책)
        
        # 2월부터 12월까지 반복
        for month in range(2, 13):
            payment_date = f"2025-{month:02d}-10"
            
            # ✅ [다양성] 매달 달라지는 수당 생성
            # 1. 연장 근무 수당 (0 ~ 20만원 랜덤)
            ext_pay = random.randint(0, 4) * 50000 
            
            # 2. 야간 근무 수당 (0 ~ 10만원 랜덤)
            night_pay = random.randint(0, 2) * 50000
            
            # 3. 기타 수당 (고정수당 + 랜덤 보너스 0~5만원)
            other_pay = fixed_allowance + (random.randint(0, 5) * 10000)

            # 관리자는 수당 적게 (품위유지?)
            if emp_id == 'admin': 
                ext_pay = 0; night_pay = 0; other_pay = fixed_allowance

            total_allowance = other_pay + ext_pay + night_pay
            gross_salary = base + total_allowance
            
            # ✅ [다양성] 기타 공제 (커피값, 동호회비 등 소액 랜덤)
            deduction_other = random.randint(0, 3) * 5000 
            
            # 공제 계산
            pension = int(gross_salary * 0.045)
            health = int(gross_salary * 0.03545)
            care = int(health * 0.1295)
            employment = int(gross_salary * 0.009)
            
            tax_base = gross_salary - 1000000
            if tax_base < 0: tax_base = 0
            income_tax = int(tax_base * 0.03) 
            local_tax = int(income_tax * 0.1)
            
            total_deduction = pension + health + care + employment + income_tax + local_tax + deduction_other
            
            # 10원 단위 절사
            total_deduction = (total_deduction // 10) * 10
            net_salary = gross_salary - total_deduction
            
            # 데이터 추가 (새 컬럼들 포함)
            salary_history_data.append((
                emp_id, 2025, month, payment_date,
                base, 
                other_pay, ext_pay, night_pay, total_allowance, # 수당 상세
                deduction_other, # 기타 공제
                pension, health, care, employment, income_tax, local_tax,
                total_deduction, net_salary, 1
            ))

    cursor.executemany("""
        INSERT INTO salary_payments (
            employee_id, payment_year, payment_month, payment_date,
            total_base, 
            allowance_other, allowance_extended, allowance_night, total_allowance,
            deduction_other,
            national_pension, health_insurance, care_insurance, employment_insurance, income_tax, local_tax,
            total_deduction, net_salary, is_finalized
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, salary_history_data)


    # ---------------------------------------------------------
    # 근태 데이터 생성 (11월 & 12월)
    # ---------------------------------------------------------
    print("근태 데이터 생성 중...")
    mock_attendance = []
    
    today_assignments = {}
    shuffled_ids = [e[0] for e in employees_data]
    random.shuffle(shuffled_ids)
    for i, eid in enumerate(shuffled_ids):
        if i < 2: today_assignments[eid] = '휴가'
        elif i < 5: today_assignments[eid] = '외근'
        elif i < 6: today_assignments[eid] = '부재'
        else: today_assignments[eid] = '정상'

    for month in [11, 12]:
        if month == 11: last_day = 30
        else: last_day = 11 

        for emp_id in [e[0] for e in employees_data]:
            seed_val = sum(ord(c) for c in emp_id) + month
            random.seed(seed_val)

            for day in range(1, last_day + 1):
                current_date = datetime(2025, month, day).date()
                date_str = current_date.strftime('%Y-%m-%d')
                weekday = current_date.weekday()

                cin = None; cout = None; status = '정상'; note = ''

                if month == 12 and day == 11:
                    assigned = today_assignments.get(emp_id, '정상')
                    if assigned == '휴가': status='휴가'; cin=None; cout=None; note='연차'
                    elif assigned == '외근': status='외근'; cin='09:00:00'; cout=None; note='외근'
                    elif assigned == '부재': status='부재'; cin=None; cout=None
                    else: status='정상'; cin='08:50:00'; cout=None
                else:
                    if weekday >= 5:
                        if random.random() < 0.05: cin='09:00:00'; cout='16:00:00'; status='정상'; note='주말 근무'
                        else: continue
                    else:
                        r = random.random()
                        if r < 0.03: status='휴가'; cin=None; cout=None; note='연차'
                        elif r < 0.08: status='지각'; cin=f"09:{random.randint(1,30):02d}:00"; cout='18:00:00'
                        else:
                            status='정상'; cin='09:00:00'
                            r_out = random.random()
                            if r_out < 0.2: cout=f"19:{random.randint(0,59):02d}:00"; note='연장 근무'
                            else: cout=f"18:{random.randint(0,10):02d}:00"
                
                mock_attendance.append((emp_id, date_str, cin, cout, status, note))

    cursor.executemany("INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status, note) VALUES (?, ?, ?, ?, ?, ?)", mock_attendance)

    vacation_data = [
        ('25DV0001', '김동현', '개발팀', '연차', '2025-11-20', '2025-11-20', '개인 사정', '승인'),
        ('25HR0001', '임찬규', '인사팀', '병가', '2025-12-05', '2025-12-06', '건강 검진', '승인'),
        ('25DS0001', '이승엽', '디자인팀', '오후 반차', '2025-11-15', '2025-11-15', '은행 업무', '반려'),
        ('25MK0002', '김연아', '마케팅팀', '연차', '2025-12-24', '2025-12-26', '크리스마스 휴가', '대기'),
        ('25SL0001', '손흥민', '영업팀', '출장', '2025-11-25', '2025-11-28', '부산 지사 미팅', '승인'),
    ]
    for v in vacation_data:
        cursor.execute("INSERT INTO vacation_requests (user_id, name, department, request_type, start_date, end_date, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", v)

    conn.commit(); conn.close()
    print("DB 초기화 완료.")

if __name__ == '__main__':
    init_database()