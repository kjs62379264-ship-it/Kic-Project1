from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
import sqlite3
from datetime import datetime, time
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

UPLOAD_FOLDER = os.path.join(app.static_folder, 'profile_photos')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------------------------------
# 1. 인증 전처리 및 데코레이터
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
        
        # users 테이블과 employees 테이블을 조인하여 role 정보까지 가져옴
        cursor.execute("""
            SELECT e.*, u.role 
            FROM employees e 
            JOIN users u ON e.id = u.employee_id 
            WHERE e.id = ?
        """, (user_id,))
        g.user = cursor.fetchone()
        
        if g.user:
            g.user = dict(g.user) 
            
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
        if g.user['role'] != 'admin':
            flash("이 기능은 관리자만 접근 가능합니다.", "error")
            return redirect(url_for('hr_management')) 
        return view(**kwargs)
    return wrapped_view


# ----------------------------------------------------
# 2. 로그인/로그아웃/비밀번호 변경 라우트
# ----------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('hr_management'))

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT employee_id, password_hash, role, username FROM users WHERE username = ?", (username,))
        user_record = cursor.fetchone()
        conn.close()
        
        if user_record and check_password_hash(user_record['password_hash'], password):
            session['user_id'] = user_record['employee_id'] 
            flash(f"환영합니다, {user_record['username']}님! ({'관리자' if user_record['role'] == 'admin' else '직원'})", "success")
            return redirect(url_for('hr_management'))
        else:
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")

    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required 
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        cursor.execute("SELECT password_hash FROM users WHERE employee_id = ?", (g.user['id'],))
        user_record = cursor.fetchone()

        if not (user_record and check_password_hash(user_record['password_hash'], current_password)):
            flash("현재 비밀번호가 일치하지 않습니다.", "error")
            conn.close()
            return redirect(url_for('change_password'))

        if new_password != confirm_password:
            flash("새 비밀번호가 일치하지 않습니다.", "error")
            conn.close()
            return redirect(url_for('change_password'))
            
        try:
            new_password_hash = generate_password_hash(new_password)
            cursor.execute("UPDATE users SET password_hash = ? WHERE employee_id = ?", 
                           (new_password_hash, g.user['id']))
            conn.commit()
            flash("비밀번호가 성공적으로 변경되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"오류가 발생했습니다: {e}", "error")
        finally:
            conn.close()
        
        return redirect(url_for('hr_management'))

    return render_template('change_password.html')

# ----------------------------------------------------
# 3. 출퇴근 상태 및 라우트
# ----------------------------------------------------

@app.context_processor
def inject_attendance_status():
    if not g.user:
        return dict(attendance_button_state=None)

    current_user_id = g.user['id']
    # SQLite DATETIME 형식으로 변환
    today = datetime.now().date().strftime('%Y-%m-%d')
    
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
@login_required 
def clock():
    current_user_id = g.user['id']
    now = datetime.now()
    today = now.date().strftime('%Y-%m-%d')
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today))
    last_record = cursor.fetchone()
    
    now_str = now.strftime('%Y-%m-%d %H:%M:%S')

    if last_record and last_record['clock_out_time'] is None:
        # 퇴근 처리
        record_id = last_record['id']
        cursor.execute("UPDATE attendance SET clock_out_time = ? WHERE id = ?", (now_str, record_id))
    else:
        # 출근 처리
        status = '정상'
        if not last_record and now.time() > time(9, 0, 59):
            status = '지각'
        cursor.execute("""
            INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
            VALUES (?, ?, ?, ?)
        """, (current_user_id, today, now_str, status))
        
    conn.commit()
    conn.close()
    return redirect(request.referrer or url_for('attendance'))


# ----------------------------------------------------
# 4. 보호된 주요 라우트
# ----------------------------------------------------

@app.route('/')
@login_required
def root():
    return redirect(url_for('hr_management'))

@app.route('/attendance')
@login_required 
def attendance():
    # ... (기존 attendance 로직은 그대로 유지, 임시 데이터 사용) ...
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    status_query = request.args.get('status', '')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    today_attendance_data = {}
    cursor.execute("SELECT * FROM employees WHERE id != 'admin' AND status = '재직' ORDER BY id")
    all_employees = cursor.fetchall()
    
    # (이하 임시 로직)
    TEMP_ATTENDANCE_STATUS = {
        '25HR0001': {'status': '재실', 'check_in': '08:50', 'check_out': None, 'leave_status': None}, 
        '25DV0001': {'status': '휴가', 'check_in': None, 'check_out': None, 'leave_status': '연차'},
        '25DS0001': {'status': '재실', 'check_in': '09:05', 'check_out': None, 'leave_status': None},
        '25MK0001': {'status': '외근', 'check_in': '09:10', 'check_out': None, 'leave_status': None},
    }

    for emp in all_employees:
        emp_id = emp['id']
        
        status_info = TEMP_ATTENDANCE_STATUS.get(emp_id, {'status': '부재', 'check_in': None, 'check_out': None, 'leave_status': None})
        
        today_attendance_data[emp_id] = {
            **dict(emp), 
            'status': status_info['status'],
            'check_in': status_info['check_in'],
            'check_out': status_info['check_out'], 
            'leave_status': status_info['leave_status']
        }
    
    total_employees_count = len(today_attendance_data)
    filtered_employees = []
    
    for emp in today_attendance_data.values():
        match = True
        if id_query and id_query.lower() not in emp['id'].lower(): match = False
        if name_query and name_query not in emp['name']: match = False
        if department_query and emp['department'] != department_query: match = False
        if position_query and emp['position'] != position_query: match = False
        if status_query and emp['status'] != status_query: match = False
        if match:
            filtered_employees.append(emp)

    status_counts = {'재실': 0, '휴가': 0, '외근/출장': 0, '부재': 0}
    
    for emp in today_attendance_data.values():
        status = emp['status']
        if status == '재실':
            status_counts['재실'] += 1
        elif status == '휴가':
            status_counts['휴가'] += 1
        elif status in ['외근', '출장']:
            status_counts['외근/출장'] += 1
        elif status == '부재': 
            status_counts['부재'] += 1
            
    # (이하 임시 데이터)
    pending_requests = [
        {'id': 101, 'employee_id': '25DV0002', 'name': '일반직원', 'department': '개발팀', 'dept_code': 'DV', 'type': '연차', 'period': '2025-10-25', 'reason': '개인사정', 'request_date': '2025-10-18', 'status': '미승인'},
        {'id': 102, 'employee_id': '25MK0004', 'name': '박마케팅', 'department': '마케팅팀', 'dept_code': 'MK', 'type': '오전 반차', 'period': '2025-10-20', 'reason': '은행 업무', 'request_date': '2025-10-17', 'status': '미승인'},
        {'id': 103, 'employee_id': '25HR0001', 'name': '관리자', 'department': '인사팀', 'dept_code': 'HR', 'type': '외근', 'period': '2025-10-20', 'reason': '미팅', 'request_date': '2025-10-16', 'status': '승인'},
        {'id': 104, 'employee_id': '25DS0006', 'name': '최디자인', 'department': '디자인팀', 'dept_code': 'DS', 'type': '수정', 'period': '2025-10-21', 'reason': '일정 변경', 'request_date': '2025-10-19', 'status': '반려'},
    ]
    
    page = request.args.get('pending_page', 1, type=int) 
    PER_PAGE = 3
    total_requests = len(pending_requests)
    total_pages = (total_requests + PER_PAGE - 1) // PER_PAGE
    start_index = (page - 1) * PER_PAGE
    end_index = start_index + PER_PAGE
    paginated_requests = pending_requests[start_index:end_index]
    total_pending_count = len([req for req in pending_requests if req['status'] == '미승인'])
    
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    conn.close()
    
    return render_template('attendance_page.html', 
                            employees=filtered_employees,
                            pending_requests=paginated_requests,
                            total_employees_count=total_employees_count,
                            departments=departments, 
                            positions=positions,
                            request=request,
                            total_requests=total_requests,
                            total_pages=total_pages,
                            current_pending_page=page,
                            status_counts=status_counts,
                            total_absent_count=status_counts['부재'])


@app.route('/attendance/employee/<employee_id>')
@login_required 
def attendance_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    
    if not employee:
        flash(f"직원 ID {employee_id}를 찾을 수 없습니다.", "error")
        return redirect(url_for('attendance'))
    
    TEMP_ATTENDANCE_STATUS = {
        '25HR0001': {'status': '재실', 'color': 'green'}, 
        '25DV0001': {'status': '휴가', 'color': '#3498db'},
        '25DS0001': {'status': '재실', 'color': 'green'},
        '25MK0001': {'status': '부재', 'color': 'red'},
        'admin': {'status': '재실', 'color': 'green'}
    }
    today_status_info = TEMP_ATTENDANCE_STATUS.get(employee_id, {'status': '정보 없음', 'color': 'black'})
    today_status = today_status_info['status']
    
    sample_records = [
        {'date': '2025-10-14', 'clock_in': '08:55', 'clock_out': '18:00', 'status': '정상'},
        {'date': '2025-10-15', 'clock_in': '09:02', 'clock_out': '18:30', 'status': '지각'},
        {'date': '2025-10-16', 'clock_in': '08:59', 'clock_out': '19:15', 'status': '정상'},
        {'date': '2025-10-17', 'clock_in': '09:00', 'clock_out': '18:00', 'status': '정상'},
        {'date': '2025-10-18', 'clock_in': '08:30', 'clock_out': None, 'status': f'{today_status} (근무중)' if today_status == '재실' else today_status},
    ]
    
    conn.close()
    
    return render_template('attendance_detail.html', 
                           employee=employee,
                           records=sample_records,
                           today_status=today_status)

# ----------------------------------------------------
# 5. 인사 관리 (HR) 라우트
# ----------------------------------------------------

@app.route('/hr')
@login_required 
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
    where_clauses = ["id != 'admin'"] 
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
        FROM employees WHERE status = '재직' AND id != 'admin'
        GROUP BY department ORDER BY count DESC
    """)
    dept_stats = cursor.fetchall()
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['count'] for row in dept_stats]

    cursor.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5")
    notices = cursor.fetchall()
    
    conn.close()
    
    return render_template('hr_management.html', 
                           employees=employee_list, 
                           departments=departments, 
                           positions=positions,
                           employee_count=employee_count,
                           dept_labels=dept_labels,
                           dept_counts=dept_counts,
                           notices=notices, 
                           request=request)

@app.route('/hr/add', methods=['GET', 'POST'])
@admin_required 
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
        
        # 사번 생성 로직: 해당 부서/연도의 마지막 ID를 찾고 +1
        cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + '%',))
        last_id_row = cursor.fetchone()
        
        new_seq = 1
        if last_id_row:
            last_id = last_id_row[0]
            # ID가 'YYCC####' 형식인지 확인하고 시퀀스 번호를 추출
            if len(last_id) == 8 and last_id[:4] == prefix:
                try:
                    new_seq = int(last_id[4:]) + 1
                except ValueError:
                    # 번호 부분이 이상하면 1부터 다시 시작
                    new_seq = 1
        
        new_id = f"{prefix}{new_seq:04d}"
        
        password = request.form['password'] 
        role = request.form.get('role', 'user') 

        if not password:
            flash("초기 비밀번호를 입력해야 합니다.", "error")
            cursor.execute("SELECT name FROM departments ORDER BY name")
            departments = cursor.fetchall()
            cursor.execute("SELECT name FROM positions ORDER BY name")
            positions = cursor.fetchall()
            cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
            email_domains = cursor.fetchall()
            conn.close()
            return render_template('add_employee.html', departments=departments, positions=positions, email_domains=email_domains)

        password_hash = generate_password_hash(password)
        
        try:
            cursor.execute("""
                INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '재직')
            """, (new_id, name, department, position, hire_date, phone_number, email, address, gender))
            
            cursor.execute("""
                INSERT INTO users (employee_id, username, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, (new_id, new_id, password_hash, role))
            
            conn.commit()
            flash(f"직원 {name}({new_id})이(가) 성공적으로 등록되었습니다.", "success")
        except sqlite3.IntegrityError as e:
            conn.rollback()
            flash(f"등록 실패: {e}", "error")
        finally:
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
@login_required 
def employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT e.*, u.role 
        FROM employees e
        LEFT JOIN users u ON e.id = u.employee_id
        WHERE e.id = ?
    """, (employee_id,))
    employee = cursor.fetchone() 
    
    conn.close()
    
    if not employee:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        return redirect(url_for('hr_management'))
        
    return render_template('employee_detail.html', employee=employee)

@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
@login_required 
def edit_employee(employee_id):
    
    if g.user['role'] != 'admin' and g.user['id'] != employee_id:
        flash("수정 권한이 없습니다.", "error")
        return redirect(url_for('employee_detail', employee_id=employee_id))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    employee = cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not employee:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('hr_management'))

    if request.method == 'POST':
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        phone_number = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
        email = f"{request.form['email_id']}@{request.form['email_domain']}"
        address = request.form['address']
        gender = request.form['gender']
        
        role = request.form.get('role', None)
        profile_image_filename = employee['profile_image']

        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                profile_image_filename = filename

        try:
            cursor.execute("""
                UPDATE employees SET name=?, department=?, position=?, hire_date=?, 
                               phone_number=?, email=?, address=?, gender=?, 
                               profile_image=?
                WHERE id=?
            """, (name, department, position, hire_date, phone_number, email, 
                  address, gender, profile_image_filename, employee_id))
            
            if g.user['role'] == 'admin' and role:
                cursor.execute("UPDATE users SET role = ? WHERE employee_id = ?", (role, employee_id))
            
            conn.commit()
            flash("직원 정보가 성공적으로 수정되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"수정 중 오류 발생: {e}", "error")
        finally:
            conn.close()
            
        return redirect(url_for('employee_detail', employee_id=employee_id))
    
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    
    user_role_info = cursor.execute("SELECT role FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
    conn.close()

    phone_parts = employee['phone_number'].split('-') if employee and employee['phone_number'] else ['','','']
    email_parts = employee['email'].split('@') if employee and employee['email'] else ['','']
    
    employee_dict = dict(employee)
    employee_dict['role'] = user_role_info['role'] if user_role_info else 'user'

    return render_template('edit_employee.html', 
                           employee=employee_dict, 
                           departments=departments, 
                           positions=positions, 
                           email_domains=email_domains,
                           phone_parts=phone_parts,
                           email_parts=email_parts)

@app.route('/hr/print')
@admin_required 
def print_employees():
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
    where_clauses = ["id != 'admin'"] 
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
@admin_required 
def process_departure(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE employees SET status = '퇴사' WHERE id = ?", (employee_id,))
        cursor.execute("UPDATE users SET role = 'user' WHERE employee_id = ?", (employee_id,)) 
        conn.commit()
        flash(f"직원({employee_id})이 퇴사 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"처리 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('employee_detail', employee_id=employee_id))
    
@app.route('/hr/rehire/<employee_id>', methods=['POST'])
@admin_required 
def process_rehire(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '재직' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 재입사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))
    
# ----------------------------------------------------
# 6. 설정 (Settings) 라우트
# ----------------------------------------------------

@app.route('/hr/settings')
@admin_required 
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
@admin_required 
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
@admin_required 
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
@admin_required 
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
@admin_required 
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
@admin_required 
def edit_department():
    original_name = request.form['original_dept_name']
    new_name = request.form['new_dept_name'].strip()
    new_code = request.form['new_dept_code'].strip().upper() 
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

# ----------------------------------------------------
# 7. 공지사항 (Notice) 라우트
# ----------------------------------------------------

@app.route('/hr/notices/add', methods=['GET', 'POST'])
@admin_required 
def add_notice_page():
    if request.method == 'POST':
        title = request.form['title']
        content = request.form['content'].strip() 
        
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        cursor.execute("INSERT INTO notices (title, content) VALUES (?, ?)", (title, content))
        conn.commit()
        conn.close()
        
        flash("새 공지사항이 등록되었습니다.", "success")
        return redirect(url_for('hr_management'))
        
    return render_template('add_notice_page.html')

@app.route('/hr/notices/delete/<int:notice_id>', methods=['POST'])
@admin_required 
def delete_notice(notice_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notices WHERE id = ?", (notice_id,))
    conn.commit()
    conn.close()
    flash("공지사항이 삭제되었습니다.", "success")
    return redirect(url_for('hr_management'))

@app.route('/hr/notices/<int:notice_id>')
@login_required 
def view_notice(notice_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM notices WHERE id = ?", (notice_id,))
    notice_row = cursor.fetchone()
    conn.close()
    
    if notice_row is None:
        flash("해당 공지사항을 찾을 수 없습니다.", "error")
        return redirect(url_for('hr_management'))

    notice = dict(notice_row)
    
    if notice['created_at']:
        try:
            notice['created_at'] = datetime.strptime(notice['created_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            notice['created_at'] = None
    else:
        notice['created_at'] = None
        
    return render_template('notice_detail.html', notice=notice)

# ----------------------------------------------------
# 8. 급여 관리 (Salary) 라우트
# ----------------------------------------------------

def get_monthly_attendance_summary(employee_id, year, month):
    """
    특정 직원의 특정 월에 대한 근태 기록을 요약하여 반환합니다.
    (월급일 경우 해당 월의 결근 일수를 계산하는 것이 핵심입니다.)
    """
    
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    # 해당 월의 총 근무(출퇴근 기록) 일수 계산 (기록이 있으면 출근으로 간주)
    cursor.execute("""
        SELECT COUNT(DISTINCT record_date) 
        FROM attendance 
        WHERE employee_id = ? AND record_date LIKE ?
    """, (employee_id, f"{year}-{month:02d}%"))
    work_days_recorded = cursor.fetchone()[0]

    conn.close()
    
    # 🚨 휴가 및 결근 테이블이 없어 임시로 결근 일수를 가정 (실제 비즈니스 로직 필요)
    # 여기서는 단순화를 위해 결근 일수를 0으로 가정하며, work_days_recorded를 통해 근태율을 조정하지 않습니다.
    absent_days = 0 
    
    # 근태 반영 계수 (1.0 = 정상, 0.9 = 10% 삭감 등)
    # 실제 결근 일수를 알면: daily_rate = 1/20 (월 20일 근무 가정)
    # attendance_factor = 1.0 - (absent_days * daily_rate)
    attendance_factor = 1.0 # 임시로 1.0 유지 (실제 결근 데이터 없음)

    return {
        'absent_days': absent_days,
        'attendance_factor': max(0.0, attendance_factor) # 최소 0.0 이상
    }

def get_employee_salary_info(employee_id):
    """직원의 기본 급여 정보를 조회합니다."""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM salaries WHERE employee_id = ?", (employee_id,))
    salary_info = cursor.fetchone()
    conn.close()
    return salary_info

def get_employee_payroll_records(employee_id):
    """직원의 월별 급여 지급 기록 목록을 조회합니다."""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM payroll_records WHERE employee_id = ? ORDER BY pay_date DESC", (employee_id,))
    records = cursor.fetchall()
    conn.close()
    return records
    
def get_all_employees_with_salary():
    """모든 재직 직원의 기본 정보와 급여 정보를 함께 조회합니다."""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    cursor.execute("""
        SELECT 
            e.id, e.name, e.department, e.position, e.status,
            s.base_salary, s.contract_type, s.payment_cycle, s.allowance
        FROM employees e
        LEFT JOIN salaries s ON e.id = s.employee_id
        WHERE e.status = '재직' AND e.id != 'admin'
        ORDER BY e.id
    """)
    employees_data = cursor.fetchall()
    conn.close()
    return employees_data

def calculate_net_pay(base_salary, allowance, tax_rate, attendance_factor=1.0, bonus=0):
    """
    기본 급여 정보와 근태율을 바탕으로 실수령액을 계산합니다.
    """
    
    # 1. 총 기본 지급액 (월급 기준)
    monthly_base_pay = (base_salary / 12)
    
    # 2. 근태 반영
    adjusted_base_pay = monthly_base_pay * attendance_factor
    
    # 3. 총 지급액 (기본급 + 수당 + 보너스)
    total_gross_pay = adjusted_base_pay + allowance + bonus
    
    # 4. 공제액 계산 (세율을 포함한 단순 공제액 가정)
    deductions = int(total_gross_pay * (tax_rate + 0.03)) # 소득세 + 3% 추가 공제 가정
    
    # 5. 실수령액
    net_pay = total_gross_pay - deductions
    
    return {
        'gross_pay': int(total_gross_pay),
        'deductions': deductions,
        'net_pay': int(net_pay),
        'bonus': bonus, 
        'allowance': allowance 
    }

@app.route('/salary')
@login_required
def salary_management():
    current_month = datetime.now().strftime('%Y-%m')
    
    # 관리자는 전체 직원의 급여 정보를 보고 관리할 수 있음
    if g.user['role'] == 'admin':
        employees_with_salary = get_all_employees_with_salary()
        return render_template('salary_management.html', 
                               is_admin=True, 
                               employees=employees_with_salary,
                               current_month=current_month)
    
    # 일반 직원은 자신의 급여 기록만 볼 수 있음
    else:
        salary_info = get_employee_salary_info(g.user['id'])
        payroll_records = get_employee_payroll_records(g.user['id'])
        
        return render_template('salary_management.html', 
                               is_admin=False, 
                               salary_info=salary_info,
                               payroll_records=payroll_records)

@app.route('/salary/add_info/<employee_id>', methods=['GET', 'POST'])
@admin_required
def add_salary_info(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    if request.method == 'POST':
        base_salary = request.form.get('base_salary', type=int)
        contract_type = request.form['contract_type']
        payment_cycle = request.form['payment_cycle']
        allowance = request.form.get('allowance', type=int)
        tax_rate = request.form.get('tax_rate', type=float) / 100 

        existing_info = get_employee_salary_info(employee_id)

        try:
            if existing_info:
                # UPDATE
                cursor.execute("""
                    UPDATE salaries SET base_salary=?, contract_type=?, payment_cycle=?, allowance=?, tax_rate=?
                    WHERE employee_id=?
                """, (base_salary, contract_type, payment_cycle, allowance, tax_rate, employee_id))
                flash(f"직원 {employee_id}의 급여 정보가 수정되었습니다.", "success")
            else:
                # INSERT
                cursor.execute("""
                    INSERT INTO salaries (employee_id, base_salary, contract_type, payment_cycle, allowance, tax_rate)
                    VALUES (?, ?, ?, ?, ?, ?)
                """, (employee_id, base_salary, contract_type, payment_cycle, allowance, tax_rate))
                flash(f"직원 {employee_id}의 급여 정보가 등록되었습니다.", "success")
                
            conn.commit()
        except Exception as e:
            conn.rollback()
            flash(f"급여 정보 처리 중 오류 발생: {e}", "error")
        finally:
            conn.close()
            
        return redirect(url_for('salary_management'))

    # GET 요청: 정보 입력/수정 폼 렌더링
    employee_info = cursor.execute("SELECT id, name FROM employees WHERE id=?", (employee_id,)).fetchone()
    salary_info = get_employee_salary_info(employee_id)
    conn.close()
    
    if not employee_info:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        return redirect(url_for('salary_management'))
        
    return render_template('edit_salary.html', 
                           employee=employee_info, 
                           salary_info=salary_info)


@app.route('/salary/record_payroll', methods=['POST'])
@admin_required
def record_monthly_payroll():
    pay_date = request.form['pay_month'] # YYYY-MM 형식
    
    try:
        year = int(pay_date.split('-')[0])
        month = int(pay_date.split('-')[1])
    except ValueError:
        flash("날짜 형식이 올바르지 않습니다.", "error")
        return redirect(url_for('salary_management'))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 대상 직원 목록 및 급여 정보 조회 
    cursor.execute("""
        SELECT e.id, s.base_salary, s.allowance, s.tax_rate 
        FROM employees e
        JOIN salaries s ON e.id = s.employee_id
        WHERE e.status = '재직' AND e.id != 'admin'
    """)
    employees_with_salary = cursor.fetchall()
    
    success_count = 0
    
    for emp in employees_with_salary:
        emp_id = emp['id']
        
        # ✨ [핵심 수정] 해당 월의 근태 요약 정보를 가져옴
        summary = get_monthly_attendance_summary(emp_id, year, month)
        attendance_factor = summary['attendance_factor']
        
        # 🚨 보너스는 임시로 0으로 설정
        pay_result = calculate_net_pay(
            emp['base_salary'],
            emp['allowance'],
            emp['tax_rate'],
            attendance_factor,
            bonus=0 # 임시 보너스 0 전달
        )
        
        # 3. DB에 기록 (중복 삽입 방지)
        try:
            cursor.execute("""
                INSERT OR IGNORE INTO payroll_records 
                (employee_id, pay_date, gross_pay, deductions, net_pay, bonus, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                emp_id, 
                pay_date, 
                pay_result['gross_pay'], 
                pay_result['deductions'], 
                pay_result['net_pay'], 
                pay_result['bonus'], 
                f"{pay_date} 급여 기록 (근태 반영: {attendance_factor * 100:.1f}% 적용)"
            ))
            if cursor.rowcount > 0:
                success_count += 1
            
        except Exception as e:
            conn.rollback()
            flash(f"직원 {emp_id}의 급여 기록 중 오류 발생: {e}", "error")
            conn.close()
            return redirect(url_for('salary_management'))
            
    conn.commit()
    conn.close()
    
    if success_count > 0:
        flash(f"{pay_date} 급여가 총 {success_count}명의 직원에 대해 성공적으로 기록되었습니다. (근태 반영 완료)", "success")
    else:
        flash(f"{pay_date} 급여는 이미 기록되어 있거나 대상 직원이 없습니다.", "error")
        
    return redirect(url_for('salary_management'))


@app.route('/salary/payroll/<employee_id>', methods=['GET'])
@login_required
def view_payroll(employee_id):
    # 본인 또는 관리자만 조회 가능
    if g.user['role'] != 'admin' and g.user['id'] != employee_id:
        flash("다른 직원의 급여 명세에 접근할 수 없습니다.", "error")
        return redirect(url_for('salary_management'))
    
    pay_date = request.args.get('pay_date') # 쿼리 인수로 pay_date를 받도록 가정
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    employee = cursor.execute("SELECT id, name, department, position FROM employees WHERE id=?", (employee_id,)).fetchone()
    salary_info = get_employee_salary_info(employee_id)
    
    if not employee or not pay_date or not salary_info:
        flash("직원 정보 또는 급여 지급일이 유효하지 않습니다.", "error")
        conn.close()
        return redirect(url_for('salary_management'))
    
    # 1. 특정 월의 지급 기록 조회
    record = cursor.execute("SELECT * FROM payroll_records WHERE employee_id=? AND pay_date=?", (employee_id, pay_date)).fetchone()
    conn.close()
    
    if not record:
        flash(f"{pay_date} 급여 명세 기록이 없습니다.", "error")
        return redirect(url_for('salary_management'))
        
    # 2. 명세서 상세 출력을 위해 record에 allowance, bonus 정보를 추가
    record_dict = dict(record)
    
    # 3. 계산 함수를 다시 호출하여 상세 내역(수당)을 분리
    # 이 부분은 명세서 템플릿의 상세 계산을 위해 사용됨.
    calculated_detail = calculate_net_pay(
        salary_info['base_salary'],
        salary_info['allowance'],
        salary_info['tax_rate'],
        attendance_factor=1.0 # 기록 시 사용된 팩터가 DB에 없으므로 1.0으로 가정
    )
    
    record_dict['allowance'] = calculated_detail['allowance']
    record_dict['bonus'] = record['bonus'] # DB 기록된 실제 보너스 사용
        
    return render_template('payroll_detail.html', 
                           employee=employee,
                           record=record_dict)

# ----------------------------------------------------
# 앱 실행
# ----------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)
