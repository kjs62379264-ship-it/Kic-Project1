from flask import Flask, render_template, request, redirect, url_for, flash
import sqlite3
from datetime import datetime, time

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# ✨ [핵심 수정] 하루의 '마지막' 기록을 기준으로 출퇴근 버튼 상태를 결정합니다.
@app.context_processor
def inject_attendance_status():
    current_user_id = '25HR0001' # 임시 사용자 ID
    today = datetime.now().date()
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 오늘 기록 중 가장 마지막 기록을 가져옵니다.
    cursor.execute("""
        SELECT clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today))
    
    last_record = cursor.fetchone()
    conn.close()

    button_state = '출근' # 기본 상태는 '출근'
    # 마지막 기록이 있고, 그 기록에 퇴근 시간이 찍혀있지 않다면 -> '퇴근' 버튼 표시
    if last_record and last_record['clock_out_time'] is None:
        button_state = '퇴근'

    return dict(attendance_button_state=button_state)

# ✨ [핵심 수정] 여러 번의 출퇴근을 처리할 수 있도록 로직을 변경합니다.
@app.route('/attendance/clock', methods=['POST'])
def clock():
    current_user_id = '25HR0001' # 임시 사용자 ID
    now = datetime.now()
    today = now.date()

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 오늘 기록 중 가장 마지막 기록을 가져옵니다.
    cursor.execute("""
        SELECT id, clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today))
    last_record = cursor.fetchone()

    # 마지막 기록이 있고, 퇴근이 안 찍혀있다면 -> '퇴근' 처리
    if last_record and last_record['clock_out_time'] is None:
        record_id = last_record['id']
        cursor.execute("UPDATE attendance SET clock_out_time = ? WHERE id = ?", (now, record_id))
    # 그 외의 모든 경우 (기록이 없거나, 마지막 기록이 퇴근 처리된 경우) -> '출근' 처리
    else:
        status = '정상'
        # 그날의 첫 출근일 경우에만 지각을 체크합니다.
        if not last_record and now.time() > time(9, 0, 59):
            status = '지각'
        
        cursor.execute("""
            INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
            VALUES (?, ?, ?, ?)
        """, (current_user_id, today, now, status))

    conn.commit()
    conn.close()
    
    return redirect(request.referrer or url_for('dashboard'))

# --- (이하 모든 기존 함수는 그대로 유지됩니다.) ---

@app.route('/')
def dashboard():
    return render_template('dashboard.html')

@app.route('/hr')
def hr_management():
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    gender_query = request.args.get('gender', '')
    status_query = request.args.get('status', '재직')

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    base_sql = "SELECT * FROM employees"
    where_clauses = []
    params = []

    if id_query:
        where_clauses.append("id LIKE ?")
        params.append(f"%{id_query}%")
    if name_query:
        where_clauses.append("name LIKE ?")
        params.append(f"%{name_query}%")
    if department_query:
        where_clauses.append("department = ?")
        params.append(department_query)
    if position_query:
        where_clauses.append("position = ?")
        params.append(position_query)
    if gender_query:
        where_clauses.append("gender = ?")
        params.append(gender_query)
    if status_query and status_query != '전체':
        where_clauses.append("status = ?")
        params.append(status_query)

    sql = base_sql
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"
    
    cursor.execute(sql, tuple(params))
    employee_list = cursor.fetchall()
    employee_count = len(employee_list)

    cursor.execute("SELECT name, code FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()

    cursor.execute("""
        SELECT department, COUNT(*) as count 
        FROM employees WHERE status = '재직' 
        GROUP BY department ORDER BY count DESC
    """)
    dept_stats = cursor.fetchall()
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['count'] for row in dept_stats]

    conn.close()

    return render_template('hr_management.html', 
                           employees=employee_list, 
                           departments=departments, 
                           positions=positions,
                           employee_count=employee_count,
                           dept_labels=dept_labels,
                           dept_counts=dept_counts)

@app.route('/hr/add', methods=['GET', 'POST'])
def add_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        phone_number = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
        email = f"{request.form['email_id']}@{request.form['email_domain']}"
        address = request.form['address']
        gender = request.form['gender']

        cursor.execute("SELECT code FROM departments WHERE name = ?", (department,))
        dept_code_row = cursor.fetchone()
        dept_code = dept_code_row[0] if dept_code_row else 'XX'
        
        year_prefix = hire_date.split('-')[0][2:]
        prefix = year_prefix + dept_code
        cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + '%',))
        last_id = cursor.fetchone()
        new_seq = int(last_id[0][-4:]) + 1 if last_id else 1
        new_id = f"{prefix}{new_seq:04d}"

        cursor.execute("""
            INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status) 
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '재직')
        """, (new_id, name, department, position, hire_date, phone_number, email, address, gender))
        
        conn.commit()
        conn.close()
        return redirect(url_for('hr_management'))

    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    conn.close()

    return render_template('add_employee.html', departments=departments, positions=positions, email_domains=email_domains)

@app.route('/hr/employee/<employee_id>')
def employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    conn.close()
    return render_template('employee_detail.html', employee=employee)

@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
def edit_employee(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        phone_number = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
        email = f"{request.form['email_id']}@{request.form['email_domain']}"
        address = request.form['address']
        gender = request.form['gender']

        cursor.execute("""
            UPDATE employees SET name=?, department=?, position=?, hire_date=?, phone_number=?, email=?, address=?, gender=?
            WHERE id=?
        """, (name, department, position, hire_date, phone_number, email, address, gender, employee_id))
        
        conn.commit()
        conn.close()
        return redirect(url_for('employee_detail', employee_id=employee_id))

    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone()
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    conn.close()

    phone_parts = employee['phone_number'].split('-') if employee and employee['phone_number'] else ['','','']
    email_parts = employee['email'].split('@') if employee and employee['email'] else ['','']

    return render_template('edit_employee.html', 
                           employee=employee, 
                           departments=departments, 
                           positions=positions, 
                           email_domains=email_domains,
                           phone_parts=phone_parts,
                           email_parts=email_parts)

@app.route('/hr/print')
def print_employees():
    # 1. 메인 페이지의 모든 검색 조건을 그대로 가져옵니다. (상태 포함)
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    gender_query = request.args.get('gender', '')
    status_query = request.args.get('status', '재직') # '상태' 조건 추가

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. 메인 페이지와 동일한 검색 로직으로 필터링된 직원 목록을 조회합니다.
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
    
    # '상태' 필터링 로직 추가
    if status_query and status_query != '전체':
        where_clauses.append("status = ?")
        params.append(status_query)

    sql = base_sql
    if where_clauses:
        sql += " WHERE " + " AND ".join(where_clauses)
    sql += " ORDER BY id DESC"

    cursor.execute(sql, tuple(params))
    employee_list = cursor.fetchall()
    conn.close()

    # 3. 조회된 데이터를 인쇄 전용 템플릿 'print.html'로 전달합니다.
    return render_template('print.html', employees=employee_list)

@app.route('/hr/depart/<employee_id>', methods=['POST'])
def process_departure(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '퇴사' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 퇴사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))
    
@app.route('/hr/rehire/<employee_id>', methods=['POST'])
def process_rehire(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '재직' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 재입사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))

@app.route('/hr/settings')
def settings_management():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT * FROM positions ORDER BY name")
    positions = cursor.fetchall()
    conn.close()
    return render_template('settings_management.html', departments=departments, positions=positions)

@app.route('/hr/settings/add_department', methods=['POST'])
def add_department():
    new_dept_name = request.form['new_department_name'].strip()
    new_dept_code = request.form['new_department_code'].strip().upper()
    if new_dept_name and new_dept_code:
        try:
            conn = sqlite3.connect('employees.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO departments (name, code) VALUES (?, ?)", (new_dept_name, new_dept_code))
            conn.commit()
            flash(f"'{new_dept_name}' 부서가 성공적으로 추가되었습니다.", "success")
        except sqlite3.IntegrityError:
            flash("이미 존재하거나 중복된 부서명 또는 코드입니다.", "error")
        finally:
            conn.close()
    return redirect(url_for('settings_management'))

@app.route('/hr/settings/add_position', methods=['POST'])
def add_position():
    new_pos_name = request.form['new_position'].strip()
    if new_pos_name:
        try:
            conn = sqlite3.connect('employees.db')
            cursor = conn.cursor()
            cursor.execute("INSERT INTO positions (name) VALUES (?)", (new_pos_name,))
            conn.commit()
            flash(f"'{new_pos_name}' 직급이 성공적으로 추가되었습니다.", "success")
        except sqlite3.IntegrityError:
            flash("이미 존재하는 직급입니다.", "error")
        finally:
            conn.close()
    return redirect(url_for('settings_management'))

@app.route('/hr/settings/delete_department/<dept_name>', methods=['POST'])
def delete_department(dept_name):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM employees WHERE department = ? AND status = '재직'", (dept_name,))
    employee_count = cursor.fetchone()[0]
    if employee_count > 0:
        flash(f"'{dept_name}' 부서에 재직 중인 직원이 있어 삭제할 수 없습니다.", "error")
    else:
        cursor.execute("DELETE FROM departments WHERE name = ?", (dept_name,))
        conn.commit()
        flash(f"'{dept_name}' 부서가 성공적으로 삭제되었습니다.", "success")
    conn.close()
    return redirect(url_for('settings_management'))

@app.route('/hr/settings/delete_position/<pos_name>', methods=['POST'])
def delete_position(pos_name):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM employees WHERE position = ? AND status = '재직'", (pos_name,))
    employee_count = cursor.fetchone()[0]
    if employee_count > 0:
        flash(f"'{pos_name}' 직급에 재직 중인 직원이 있어 삭제할 수 없습니다.", "error")
    else:
        cursor.execute("DELETE FROM positions WHERE name = ?", (pos_name,))
        conn.commit()
        flash(f"'{pos_name}' 직급이 성공적으로 삭제되었습니다.", "success")
    conn.close()
    return redirect(url_for('settings_management'))

@app.route('/hr/settings/edit_department', methods=['POST'])
def edit_department():
    original_name = request.form['original_dept_name']
    new_name = request.form['new_dept_name'].strip()
    new_code = request.form['new_department_code'].strip().upper()
    try:
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE departments SET name = ?, code = ? WHERE name = ?", (new_name, new_code, original_name))
        cursor.execute("UPDATE employees SET department = ? WHERE department = ?", (new_name, original_name))
        conn.commit()
        flash("부서 정보가 성공적으로 수정되었습니다.", "success")
    except sqlite3.IntegrityError:
        flash("이미 존재하거나 중복된 부서명 또는 코드입니다.", "error")
    finally:
        conn.close()
    return redirect(url_for('settings_management'))

# ✨ [추가] '내 출퇴근 기록' 페이지를 위한 라우트
@app.route('/my_attendance')
def my_attendance():
    current_user_id = '25HR0001' # 임시 사용자 ID

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 현재 사용자의 모든 출퇴근 기록을 최신순으로 조회합니다.
    cursor.execute("""
        SELECT record_date, clock_in_time, clock_out_time, attendance_status
        FROM attendance
        WHERE employee_id = ?
        ORDER BY record_date DESC, clock_in_time DESC
    """, (current_user_id,))
    
    attendance_records = cursor.fetchall()
    conn.close()

    return render_template('my_attendance.html', records=attendance_records)



if __name__ == '__main__':
    app.run(debug=True)

