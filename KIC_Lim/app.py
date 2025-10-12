from flask import Flask, render_template, request, redirect, url_for
import sqlite3

app = Flask(__name__)

# 대시보드 (메인 화면) 라우트 설정
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# '/hr' 경로로 접속했을 때의 규칙 정의
@app.route('/hr')
def hr_management():
    # 1. 폼에서 전달된 모든 검색 조건 가져오기
    id_query = request.args.get('id', '')          
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')   
    gender_query = request.args.get('gender', '')

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. 동적 SQL 쿼리 생성을 위한 준비
    base_sql = "SELECT * FROM employees"
    where_clauses = []
    params = []

    # 3. ★ 추가된 검색 조건을 확인하고, 쿼리 조립
    if id_query:
        where_clauses.append("id LIKE ?")
        params.append('%' + id_query + '%')

    if name_query:
        where_clauses.append("name LIKE ?")
        params.append('%' + name_query + '%')

    if department_query:
        where_clauses.append("department = ?")
        params.append(department_query)

    if position_query:
        where_clauses.append("position = ?")
        params.append(position_query)

    if gender_query:
        where_clauses.append("gender = ?")
        params.append(gender_query)

    # 4. 조립된 조건으로 최종 SQL 쿼리 완성
    sql = base_sql
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"

    # 5. 최종 쿼리 실행
    cursor.execute(sql, tuple(params))
    employee_list = cursor.fetchall()

     # ★ 3. 그래프 데이터 생성 로직 추가
    cursor.execute("""
        SELECT department, COUNT(*) as count 
        FROM employees 
        GROUP BY department 
        ORDER BY count DESC
    """)
    dept_stats = cursor.fetchall()

    # Chart.js가 사용할 수 있도록 부서명 리스트와 인원수 리스트로 분리
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['count'] for row in dept_stats]

    # ★ 1. 조회된 직원 목록의 총 인원수 계산
    employee_count = len(employee_list)

    # 6. ★ 검색창의 드롭다운을 채우기 위해 부서 및 직급 목록 조회
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()

    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()

    conn.close()

    return render_template('hr_management.html', 
                           employees=employee_list, 
                           departments=departments, 
                           positions=positions,
                           employee_count=employee_count,
                           dept_labels=dept_labels,     # ★ 추가
                           dept_counts=dept_counts)     # ★ 추가
# '신규 직원 등록' 페이지를 보여주고, 데이터를 DB에 저장하는 라우트
# app.py

@app.route('/hr/add', methods=['GET', 'POST'])
def add_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        # 1. 폼에서 status 관련 데이터 제거
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']

        phone1 = request.form['phone1']
        phone2 = request.form['phone2']
        phone3 = request.form['phone3']
        phone_number = f"{phone1}-{phone2}-{phone3}"

        email_id = request.form['email_id']
        email_domain = request.form['email_domain']
        email = f"{email_id}@{email_domain}"

        address = request.form['address']
        gender = request.form['gender']
        # status = request.form['status'] # 이 줄 삭제

        # (사번 생성 로직은 기존과 동일)
        dept_codes = {'인사팀': 'HR', '개발팀': 'DV', '디자인팀': 'DS', '마케팅팀': 'MK'}
        dept_code = dept_codes.get(department, 'XX')
        year_prefix = hire_date.split('-')[0][2:]
        prefix = year_prefix + dept_code
        cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + '%',))
        last_id = cursor.fetchone()
        if last_id:
            new_seq = int(last_id[0][-4:]) + 1
        else:
            new_seq = 1
        new_id = f"{prefix}{new_seq:04d}"

        # 2. ★ DB INSERT 문에서 status 관련 부분 제거
        cursor.execute("""
            INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (new_id, name, department, position, hire_date, phone_number, email, address, gender))

        conn.commit()
        conn.close()
        return redirect(url_for('hr_management'))

    # GET 요청일 때: ★ status 관련 부분 제거
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()

    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()

    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()

    conn.close()

    return render_template('add_employee.html', departments=departments, positions=positions, email_domains=email_domains)

# '근태관리'
@app.route('/attendance')
def attendance():
    return render_template('attendance.html')

# 특정 직원의 상세 정보 페이지를 보여주는 라우트
@app.route('/hr/employee/<employee_id>')
def employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # id가 일치하는 직원 한 명의 모든 정보 조회
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 

    conn.close()

    # 조회된 직원 정보를 employee_detail.html 로 전달
    return render_template('employee_detail.html', employee=employee)

# 직원 정보 수정을 위한 페이지 라우트
@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # POST 요청: 폼 데이터 받아서 DB 업데이트
    if request.method == 'POST':
        # 1. 수정 폼에서 제출된 새로운 데이터 가져오기
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        
        phone1 = request.form['phone1']
        phone2 = request.form['phone2']
        phone3 = request.form['phone3']
        phone_number = f"{phone1}-{phone2}-{phone3}"

        email_id = request.form['email_id']
        email_domain = request.form['email_domain']
        email = f"{email_id}@{email_domain}"
        
        address = request.form['address']
        gender = request.form['gender']

        # 2. SQL UPDATE 쿼리 실행 (WHERE 절이 매우 중요!)
        cursor.execute("""
            UPDATE employees 
            SET name = ?, department = ?, position = ?, hire_date = ?, 
                phone_number = ?, email = ?, address = ?, gender = ?
            WHERE id = ?
        """, (name, department, position, hire_date, phone_number, email, address, gender, employee_id))
        
        conn.commit()
        conn.close()

        # 3. 수정이 완료되면 해당 직원의 '상세 보기' 페이지로 이동
        return redirect(url_for('employee_detail', employee_id=employee_id))

    # GET 요청: DB에서 정보 가져와서 수정 폼 보여주기 (기존과 동일)
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone()

    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    
    conn.close()

    phone_parts = employee['phone_number'].split('-') if employee['phone_number'] else ['','','']
    email_parts = employee['email'].split('@') if employee['email'] else ['','']

    return render_template('edit_employee.html', 
                           employee=employee, 
                           departments=departments, 
                           positions=positions, 
                           email_domains=email_domains,
                           phone_parts=phone_parts,
                           email_parts=email_parts)

# 인쇄 전용 페이지를 위한 라우트
@app.route('/hr/print')
def print_employees():
    # 1. 메인 페이지의 검색 조건을 그대로 가져옴
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    gender_query = request.args.get('gender', '')

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. 메인 페이지와 동일한 검색 로직으로 필터링된 직원 목록 조회
    base_sql = "SELECT * FROM employees"
    where_clauses = []
    params = []
    if id_query:
        where_clauses.append("id LIKE ?")
        params.append('%' + id_query + '%')
    if name_query:
        where_clauses.append("name LIKE ?")
        params.append('%' + name_query + '%')
    if department_query:
        where_clauses.append("department = ?")
        params.append(department_query)
    if position_query:
        where_clauses.append("position = ?")
        params.append(position_query)
    if gender_query:
        where_clauses.append("gender = ?")
        params.append(gender_query)

    sql = base_sql
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"

    cursor.execute(sql, tuple(params))
    employee_list = cursor.fetchall()
    conn.close()

    # 3. 조회된 데이터를 인쇄 전용 템플릿 'print_view.html'로 전달
    return render_template('print.html', employees=employee_list)

# 특정 직원의 정보를 삭제하는 라우트
@app.route('/hr/delete/<employee_id>', methods=['POST'])
def delete_employee(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # id가 일치하는 직원 데이터 삭제
    cursor.execute("DELETE FROM employees WHERE id = ?", (employee_id,))

    conn.commit()
    conn.close()

    # 삭제 후 메인 직원 명부 페이지로 이동
    return redirect(url_for('hr_management'))

if __name__ == '__main__':
    app.run(debug=True)
