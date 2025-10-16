from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort # abort 임포트 추가
import sqlite3
from datetime import datetime, time
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# ----------------------------------------------------
# 1. 인증 전처리 및 데코레이터 (role 포함)
# ----------------------------------------------------

@app.before_request
def load_logged_in_user():
    """세션에서 사용자 ID를 읽어 g.user에 직원 정보와 role을 저장"""
    user_id = session.get('user_id')
    g.user = None
    
    if user_id is not None:
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # ✨ [핵심 수정] users 테이블과 employees 테이블을 조인하여 role 정보까지 가져옴
        cursor.execute("""
            SELECT e.*, u.role 
            FROM employees e 
            JOIN users u ON e.id = u.employee_id 
            WHERE e.id = ?
        """, (user_id,))
        g.user = cursor.fetchone()
        conn.close()

def login_required(view):
    """로그인만 하면 접근 가능한 페이지 데코레이터 (모든 직원용)"""
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def admin_required(view):
    """관리자 권한이 필요한 페이지 데코레이터"""
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for('login'))
        # ✨ [핵심 추가] role이 'admin'이 아니면 403 에러 발생
        if g.user['role'] != 'admin':
            flash("이 기능은 관리자만 접근 가능합니다.", "error")
            return redirect(url_for('dashboard')) # 대시보드로 리다이렉트
        return view(**kwargs)
    return wrapped_view


# ----------------------------------------------------
# 2. 로그인/로그아웃 라우트 (수정 없음)
# ----------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # role 정보도 함께 가져옴
        cursor.execute("SELECT employee_id, password_hash, role FROM users WHERE username = ?", (username,))
        user_record = cursor.fetchone()
        conn.close()
        
        if user_record and check_password_hash(user_record['password_hash'], password):
            session['user_id'] = user_record['employee_id']
            flash(f"환영합니다, {username}님! ({'관리자' if user_record['role'] == 'admin' else '직원'})", "success")
            return redirect(url_for('dashboard'))
        else:
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))


# ----------------------------------------------------
# 3. 출퇴근 상태 및 라우트 (login_required 유지)
# ----------------------------------------------------

@app.context_processor
def inject_attendance_status():
    if not g.user:
        return dict(attendance_button_state=None)

    current_user_id = g.user['id']
    today = datetime.now().date()
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today))
    
    last_record = cursor.fetchone()
    conn.close()

    button_state = '출근'
    if last_record and last_record['clock_out_time'] is None:
        button_state = '퇴근'

    return dict(attendance_button_state=button_state)

@app.route('/attendance/clock', methods=['POST'])
@login_required # 모든 직원이 사용 가능
def clock():
    current_user_id = g.user['id']
    now = datetime.now()
    today = now.date()
    # ... (기존 출퇴근 로직) ...
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today))
    last_record = cursor.fetchone()
    if last_record and last_record['clock_out_time'] is None:
        record_id = last_record['id']
        cursor.execute("UPDATE attendance SET clock_out_time = ? WHERE id = ?", (now, record_id))
    else:
        status = '정상'
        if not last_record and now.time() > time(9, 0, 59):
            status = '지각'
        cursor.execute("""
            INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
            VALUES (?, ?, ?, ?)
        """, (current_user_id, today, now, status))
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('dashboard'))


# ----------------------------------------------------
# 4. 보호된 주요 라우트 (admin_required 적용)
# ----------------------------------------------------

@app.route('/')
@login_required # 모든 직원이 접근 가능
def dashboard():
    return render_template('dashboard.html')

# 인사 관리 관련 모든 라우트에 admin_required 적용
@app.route('/hr')
@login_required # ✨ [수정] admin_required에서 login_required로 변경
def hr_management():
    # ... (기존 로직) ...
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    gender_query = request.args.get('gender', '')
    status_query = request.args.get('status', '재직')
    # ... (생략) ...
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
                           dept_counts=dept_counts,
                           request=request)

@app.route('/hr/add', methods=['GET', 'POST'])
@admin_required # ✨ [수정] 관리자 전용
def add_employee():
    # ... (기존 로직) ...
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
@login_required # ✨ [수정] admin_required에서 login_required로 변경
def employee_detail(employee_id):
    # ... (기존 로직) ...
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    conn.close()
    return render_template('employee_detail.html', employee=employee)

@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
@admin_required # ✨ [수정] 관리자 전용
def edit_employee(employee_id):
    # ... (기존 로직) ...
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
@login_required # 👈 @admin_required를 이것으로 변경
def print_employees():
    # ... (기존 로직) ...
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    gender_query = request.args.get('gender', '')
    status_query = request.args.get('status', '재직')
    # ... (생략) ...
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
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
    return render_template('print.html', employees=employee_list)

@app.route('/hr/depart/<employee_id>', methods=['POST'])
@admin_required # ✨ [수정] 관리자 전용
def process_departure(employee_id):
    # ... (기존 로직) ...
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '퇴사' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 퇴사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))
    
@app.route('/hr/rehire/<employee_id>', methods=['POST'])
@admin_required # ✨ [수정] 관리자 전용
def process_rehire(employee_id):
    # ... (기존 로직) ...
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '재직' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 재입사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))

@app.route('/hr/settings')
@admin_required # ✨ [수정] 관리자 전용
def settings_management():
    # ... (기존 로직) ...
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
@admin_required # ✨ [수정] 관리자 전용
def add_department():
    # ... (기존 로직) ...
    new_dept_name = request.form['new_department_name'].strip()
    new_dept_code = request.form['new_department_code'].strip().upper()
    # ... (생략) ...
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
@admin_required # ✨ [수정] 관리자 전용
def add_position():
    # ... (기존 로직) ...
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
@admin_required # ✨ [수정] 관리자 전용
def delete_department(dept_name):
    # ... (기존 로직) ...
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
@admin_required # ✨ [수정] 관리자 전용
def delete_position(pos_name):
    # ... (기존 로직) ...
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
@admin_required # ✨ [수정] 관리자 전용
def edit_department():
    # ... (기존 로직) ...
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

if __name__ == '__main__':
    app.run(debug=True)