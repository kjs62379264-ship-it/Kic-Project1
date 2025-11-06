from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
import sqlite3
from datetime import datetime, time, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
import os
from werkzeug.utils import secure_filename
import calendar 

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
    """사이드바 출퇴근 버튼 상태 결정 로직 (DB 연동)"""
    if not g.user:
        return dict(attendance_button_state=None)

    current_user_id = g.user['id']
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 오늘 승인된 휴가/외근 등이 있는지 확인
    cursor.execute("""
        SELECT request_type FROM leave_requests
        WHERE employee_id = ? AND status = '승인'
        AND ? BETWEEN start_date AND end_date
    """, (current_user_id, today_str))
    leave_today = cursor.fetchone()

    # 2. 출퇴근 기록 확인
    cursor.execute("""
        SELECT clock_in_time, clock_out_time FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (current_user_id, today_str))
    attendance_record = cursor.fetchone()
    conn.close()

    button_state = '출근'
    if leave_today:
        if '반차' in leave_today['request_type']:
            if attendance_record and attendance_record['clock_in_time'] and not attendance_record['clock_out_time']:
                button_state = '퇴근'
            elif attendance_record and attendance_record['clock_out_time']:
                 button_state = '완료' 
            else:
                 button_state = '출근'
        else:
            button_state = leave_today['request_type'] 
    elif attendance_record and attendance_record['clock_in_time'] and not attendance_record['clock_out_time']:
        button_state = '퇴근'
    elif attendance_record and attendance_record['clock_out_time']:
        button_state = '완료'
        
    return dict(attendance_button_state=button_state)

@app.route('/attendance/clock', methods=['POST'])
@login_required 
def clock():
    """출퇴근 버튼 클릭 처리 (DB 연동)"""
    current_user_id = g.user['id']
    now = datetime.now()
    today = now.date()

    status_dict = inject_attendance_status()
    button_state = status_dict.get('attendance_button_state')

    if button_state not in ['출근', '퇴근']:
        flash(f"현재 '{button_state}' 상태에서는 출퇴근 기록을 할 수 없습니다.", "error")
        return redirect(request.referrer or url_for('attendance'))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if button_state == '퇴근':
        cursor.execute("""
            SELECT id FROM attendance 
            WHERE employee_id = ? AND record_date = ? AND clock_out_time IS NULL
            ORDER BY id DESC LIMIT 1
        """, (current_user_id, today))
        last_record = cursor.fetchone()
        
        if last_record:
            record_id = last_record['id']
            cursor.execute("UPDATE attendance SET clock_out_time = ? WHERE id = ?", (now, record_id))
            flash("퇴근 처리되었습니다.", "success")
        else:
            flash("퇴근 처리할 출근 기록이 없습니다.", "error")

    elif button_state == '출근':
        status = '정상'
        if now.time() > time(9, 0, 59): 
            status = '지각'
        
        try:
            cursor.execute("""
                INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
                VALUES (?, ?, ?, ?)
            """, (current_user_id, today, now, status))
            flash("출근 처리되었습니다.", "success")
        except sqlite3.IntegrityError:
            flash("오늘은 이미 출근 기록이 있습니다. (반차의 경우에도 출근은 1회만 기록됩니다)", "error")
            
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

# ----------------------------------------------------
# 4.1. 근태 관리 라우트 (✨ DB 연동 완료)
# ----------------------------------------------------
def get_today_attendance_status(cursor, employee_id, today_str):
    """(헬퍼) 특정 직원의 오늘 최종 근태 상태를 결정"""
    
    # 1. 승인된 휴가/외근/출장 확인
    cursor.execute("""
        SELECT request_type FROM leave_requests
        WHERE employee_id = ? AND status = '승인' AND ? BETWEEN start_date AND end_date
    """, (employee_id, today_str))
    leave_record = cursor.fetchone()
    
    if leave_record:
        return leave_record['request_type']
        
    # 2. 출/퇴근 기록 확인
    cursor.execute("""
        SELECT clock_in_time, clock_out_time FROM attendance
        WHERE employee_id = ? AND record_date = ?
    """, (employee_id, today_str))
    att_record = cursor.fetchone()
    
    if att_record and att_record['clock_in_time']:
        if att_record['clock_out_time']:
            return '퇴근'
        else:
            return '재실'
            
    # 3. 위 두 경우 모두 아니면 '부재'
    return '부재'

@app.route('/attendance')
@login_required 
def attendance():
    """근태 대시보드 (DB 연동)"""
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    status_query = request.args.get('status', '')
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 모든 재직 직원 정보 + 출퇴근 기록 조인
    cursor.execute("""
        SELECT 
            e.id, e.name, e.department, e.position,
            a.clock_in_time, a.clock_out_time
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.record_date = ?
        WHERE e.status = '재직' AND e.id != 'admin'
    """, (today_str,))
    all_employees_raw = cursor.fetchall()
    
    today_attendance_data = {}
    status_counts = {'재실': 0, '휴가': 0, '외근/출장': 0, '부재': 0}

    # 2. 각 직원의 최종 상태 결정 (DB 헬퍼 함수 사용)
    for emp_row in all_employees_raw:
        emp_id = emp_row['id']
        final_status = get_today_attendance_status(cursor, emp_id, today_str)
        
        # 상태 카운트
        if final_status == '재실' or final_status == '퇴근':
            status_counts['재실'] += 1
        elif final_status in ['외근', '출장']:
            status_counts['외근/출장'] += 1
        elif final_status in ['연차', '오전 반차', '오후 반차', '병가', '기타']:
            status_counts['휴가'] += 1
        elif final_status == '부재':
            status_counts['부재'] += 1

        # 템플릿에 전달할 데이터
        today_attendance_data[emp_id] = {
            **dict(emp_row), 
            'status': final_status,
            'check_in': emp_row['clock_in_time'].split(' ')[1][:5] if emp_row['clock_in_time'] else None,
            'check_out': emp_row['clock_out_time'].split(' ')[1][:5] if emp_row['clock_out_time'] else None,
        }

    # 3. 검색 필터 적용
    total_employees_count = len(today_attendance_data)
    filtered_employees = []
    
    for emp in today_attendance_data.values():
        match = True
        if id_query and id_query.lower() not in emp['id'].lower(): match = False
        if name_query and name_query not in emp['name']: match = False
        if department_query and emp['department'] != department_query: match = False
        if position_query and emp['position'] != position_query: match = False
        
        if status_query:
            if status_query == '재실' and emp['status'] not in ['재실', '퇴근']:
                match = False
            elif status_query == '휴가' and emp['status'] not in ['연차', '오전 반차', '오후 반차', '병가', '기타']:
                match = False
            elif status_query == '외근/출장' and emp['status'] not in ['외근', '출장']:
                match = False
            elif status_query == '부재' and emp['status'] != '부재':
                match = False
        
        if match:
            filtered_employees.append(emp)

    # 4. 근태 요청 현황 (DB에서 실제 데이터 가져오기)
    page = request.args.get('pending_page', 1, type=int) 
    PER_PAGE = 3
    
    if g.user['role'] == 'admin':
        cursor.execute("SELECT COUNT(*) FROM leave_requests WHERE status = '미승인'")
        total_requests = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT lr.*, e.name, e.department 
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.status = '미승인'
            ORDER BY lr.requested_at ASC
            LIMIT ? OFFSET ?
        """, (PER_PAGE, (page - 1) * PER_PAGE))
        paginated_requests = cursor.fetchall()
        
    else:
        cursor.execute("SELECT COUNT(*) FROM leave_requests WHERE employee_id = ?", (g.user['id'],))
        total_requests = cursor.fetchone()[0]
        
        cursor.execute("""
            SELECT lr.*, e.name, e.department 
            FROM leave_requests lr
            JOIN employees e ON lr.employee_id = e.id
            WHERE lr.employee_id = ?
            ORDER BY lr.requested_at DESC
            LIMIT ? OFFSET ?
        """, (g.user['id'], PER_PAGE, (page - 1) * PER_PAGE))
        paginated_requests = cursor.fetchall()

    total_pages = (total_requests + PER_PAGE - 1) // PER_PAGE
    
    # 5. 부서/직급 필터용 데이터
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
                            today_date=today_str)

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
    
    today_str = datetime.now().strftime('%Y-%m-%d')
    today_status = get_today_attendance_status(cursor, employee_id, today_str)
    
    # (임시 샘플 기록)
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
# 4.2. 근태 요청 라우트 (✨ 새로 추가)
# ----------------------------------------------------
@app.route('/attendance/request', methods=['GET', 'POST'])
@login_required
def add_leave_request():
    if request.method == 'POST':
        request_type = request.form['request_type']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        reason = request.form.get('reason', '')
        
        # 날짜 유효성 검사
        if start_date > end_date:
            flash("시작일이 종료일보다 늦을 수 없습니다.", "error")
            return render_template('add_leave_request.html')
            
        try:
            conn = sqlite3.connect('employees.db')
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO leave_requests (employee_id, request_type, start_date, end_date, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (g.user['id'], request_type, start_date, end_date, reason))
            conn.commit()
            flash("근태 요청이 성공적으로 제출되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"요청 제출 중 오류 발생: {e}", "error")
        finally:
            conn.close()
            
        return redirect(url_for('attendance'))

    return render_template('add_leave_request.html')

@app.route('/attendance/request/process/<int:request_id>', methods=['POST'])
@admin_required
def process_leave_request(request_id):
    action = request.form.get('action') # '승인' 또는 '반려'
    
    if action not in ['승인', '반려']:
        flash("잘못된 요청입니다.", "error")
        return redirect(url_for('attendance'))
        
    try:
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE leave_requests SET status = ? WHERE id = ?", (action, request_id))
        conn.commit()
        flash(f"요청이 {action} 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"처리 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('attendance'))
    
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
        cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + '%',))
        last_id = cursor.fetchone()
        new_seq = int(last_id[0][-4:]) + 1 if last_id and last_id[0].startswith(prefix) else 1
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
            # profile_image는 DB에서 DEFAULT 'default.jpg'로 설정됨
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
            flash(f"등록 실패: {e} (사번 {new_id}가 이미 존재할 수 있습니다)", "error")
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
        profile_image_filename = employee['profile_image'] # 기본값은 현재 이미지

        # (✨ 사진 삭제 로직 추가)
        delete_image = request.form.get('delete_profile_image')

        if delete_image:
             profile_image_filename = 'default.jpg' # 기본 이미지로 변경
        elif 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                profile_image_filename = filename # 새 파일명으로 교체

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
    
    # GET 요청
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
# 8. 급여 관리 (Salary) 라우트 (✨ 근태 연동 완료)
# ----------------------------------------------------

# ----------------------------------------------------
# 8.1. 근태 데이터 조회 헬퍼
# ----------------------------------------------------
def get_monthly_attendance_summary(employee_id, year, month):
    """
    특정 직원의 특정 월에 대한 근태 기록을 요약하여 반환합니다.
    (급여 계산을 위한 근태율(attendance_factor) 계산이 핵심)
    """
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    # 1. 해당 월의 총 근무일 (주말 제외)
    num_days_in_month = calendar.monthrange(year, month)[1]
    weekdays_count = 0
    for day in range(1, num_days_in_month + 1):
        weekday = date(year, month, day).weekday()
        if weekday < 5: # 0(월)~4(금)
            weekdays_count += 1
            
    # 2. 승인된 '연차', '병가', '반차', '기타' 일수 계산 (급여 차감/조정 대상)
    # (✨ '외근', '출장'은 급여 차감 대상이 아니므로 제외)
    cursor.execute("""
        SELECT start_date, end_date, request_type FROM leave_requests
        WHERE employee_id = ? AND status = '승인'
        AND (request_type LIKE '%연차%' OR request_type LIKE '%반차%' OR request_type = '병가' OR request_type = '기타')
    """, (employee_id,))
    leave_requests = cursor.fetchall()

    unpaid_leave_days = 0.0 # ✨ float으로 변경
    month_start = date(year, month, 1)
    month_end = date(year, month, num_days_in_month)

    for req in leave_requests:
        start = datetime.strptime(req['start_date'], '%Y-%m-%d').date()
        end = datetime.strptime(req['end_date'], '%Y-%m-%d').date()
        
        # 겹치는 기간 계산
        overlap_start = max(start, month_start)
        overlap_end = min(end, month_end)
        
        if overlap_start <= overlap_end:
            current_day = overlap_start
            while current_day <= overlap_end:
                if current_day.weekday() < 5: # 평일만 카운트
                    if '반차' in req['request_type']:
                        unpaid_leave_days += 0.5
                    else:
                        unpaid_leave_days += 1.0
                # 날짜 증가
                current_day += timedelta(days=1) 
                
    # 3. 유효 근무일 (총 평일수 - 유급 휴가/병가)
    effective_work_days = weekdays_count - unpaid_leave_days
    
    # 4. 근태율 (유효 근무일 / 총 평일수)
    if weekdays_count == 0:
        attendance_factor = 1.0
    else:
        # (결근일수만큼 급여 차감)
        attendance_factor = effective_work_days / weekdays_count
        if attendance_factor < 0: # (혹시 모를 오류 방지)
            attendance_factor = 0

    conn.close()
    
    return {
        'weekdays_count': weekdays_count,
        'unpaid_leave_days': unpaid_leave_days, # (연차/병가/반차 합계)
        'attendance_factor': attendance_factor # (급여 계산에 사용할 비율)
    }

# ----------------------------------------------------
# 8.2. 급여 계산 핵심 로직 (✨ 수정됨)
# ----------------------------------------------------
def calculate_net_pay(base_salary, allowance, tax_rate, attendance_factor=1.0, bonus=0):
    """
    기본 급여 정보와 근태율을 바탕으로 실수령액을 계산합니다.
    (4대 보험 등 복잡한 공제는 단순화하여 소득세율로만 처리합니다.)
    """
    
    monthly_base = base_salary / 12
    
    # 근태(결근/휴가)가 반영된 기본급
    adjusted_base = monthly_base * attendance_factor
    # 총 지급액 = 근태반영 기본급 + 고정수당 + 보너스
    total_gross_pay = adjusted_base + allowance + bonus
    
    # 공제액 (총 지급액 기준)
    # (가정: 4대보험 9% + 소득세(tax_rate))
    # (음수가 되지 않도록 max 사용)
    deductions = int(max(0, total_gross_pay * (tax_rate + 0.09)))
    
    # 실수령액
    net_pay = total_gross_pay - deductions
    
    return {
        'gross_pay': int(total_gross_pay),
        'deductions': deductions,
        'net_pay': int(net_pay),
        'bonus': int(bonus),
        'allowance': int(allowance)
    }
    
# ----------------------------------------------------
# 8.3. 급여 DB 조회 헬퍼
# ----------------------------------------------------
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

# ----------------------------------------------------
# 8.4. 급여 관리 메인 라우트
# ----------------------------------------------------
@app.route('/salary')
@login_required
def salary_management():
    current_month = datetime.now().strftime('%Y-%m')
    
    # 관리자는 전체 직원의 급여 정보를 보고 관리할 수 있음
    if g.user['role'] == 'admin':
        employees_with_salary = get_all_employees_with_salary()
        
        # 관리자용: 현재 월에 이미 기록된 급여 내역 조회
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT pr.*, e.name 
            FROM payroll_records pr
            JOIN employees e ON pr.employee_id = e.id
            WHERE pr.pay_date = ?
            ORDER BY e.name
        """, (current_month,))
        current_month_records = cursor.fetchall()
        conn.close()

        return render_template('salary_management.html', 
                               is_admin=True, 
                               employees=employees_with_salary,
                               current_month_records=current_month_records, # (현재 월 기록)
                               current_month=current_month) # (급여 계산 폼용)
    
    # 일반 직원은 자신의 급여 기록만 볼 수 있음
    else:
        salary_info = get_employee_salary_info(g.user['id'])
        payroll_records = get_employee_payroll_records(g.user['id'])
        
        return render_template('salary_management.html', 
                               is_admin=False, 
                               salary_info=salary_info,
                               payroll_records=payroll_records)

# ----------------------------------------------------
# 8.5. 급여 정보 등록/수정 라우트
# ----------------------------------------------------
@app.route('/salary/add_info/<employee_id>', methods=['GET', 'POST'])
@admin_required
def add_salary_info(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row 
    cursor = conn.cursor()
    
    if request.method == 'POST':
        base_salary = request.form.get('base_salary', type=int)
        contract_type = request.form['contract_type']
        payment_cycle = request.form['payment_cycle']
        allowance = request.form.get('allowance', 0, type=int)
        tax_rate_percent = request.form.get('tax_rate', 5.0, type=float)
        tax_rate = tax_rate_percent / 100.0 # %로 입력받아 실수로 변환

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

    # GET 요청
    employee_info = cursor.execute("SELECT id, name FROM employees WHERE id=?", (employee_id,)).fetchone()
    salary_info = get_employee_salary_info(employee_id) 
    conn.close()
    
    if not employee_info:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        return redirect(url_for('salary_management'))
        
    return render_template('edit_salary.html', 
                           employee=employee_info, 
                           salary_info=salary_info) 

# ----------------------------------------------------
# 8.6. 급여 명세 상세 조회 라우트
# ----------------------------------------------------
@app.route('/salary/payroll/<employee_id>')
@login_required
def view_payroll(employee_id):
    pay_date = request.args.get('pay_date')
    if not pay_date:
        flash("조회할 급여 월을 지정해야 합니다.", "error")
        return redirect(url_for('salary_management'))

    if g.user['role'] != 'admin' and g.user['id'] != employee_id:
        flash("다른 직원의 급여 명세에 접근할 수 없습니다.", "error")
        return redirect(url_for('salary_management'))
        
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    employee = cursor.execute("SELECT id, name, department, position FROM employees WHERE id=?", (employee_id,)).fetchone()
    if not employee:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('salary_management'))
    
    record = cursor.execute("""
        SELECT * FROM payroll_records WHERE employee_id=? AND pay_date=?
    """, (employee_id, pay_date)).fetchone()
    
    conn.close()
    
    if not record:
        flash(f"{pay_date}에 해당하는 급여 기록을 찾을 수 없습니다.", "error")
        return redirect(url_for('salary_management'))
        
    return render_template('payroll_detail.html', 
                           employee=employee,
                           record=record)

# ----------------------------------------------------
# 8.7. 월별 급여 기록 라우트
# ----------------------------------------------------
@app.route('/salary/record_payroll', methods=['POST'])
@admin_required
def record_monthly_payroll():
    pay_date_str = request.form['pay_month'] # YYYY-MM 형식
    
    try:
        pay_date_obj = datetime.strptime(pay_date_str, '%Y-%m')
        year = pay_date_obj.year
        month = pay_date_obj.month
    except ValueError:
        flash("올바르지 않은 날짜 형식입니다 (YYYY-MM).", "error")
        return redirect(url_for('salary_management'))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # (급여 정보가 등록된) 재직 직원 목록
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
        
        # 1. 근태 반영 요소 (DB 조회)
        attendance_summary = get_monthly_attendance_summary(emp_id, year, month)
        attendance_factor = attendance_summary['attendance_factor']
        
        bonus = 0 # (임시: 보너스 0)
        
        # 2. 급여 계산
        pay_result = calculate_net_pay(
            emp['base_salary'],
            emp['allowance'],
            emp['tax_rate'],
            attendance_factor,
            bonus
        )
        
        memo = f"{pay_date_str} 급여. (평일: {attendance_summary['weekdays_count']}일, 유급휴가/병가: {attendance_summary['unpaid_leave_days']}일, 근태율: {attendance_factor*100:.0f}%)"

        # 3. DB 기록
        try:
            # (INSERT OR IGNORE: 이미 해당 월에 기록이 있으면 무시)
            cursor.execute("""
                INSERT OR IGNORE INTO payroll_records 
                (employee_id, pay_date, gross_pay, deductions, net_pay, bonus, allowance, memo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                emp_id, 
                pay_date_str, 
                pay_result['gross_pay'], 
                pay_result['deductions'], 
                pay_result['net_pay'], 
                pay_result['bonus'],
                pay_result['allowance'],
                memo
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
        flash(f"{pay_date_str} 급여가 총 {success_count}명의 직원에 대해 성공적으로 기록되었습니다.", "success")
    else:
        flash(f"{pay_date_str} 급여는 이미 기록되어 있거나 대상 직원이 없습니다.", "error")
        
    return redirect(url_for('salary_management'))

# ----------------------------------------------------
# 8.8. 급여 기록 삭제 라우트
# ----------------------------------------------------
@app.route('/salary/payroll/delete/<int:record_id>', methods=['POST'])
@admin_required
def delete_payroll_record(record_id):
    """지정된 ID의 월별 급여 기록을 삭제합니다."""
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    record = cursor.execute("SELECT employee_id, pay_date FROM payroll_records WHERE id = ?", (record_id,)).fetchone()
    
    if record:
        try:
            cursor.execute("DELETE FROM payroll_records WHERE id = ?", (record_id,))
            conn.commit()
            flash(f"{record['employee_id']} 직원의 {record['pay_date']} 급여 기록(ID: {record_id})이 삭제되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"삭제 중 오류 발생: {e}", "error")
        finally:
            conn.close()
    else:
        flash("삭제할 급여 기록을 찾을 수 없습니다.", "error")
        conn.close()

    return redirect(url_for('salary_management'))
    
# ----------------------------------------------------
# 앱 실행
# ----------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)