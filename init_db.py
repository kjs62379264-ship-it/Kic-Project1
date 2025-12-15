import sqlite3
from werkzeug.security import generate_password_hash
from datetime import datetime, timedelta
import random

# 주말이면 직전 금요일로 지급일 변경
def get_pay_date(year, month):
    target_date = datetime(year, month, 25)
    if target_date.weekday() == 5: return (target_date - timedelta(days=1)).strftime("%Y-%m-%d")
    elif target_date.weekday() == 6: return (target_date - timedelta(days=2)).strftime("%Y-%m-%d")
    return target_date.strftime("%Y-%m-%d")

def init_database():
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # 1. 초기화
    tables = [
        "payroll_rates", "salary_payments", "fixed_deductions", "fixed_allowances",
        "salary_contracts", "vacation_requests", "notices", "attendance",
        "users", "employees", "email_domains", "positions", "departments"
    ]
    for table in tables: cursor.execute(f"DROP TABLE IF EXISTS {table}")
    print("기존 테이블 삭제 완료.")

    # 2. 기초 데이터 (부서/직급 등)
    departments_list = [('인사팀', 'HR'), ('개발팀', 'DV'), ('디자인팀', 'DS'), ('마케팅팀', 'MK'), ('영업팀', 'SL'), ('재무팀', 'FN')]
    positions_list = [('사원',), ('주임',), ('대리',), ('과장',), ('팀장',)]
    email_domains_list = [('company.com',), ('gmail.com',), ('naver.com',)]

    cursor.execute("CREATE TABLE departments (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, code TEXT UNIQUE NOT NULL, is_active BOOLEAN DEFAULT 1);")
    cursor.executemany("INSERT INTO departments (name, code) VALUES (?, ?)", departments_list)
    cursor.execute("CREATE TABLE positions (id INTEGER PRIMARY KEY, name TEXT UNIQUE NOT NULL, is_active BOOLEAN DEFAULT 1);")
    cursor.executemany("INSERT INTO positions (name) VALUES (?)", positions_list)
    cursor.execute("CREATE TABLE email_domains (id INTEGER PRIMARY KEY, domain TEXT UNIQUE NOT NULL);")
    cursor.executemany("INSERT INTO email_domains (domain) VALUES (?)", email_domains_list)

    # 3. 테이블 생성
    cursor.execute("""
    CREATE TABLE employees (
        id TEXT PRIMARY KEY, name TEXT NOT NULL, department TEXT NOT NULL, position TEXT NOT NULL,
        hire_date DATE NOT NULL, birth_date DATE, phone_number TEXT, email TEXT, address TEXT, gender TEXT,
        status TEXT DEFAULT '재직' NOT NULL, profile_image TEXT, has_vehicle BOOLEAN DEFAULT 0
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
    
    cursor.execute("CREATE TABLE salary_contracts (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, base_salary INTEGER NOT NULL, annual_salary INTEGER NOT NULL, bank_name TEXT, account_number TEXT, created_at DATETIME DEFAULT CURRENT_TIMESTAMP, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("CREATE TABLE fixed_allowances (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, allowance_name TEXT NOT NULL, amount INTEGER NOT NULL, is_taxable BOOLEAN DEFAULT 1, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("CREATE TABLE fixed_deductions (id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, deduction_name TEXT NOT NULL, amount INTEGER NOT NULL, FOREIGN KEY (employee_id) REFERENCES employees (id));")
    cursor.execute("""
    CREATE TABLE salary_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT, employee_id TEXT NOT NULL, payment_year INTEGER NOT NULL, payment_month INTEGER NOT NULL, payment_date DATE NOT NULL,
        total_base INTEGER NOT NULL, allowance_other INTEGER DEFAULT 0, allowance_extended INTEGER DEFAULT 0, allowance_night INTEGER DEFAULT 0, total_allowance INTEGER NOT NULL,
        deduction_other INTEGER DEFAULT 0, national_pension INTEGER DEFAULT 0, health_insurance INTEGER DEFAULT 0, care_insurance INTEGER DEFAULT 0, employment_insurance INTEGER DEFAULT 0, income_tax INTEGER DEFAULT 0, local_tax INTEGER DEFAULT 0,
        total_deduction INTEGER NOT NULL, net_salary INTEGER NOT NULL, is_finalized BOOLEAN DEFAULT 0, 
        FOREIGN KEY (employee_id) REFERENCES employees (id)
    );""")
    cursor.execute("CREATE TABLE payroll_rates (id INTEGER PRIMARY KEY AUTOINCREMENT, national_pension_rate REAL DEFAULT 4.5, health_insurance_rate REAL DEFAULT 3.545, care_insurance_rate REAL DEFAULT 12.95, employment_insurance_rate REAL DEFAULT 0.9);")
    cursor.execute("INSERT INTO payroll_rates (id) VALUES (1)")

    # 4. 직원 데이터
    employees_data = [
        ('admin', '홍길동', '인사팀', '관리자', '2025-01-01', '1985-01-01', '010-0000-0000', 'sys@company.com', '본사', '남성', '재직', 'default.jpg', 1),
        ('25HR0001', '임찬규', '인사팀', '과장', '2025-01-10', '1992-11-20', '010-1234-5678', 'lim@company.com', '서울시 강남구', '남성', '재직', 'default.jpg', 0),
        ('25HR0002', '박지성', '인사팀', '팀장', '2025-01-02', '1981-02-25', '010-1000-0001', 'park@company.com', '서울시 강남구', '남성', '재직', 'default.jpg', 0),
        ('25HR0003', '김연경', '인사팀', '과장', '2025-02-10', '1988-02-26', '010-4000-0004', 'kimyk@company.com', '경기도 안산시', '여성', '재직', 'default.jpg', 0),
        ('25HR0004', '장미란', '인사팀', '대리', '2025-02-15', '1983-10-09', '010-8000-0008', 'rose@company.com', '경기도 고양시', '여성', '재직', 'default.jpg', 0),
        ('25HR0005', '차범근', '인사팀', '팀장', '2025-01-01', '1953-05-22', '010-8888-0017', 'cha@company.com', '경기도 화성시', '남성', '재직', 'default.jpg', 0),
        ('25DV0001', '김동현', '개발팀', '대리', '2025-03-15', '1981-11-17', '010-2222-3333', 'kimdh@company.com', '경기도 성남시', '남성', '재직', 'default.jpg', 0),
        ('25DV0002', '이상화', '개발팀', '과장', '2025-03-01', '1989-02-25', '010-6000-0006', 'lee@company.com', '서울시 동대문구', '여성', '재직', 'default.jpg', 0),
        ('25DV0003', '윤성빈', '개발팀', '대리', '2025-04-01', '1994-05-23', '010-9000-0009', 'yun@company.com', '경상남도 남해군', '남성', '재직', 'default.jpg', 0),
        ('25DV0004', '안세영', '개발팀', '주임', '2025-04-01', '2002-02-05', '010-3434-0020', 'ahnsy@company.com', '광주광역시', '여성', '재직', 'default.jpg', 0),
        ('25DV0005', '조구함', '개발팀', '주임', '2025-04-01', '1992-07-30', '010-5566-7788', 'cho@company.com', '강원도 춘천시', '남성', '재직', 'default.jpg', 0),
        ('25DS0001', '이승엽', '디자인팀', '주임', '2025-02-01', '1976-08-18', '010-4444-5555', 'leesy@company.com', '서울시 마포구', '남성', '재직', 'default.jpg', 1),
        ('25DS0002', '김제덕', '디자인팀', '사원', '2025-05-01', '2004-04-12', '010-2222-0011', 'duck@company.com', '경상북도 예천군', '남성', '재직', 'default.jpg', 0),
        ('25DS0003', '안산', '디자인팀', '주임', '2025-04-15', '2001-02-27', '010-3333-0012', 'ansan@company.com', '광주광역시 북구', '여성', '재직', 'default.jpg', 0),
        ('25DS0004', '여서정', '디자인팀', '주임', '2025-04-20', '2002-02-20', '010-7777-0016', 'yeo@company.com', '경기도 용인시', '여성', '재직', 'default.jpg', 0),
        ('25MK0001', '박찬호', '마케팅팀', '사원', '2025-04-20', '1973-06-29', '010-7777-8888', 'parkch@company.com', '인천시 연수구', '남성', '재직', 'default.jpg', 0),
        ('25MK0002', '김연아', '마케팅팀', '팀장', '2025-01-05', '1990-09-05', '010-2000-0002', 'yuna@company.com', '경기도 군포시', '여성', '재직', 'default.jpg', 0),
        ('25MK0003', '신유빈', '마케팅팀', '사원', '2025-05-10', '2004-07-05', '010-4444-0013', 'shin@company.com', '경기도 수원시', '여성', '재직', 'default.jpg', 0),
        ('25MK0004', '우상혁', '마케팅팀', '대리', '2025-03-20', '1996-04-23', '010-6666-0015', 'woo@company.com', '대전광역시 대덕구', '남성', '재직', 'default.jpg', 0),
        ('25MK0005', '허웅', '마케팅팀', '주임', '2025-04-05', '1993-08-05', '010-1212-0019', 'heo@company.com', '서울시 용산구', '남성', '재직', 'default.jpg', 0),
        ('25SL0001', '손흥민', '영업팀', '과장', '2025-02-01', '1992-07-08', '010-3000-0003', 'son@company.com', '강원도 춘천시', '남성', '재직', 'default.jpg', 0),
        ('25SL0002', '이정후', '영업팀', '대리', '2025-03-05', '1998-08-20', '010-7000-0007', 'hoo@company.com', '광주광역시 서구', '남성', '재직', 'default.jpg', 0),
        ('25SL0003', '황선우', '영업팀', '사원', '2025-05-12', '2003-05-21', '010-5555-0014', 'hwang@company.com', '경기도 수원시', '남성', '재직', 'default.jpg', 0),
        ('25SL0004', '김하성', '영업팀', '대리', '2025-03-10', '1995-10-17', '010-9999-0018', 'ha@company.com', '경기도 부천시', '남성', '재직', 'default.jpg', 0),
        ('25FN0001', '박세리', '재무팀', '팀장', '2025-01-01', '1977-09-28', '010-5000-0005', 'seri@company.com', '대전광역시 유성구', '여성', '재직', 'default.jpg', 0),
        ('25FN0002', '류현진', '재무팀', '과장', '2025-01-20', '1987-03-25', '010-1111-0010', 'ryu@company.com', '인천광역시 동구', '남성', '재직', 'default.jpg', 0),
    ]
    cursor.executemany("INSERT INTO employees VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", employees_data)

    # 사용자 계정
    users_data = []
    for emp in employees_data:
        role = 'admin' if emp[0] == 'admin' else 'user'
        users_data.append((emp[0], emp[0], generate_password_hash('1234'), role))
    cursor.executemany("INSERT INTO users VALUES (?, ?, ?, ?)", users_data)

    # 5. 공지사항
    notices_data = [
        ('환영합니다!', '인사관리 시스템이 오픈되었습니다.', '2025-12-01 09:00:00'),
        ('[필독] 12월 급여 지급 안내', '12월 급여는 25일(목)에 지급됩니다.', '2025-12-05 14:30:00'),
        ('[공지] 2025년 연말정산 미리보기 오픈', '홈택스에서 확인하세요.', '2025-12-10 17:00:00')
    ]
    cursor.executemany("INSERT INTO notices (title, content, created_at) VALUES (?, ?, ?)", notices_data)

    # 6. 급여 계약 및 수당
    salary_base = {'사원': 32000000, '주임': 38000000, '대리': 45000000, '과장': 55000000, '팀장': 70000000, '관리자': 80000000}
    salary_contracts_data = []; allowance_data = []; emp_salary_map = {}
    banks = ['국민은행', '신한은행', '농협', '카카오뱅크']

    for emp in employees_data:
        emp_id, pos, has_vehicle = emp[0], emp[3], emp[12]
        base_annual = salary_base.get(pos, 30000000)
        monthly_base = base_annual // 12
        salary_contracts_data.append((emp_id, monthly_base, base_annual, random.choice(banks), f"{random.randint(100,999)}-{random.randint(1000,9999)}"))
        
        fixed_sum = 0
        allowance_data.append((emp_id, '식대', 200000, 0))
        fixed_sum += 200000
        if has_vehicle:
            allowance_data.append((emp_id, '자가운전보조금', 200000, 0))
            fixed_sum += 200000
        if pos in ['과장', '팀장', '관리자']:
            allowance_data.append((emp_id, '직책수당', 300000, 1))
            fixed_sum += 300000
        emp_salary_map[emp_id] = {'base': monthly_base, 'fixed': fixed_sum}

    cursor.executemany("INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number) VALUES (?, ?, ?, ?, ?)", salary_contracts_data)
    cursor.executemany("INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable) VALUES (?, ?, ?, ?)", allowance_data)

    # 7. 급여 이력 (1~12월)
    salary_history_data = []
    for emp_id, info in emp_salary_map.items():
        base = info['base']; fixed = info['fixed']
        for month in range(2, 13):
            pay_date = get_pay_date(2025, month)
            is_final = 1 if month < 12 else 0
            
            # 관리자와 이승엽(25DS0001)의 경우 월급에 변동을 줌
            if emp_id == 'admin':
                if month < 12:
                    ext_pay = random.randint(0, 4) * 35240
                    night_pay = random.randint(0, 2) * 11500
                else:
                    ext_pay = 200956 
                    night_pay = 8373
            elif emp_id == '25DS0001': # 이승엽
                ext_pay = random.randint(1, 5) * 45000 # 연장 자주함
                night_pay = 0
            else:
                ext_pay = random.randint(0, 3) * 50000
                night_pay = random.randint(0, 1) * 30000

            total_allowance = fixed + ext_pay + night_pay
            gross = base + total_allowance
            
            pension = int(gross * 0.045); health = int(gross * 0.03545); care = int(health * 0.1295); emp = int(gross * 0.009)
            tax = int(max(0, gross-1000000) * 0.03); local = int(tax * 0.1)
            deduction = pension + health + care + emp + tax + local + 10000
            net = gross - deduction
            
            salary_history_data.append((emp_id, 2025, month, pay_date, base, fixed, ext_pay, night_pay, total_allowance, 10000, pension, health, care, emp, tax, local, deduction, net, is_final))
            
    cursor.executemany("INSERT INTO salary_payments (employee_id, payment_year, payment_month, payment_date, total_base, allowance_other, allowance_extended, allowance_night, total_allowance, deduction_other, national_pension, health_insurance, care_insurance, employment_insurance, income_tax, local_tax, total_deduction, net_salary, is_finalized) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", salary_history_data)

    # ---------------------------------------------------------
    # ⭐ [핵심] 근태 데이터 생성 (관리자 & 이승엽 집중)
    # ---------------------------------------------------------
    print("근태 데이터 생성 중...")
    mock_attendance = []
    
    # [11월 데이터] (1일 ~ 30일)
    for day in range(1, 31):
        current_date = datetime(2025, 11, day).date()
        date_str = current_date.strftime('%Y-%m-%d')
        weekday = current_date.weekday()

        if weekday >= 5: continue # 주말 쉼

        # 1. 관리자(admin) - 11월 꽉 채움
        cin = '09:00:00'; cout = '18:00:00'; status = '정상'; note = ''
        if day == 5: status = '지각'; cin = '09:15:00'; cout = '18:00:00'; note = '지각'
        elif day == 12: cout = '22:30:00'; note = '연장(야간) 근무'
        elif day == 19: cout = '20:30:00'; note = '연장 근무'
        elif day == 26: cout = '21:00:00'; note = '연장 근무'
        mock_attendance.append(('admin', date_str, cin, cout, status, note))

        # 2. ✅ 이승엽(25DS0001) - 11월: 야간 없이 연장 근무 위주
        # 랜덤하게 3일에 한번꼴로 연장 근무
        cin_lee = '09:00:00'; cout_lee = '18:00:00'; note_lee = ''
        if day % 3 == 0: 
            cout_lee = f"19:{random.randint(30, 59)}:00" # 19시~20시 퇴근
            note_lee = '연장 근무'
        elif day % 5 == 0:
            cout_lee = f"20:{random.randint(0, 30)}:00" # 20시~20시반 퇴근
            note_lee = '연장 근무'
        
        mock_attendance.append(('25DS0001', date_str, cin_lee, cout_lee, '정상', note_lee))


    # [12월 데이터] (1일 ~ 10일)
    for day in range(1, 11): 
        current_date = datetime(2025, 12, day).date()
        date_str = current_date.strftime('%Y-%m-%d')
        weekday = current_date.weekday()

        if weekday >= 5: continue # 주말 쉼

        # 1. 관리자(admin)
        cin = '09:00:00'; cout = '18:00:00'; status = '정상'; note = ''
        if day == 2: cin = None; cout = None; status = '휴가'; note = '연차'
        elif day == 8: cout = '22:30:00'; note = '연장(야간) 근무'
        elif day == 9: cout = '19:00:00'; note = '연장 근무' # ✅ 9일 연장
        mock_attendance.append(('admin', date_str, cin, cout, status, note))

        # 2. ✅ 이승엽(25DS0001) - 12월: 휴가 2일, 나머지 정상 (연장X, 지각X)
        if day == 4 or day == 5: # 4, 5일 휴가
            mock_attendance.append(('25DS0001', date_str, None, None, '휴가', '연차'))
        else:
            mock_attendance.append(('25DS0001', date_str, '09:00:00', '18:00:00', '정상', ''))


    # [12월 11일 (오늘)] - 관리자 제외하고 데이터 넣기
    today_str = '2025-12-11'
    # 이승엽은 오늘 정상 근무 중으로 설정
    mock_attendance.append(('25DS0001', today_str, '09:00:00', None, '정상', ''))
    
    # 다른 배경 직원들 (admin, 이승엽 제외)
    other_employees = [e[0] for e in employees_data if e[0] not in ['admin', '25DS0001']]
    if len(other_employees) >= 1: mock_attendance.append((other_employees[0], today_str, None, None, '휴가', '연차'))
    if len(other_employees) >= 2: mock_attendance.append((other_employees[1], today_str, '09:00:00', None, '외근', '외근'))
    if len(other_employees) >= 3: mock_attendance.append((other_employees[2], today_str, '09:30:00', None, '지각', '지각'))
    
    # 나머지 직원은 정상 출근 상태로
    for emp_id in other_employees[3:]:
        mock_attendance.append((emp_id, today_str, '09:00:00', None, '정상', ''))


    cursor.executemany("INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status, note) VALUES (?, ?, ?, ?, ?, ?)", mock_attendance)

    # 휴가 신청 데이터 (이승엽 승인된 휴가 포함)
    vacation_data = [
        ('25DS0001', '이승엽', '디자인팀', '연차', '2025-12-04', '2025-12-05', '개인 사정', '승인'), # ✅ 이승엽 휴가
        ('25DV0001', '김동현', '개발팀', '연차', '2025-11-20', '2025-11-20', '개인 사정', '승인'),
        ('25HR0001', '임찬규', '인사팀', '병가', '2025-12-05', '2025-12-06', '건강 검진', '승인'),
        ('25DS0001', '이승엽', '디자인팀', '오후 반차', '2025-11-15', '2025-11-15', '은행 업무', '반려'),
        ('25MK0002', '김연아', '마케팅팀', '연차', '2025-12-24', '2025-12-26', '크리스마스 휴가', '대기')
    ]
    for v in vacation_data:
        cursor.execute("INSERT INTO vacation_requests (user_id, name, department, request_type, start_date, end_date, reason, status) VALUES (?, ?, ?, ?, ?, ?, ?, ?)", v)

    conn.commit(); conn.close()
    print("DB 초기화 완료.")

if __name__ == '__main__':
    init_database()