import sqlite3

def update_database_schema():
    print("DB 업데이트를 시작합니다...")
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # 1. payroll_rates 테이블 생성 (요율 관리용)
    print("- 'payroll_rates' 테이블 확인 중...")
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS payroll_rates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        national_pension_rate REAL DEFAULT 4.5,
        health_insurance_rate REAL DEFAULT 3.545,
        care_insurance_rate REAL DEFAULT 12.95,
        employment_insurance_rate REAL DEFAULT 0.9
    );""")
    
    # 기본 요율 데이터가 없으면 추가
    cursor.execute("SELECT count(*) FROM payroll_rates")
    if cursor.fetchone()[0] == 0:
        cursor.execute("INSERT INTO payroll_rates (id) VALUES (1)")
        print("  >> 기본 요율 데이터 추가 완료.")

    # 2. salary_payments 테이블에 overtime_pay 컬럼 추가 (야근 수당용)
    print("- 'salary_payments' 테이블에 'overtime_pay' 컬럼 추가 중...")
    try:
        cursor.execute("ALTER TABLE salary_payments ADD COLUMN overtime_pay INTEGER DEFAULT 0")
        print("  >> 'overtime_pay' 컬럼 추가 완료.")
    except sqlite3.OperationalError:
        print("  >> (이미 존재하는 컬럼입니다. 패스합니다.)")

    conn.commit()
    conn.close()
    print("\n✅ DB 업데이트가 성공적으로 완료되었습니다!")
    print("이제 'python app.py'를 실행해서 교수님이 요청하신 기능을 확인해보세요.")

if __name__ == '__main__':
    update_database_schema()