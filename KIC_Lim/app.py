from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort
import sqlite3
from datetime import datetime, time
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
# ✨ [병합 1] 프로필 사진 업로드를 위한 라이브러리 추가
import os
from werkzeug.utils import secure_filename

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# ✨ [병합 2] 업로드 폴더 설정 추가
UPLOAD_FOLDER = os.path.join(app.static_folder, 'profile_photos')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------------------------------
# 1. 인증 전처리 및 데코레이터 (새 시스템 유지)
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
        
        # ✨ [병합 3] g.user를 수정 가능한 dict로 변경 (기존 기능 호환)
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
            # ✨ [수정] 근태관리 대시보드(attendance)로 리다이렉트
            return redirect(url_for('hr_management')) 
        return view(**kwargs)
    return wrapped_view


# ----------------------------------------------------
# 2. 로그인/로그아웃 라우트 (새 시스템 유지)
# ----------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user:
        return redirect(url_for('hr_management')) # ✨ [수정] 로그인 후 인사관리로 이동

    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # role 정보도 함께 가져옴
        cursor.execute("SELECT employee_id, password_hash, role, username FROM users WHERE username = ?", (username,))
        user_record = cursor.fetchone()
        conn.close()
        
        if user_record and check_password_hash(user_record['password_hash'], password):
            # ✨ [수정] employee_id를 세션에 저장 (g.user 로드를 위함)
            session['user_id'] = user_record['employee_id'] 
            flash(f"환영합니다, {user_record['username']}님! ({'관리자' if user_record['role'] == 'admin' else '직원'})", "success")
            return redirect(url_for('hr_management')) # ✨ [수정] 로그인 후 인사관리로 이동
        else:
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")

    return render_template('login.html') # ✨ [수정] login.html 사용 (기존과 동일)

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))

# ----------------------------------------------------
# ✨ [병합 4] 비밀번호 변경 라우트 (기존 기능 추가)
# ----------------------------------------------------
@app.route('/change_password', methods=['GET', 'POST'])
@login_required # 로그인이 필요합니다.
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']

        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # ✨ [수정] users 테이블에서 현재 유저의 password_hash를 가져옴
        cursor.execute("SELECT password_hash FROM users WHERE employee_id = ?", (g.user['id'],))
        user_record = cursor.fetchone()

        # 1. 현재 비밀번호가 맞는지 확인
        if not (user_record and check_password_hash(user_record['password_hash'], current_password)):
            flash("현재 비밀번호가 일치하지 않습니다.", "error")
            conn.close()
            return redirect(url_for('change_password'))

        # 2. 새 비밀번호와 확인용 비밀번호가 일치하는지 확인
        if new_password != confirm_password:
            flash("새 비밀번호가 일치하지 않습니다.", "error")
            conn.close()
            return redirect(url_for('change_password'))
            
        # 3. 새 비밀번호로 업데이트
        try:
            new_password_hash = generate_password_hash(new_password)
            # ✨ [수정] users 테이블의 password_hash를 업데이트
            cursor.execute("UPDATE users SET password_hash = ? WHERE employee_id = ?", 
                           (new_password_hash, g.user['id']))
            conn.commit()
            flash("비밀번호가 성공적으로 변경되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"오류가 발생했습니다: {e}", "error")
        finally:
            conn.close()
        
        return redirect(url_for('hr_management')) # ✨ [수정] 성공 시 인사관리로

    # GET 요청 시: 비밀번호 변경 폼 페이지를 보여줌
    return render_template('change_password.html')

# ----------------------------------------------------
# 3. 출퇴근 상태 및 라우트 (새 시스템 유지)
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
    # (새 시스템의 로직 그대로 유지)
    current_user_id = g.user['id']
    now = datetime.now()
    today = now.date()
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
    return redirect(request.referrer or url_for('attendance'))


# ----------------------------------------------------
# 4. 보호된 주요 라우트 (새 시스템 + 기존 기능 병합)
# ----------------------------------------------------

@app.route('/')
@login_required
def root():
    # ✨ [수정] 루트(/)로 접근 시 근태관리 메인으로 리다이렉트
    return redirect(url_for('hr_management'))

# ( /dashboard 라우트는 새 코드에 있지만, attendance_page.html과 겹치므로 삭제)

@app.route('/attendance')
@login_required 
def attendance():
    # (새 시스템의 근태 현황 로직 그대로 유지)
    # ... (생략) ...
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    status_query = request.args.get('status', '')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    today_attendance_data = {}
    # ✨ [버그 수정] 'admin' 계정은 근태 현황 목록에서 제외
    cursor.execute("SELECT * FROM employees WHERE id != 'admin' ORDER BY id")
    all_employees = cursor.fetchall()
    
    # (이하 임시 로직은 새 코드 그대로 유지)
    # ... (생략) ...
    for emp in all_employees:
        emp_id = emp['id']
        status = '부재' # 기본값
        check_in = None
        
        if emp_id == '25HR0001': # 관리자
            status = '재실'
            check_in = '08:50'
        elif emp_id == '25DV0002': # 일반직원
            status = '휴가'
        elif emp_id == '25DV0003': # 김개발
            status = '재실'
            check_in = '09:05'
        elif emp_id == '25HR0005': # 이인사
            status = '출장'
            check_in = '08:40'
        elif emp_id == '25DS0006': # 최디자인
            status = '외근'
            check_in = '09:10'
        
        today_attendance_data[emp_id] = {
            **dict(emp), 
            'status': status,
            'check_in': check_in,
            'check_out': None, 
            'leave_status': '연차' if status == '휴가' else None
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

    total_onsite_count = 0 
    total_leave_count = 0  
    total_out_count = 0    
    total_absent_count = 0 
    status_counts = {'재실': 0, '휴가': 0, '외근/출장': 0, '부재': 0}
    
    for emp in today_attendance_data.values():
        status = emp['status']
        if status == '재실':
            total_onsite_count += 1
            status_counts['재실'] += 1
        elif status == '휴가':
            total_leave_count += 1
            status_counts['휴가'] += 1
        elif status in ['외근', '출장']:
            total_out_count += 1
            status_counts['외근/출장'] += 1
        elif status == '부재': 
            total_absent_count += 1
            status_counts['부재'] += 1
            
    total_pending_count = 1 
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    conn.close()
    
    # (새 코드의 임시 'pending_requests' 데이터는 그대로 유지)
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
                            total_onsite_count=total_onsite_count,
                            total_leave_count=total_leave_count,
                            total_out_count=total_out_count,
                            total_pending_count=total_pending_count,
                            status_counts=status_counts,
                            total_absent_count=total_absent_count)

@app.route('/attendance/employee/<employee_id>')
@login_required # 모든 직원이 자신의 상세 정보를 볼 수 있어야 함
def attendance_detail(employee_id):
    # (새 시스템의 근태 상세 로직 그대로 유지)
    # ... (생략) ...
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    
    if not employee:
        flash(f"직원 ID {employee_id}를 찾을 수 없습니다.", "error")
        return redirect(url_for('attendance'))
    
    # (새 코드의 임시 'TEMP_ATTENDANCE_STATUS' 로직은 그대로 유지)
    TEMP_ATTENDANCE_STATUS = {
        '25HR0001': {'status': '재실', 'color': 'green'}, 
        '25DV0002': {'status': '휴가', 'color': '#3498db'},
        '25DV0003': {'status': '재실', 'color': 'green'},
        '25MK0004': {'status': '부재', 'color': 'red'},
        '25HR0005': {'status': '출장', 'color': '#1abc9c'},
        '25DS0006': {'status': '외근', 'color': '#f39c12'},
    }
    today_status_info = TEMP_ATTENDANCE_STATUS.get(employee_id, {'status': '정보 없음', 'color': 'black'})
    today_status = today_status_info['status']
    
    # (새 코드의 임시 'sample_records' 로직은 그대로 유지)
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
# 5. 인사 관리 (HR) 라우트 (기존 기능 병합 및 수정)
# ----------------------------------------------------

@app.route('/hr')
@login_required #
def hr_management():
    # ... (기존 로직) ...
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
    # ✨ [버그 수정] 'admin' 계정은 목록에서 제외
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
    
    # ✨ [버그 수정] 차트에서도 'admin' 계정 제외
    cursor.execute("""
        SELECT department, COUNT(*) as count 
        FROM employees WHERE status = '재직' AND id != 'admin'
        GROUP BY department ORDER BY count DESC
    """)
    dept_stats = cursor.fetchall()
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['count'] for row in dept_stats]

    # ✨ [병합 5] 공지사항 기능 추가
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
                           notices=notices, # ✨ [병합 5] 공지사항 전달
                           request=request)

@app.route('/hr/add', methods=['GET', 'POST'])
@admin_required # 관리자 전용
def add_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'POST':
        # --- 1. 직원 정보 (employees 테이블) ---
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        phone_number = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
        email = f"{request.form['email_id']}@{request.form['email_domain']}"
        address = request.form['address']
        gender = request.form['gender']
        
        # 사번 생성 (기존 로직)
        cursor.execute("SELECT code FROM departments WHERE name = ?", (department,))
        dept_code_row = cursor.fetchone()
        dept_code = dept_code_row[0] if dept_code_row else 'XX'
        year_prefix = hire_date.split('-')[0][2:]
        prefix = year_prefix + dept_code
        cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (prefix + '%',))
        last_id = cursor.fetchone()
        new_seq = int(last_id[0][-4:]) + 1 if last_id else 1
        new_id = f"{prefix}{new_seq:04d}"
        
        # --- 2. 로그인 정보 (users 테이블) ---
        # ✨ [병합 6] 폼에서 초기 비밀번호와 역할(role) 받기
        password = request.form['password'] # (add_employee.html에 <input name="password"> 필요)
        role = request.form.get('role', 'user') # (add_employee.html에 <select name="role"> 필요)

        if not password:
            flash("초기 비밀번호를 입력해야 합니다.", "error")
            # (GET 요청과 동일한 로직으로 폼을 다시 보여줌)
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
            # ✨ [병합 6] 두 테이블에 모두 INSERT (트랜잭션)
            cursor.execute("""
                INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status) 
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, '재직')
            """, (new_id, name, department, position, hire_date, phone_number, email, address, gender))
            
            cursor.execute("""
                INSERT INTO users (employee_id, username, password_hash, role)
                VALUES (?, ?, ?, ?)
            """, (new_id, new_id, password_hash, role)) # (사번을 username으로 동일하게 사용)
            
            conn.commit()
            flash(f"직원 {name}({new_id})이(가) 성공적으로 등록되었습니다.", "success")
        except sqlite3.IntegrityError as e:
            conn.rollback()
            flash(f"등록 실패: {e}", "error")
        finally:
            conn.close()
            
        return redirect(url_for('hr_management'))
    
    # (GET 요청)
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    conn.close()
    return render_template('add_employee.html', departments=departments, positions=positions, email_domains=email_domains)

@app.route('/hr/employee/<employee_id>')
# ✨ [병합 7] @login_required로 변경 (모든 사용자가 상세정보 접근 가능)
@login_required 
def employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # ✨ [병합 7] employees 테이블과 users 테이블을 JOIN 하여 role 정보도 함께 가져옴
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
# ✨ [병합 8] @login_required로 변경
@login_required 
def edit_employee(employee_id):
    
    # ✨ [병합 8] 관리자 또는 본인만 수정 가능하도록 내부에서 권한 확인
    if g.user['role'] != 'admin' and g.user['id'] != employee_id:
        flash("수정 권한이 없습니다.", "error")
        return redirect(url_for('employee_detail', employee_id=employee_id))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # (POST든 GET이든 현재 직원 정보를 먼저 가져옴)
    employee = cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not employee:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('hr_management'))

    if request.method == 'POST':
        # 1. 폼 데이터 받기 (기존)
        name = request.form['name']
        department = request.form['department']
        position = request.form['position']
        hire_date = request.form['hire_date']
        phone_number = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
        email = f"{request.form['email_id']}@{request.form['email_domain']}"
        address = request.form['address']
        gender = request.form['gender']
        
        # ✨ [병합 8] 역할(role)과 프로필 사진 처리
        role = request.form.get('role', None)
        profile_image_filename = employee['profile_image'] # 1. 기본값은 현재 이미지

        # 2. 새 파일이 업로드되었는지 확인
        if 'profile_image' in request.files:
            file = request.files['profile_image']
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                file.save(save_path)
                profile_image_filename = filename # 3. 새 파일이 있으면 파일명 교체

        try:
            # 4. employees 테이블 업데이트
            cursor.execute("""
                UPDATE employees SET name=?, department=?, position=?, hire_date=?, 
                               phone_number=?, email=?, address=?, gender=?, 
                               profile_image=?
                WHERE id=?
            """, (name, department, position, hire_date, phone_number, email, 
                  address, gender, profile_image_filename, employee_id))
            
            # 5. [관리자 전용] users 테이블의 role 업데이트
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
    
    # (GET 요청)
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = cursor.fetchall()
    cursor.execute("SELECT name FROM positions ORDER BY name")
    positions = cursor.fetchall()
    cursor.execute("SELECT domain FROM email_domains ORDER BY domain")
    email_domains = cursor.fetchall()
    
    # ✨ [병합 8] role 정보도 가져오기 (관리자용)
    user_role_info = cursor.execute("SELECT role FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
    conn.close()

    phone_parts = employee['phone_number'].split('-') if employee and employee['phone_number'] else ['','','']
    email_parts = employee['email'].split('@') if employee and employee['email'] else ['','']
    
    # (employee 딕셔너리로 변환 후 role 정보 추가)
    employee_dict = dict(employee)
    employee_dict['role'] = user_role_info['role'] if user_role_info else 'user'

    return render_template('edit_employee.html', 
                           employee=employee_dict, # ✨ 수정된 딕셔너리 전달
                           departments=departments, 
                           positions=positions, 
                           email_domains=email_domains,
                           phone_parts=phone_parts,
                           email_parts=email_parts)

@app.route('/hr/print')
@admin_required # 관리자 전용
def print_employees():
    # ... (기존 로직) ...
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
    # ✨ [버그 수정] 'admin' 계정은 인쇄 목록에서 제외
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
@admin_required # 관리자 전용
def process_departure(employee_id):
    # (기존 로직 그대로 유지)
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        # ✨ [병합 9] 퇴사 처리 시, 직원 상태 '퇴사'로 변경
        cursor.execute("UPDATE employees SET status = '퇴사' WHERE id = ?", (employee_id,))
        # ✨ [병합 9] 로그인 계정도 비활성화 (예: role을 'disabled'로 변경)
        cursor.execute("UPDATE users SET role = 'user' WHERE employee_id = ?", (employee_id,)) 
        # (혹은 계정을 삭제할 수도 있으나, 우선 role을 user로 강등)
        conn.commit()
        flash(f"직원({employee_id})이 퇴사 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"처리 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('employee_detail', employee_id=employee_id))
    
@app.route('/hr/rehire/<employee_id>', methods=['POST'])
@admin_required # 관리자 전용
def process_rehire(employee_id):
    # (기존 로직 그대로 유지)
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("UPDATE employees SET status = '재직' WHERE id = ?", (employee_id,))
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 재입사 처리되었습니다.", "success")
    return redirect(url_for('employee_detail', employee_id=employee_id))

# ----------------------------------------------------
# 6. 설정 (Settings) 라우트 (기존 기능 병합)
# ----------------------------------------------------

@app.route('/hr/settings')
@admin_required # 관리자 전용
def settings_management():
    # (기존 로직 그대로 유지)
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
@admin_required # 관리자 전용
def add_department():
    # (기존 로직 그대로 유지)
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
@admin_required # 관리자 전용
def add_position():
    # (기존 로직 그대로 유지)
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
@admin_required # 관리자 전용
def delete_department(dept_name):
    # (기존 로직 그대로 유지)
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
@admin_required # 관리자 전용
def delete_position(pos_name):
    # (기존 로직 그대로 유지)
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
@admin_required # 관리자 전용
def edit_department():
    original_name = request.form['original_dept_name']
    new_name = request.form['new_dept_name'].strip()
    # ✨ [버그 수정] new_dept_code로 수정 (기존 버그)
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
# 7. 공지사항 (Notice) 라우트 (기존 기능 병합)
# ----------------------------------------------------

@app.route('/hr/notices/add', methods=['GET', 'POST'])
@admin_required # 관리자 전용
def add_notice_page():
    if request.method == 'POST':
        title = request.form['title']
        # ✨ [핵심 수정] .strip()을 사용하여 앞뒤 공백 제거
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
@admin_required # 관리자 전용
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
    
    # Fetch the specific notice by its ID
    # ✨ [수정] SQL에서 datetime() 함수 제거 (Python에서 처리)
    cursor.execute("SELECT * FROM notices WHERE id = ?", (notice_id,))
    notice_row = cursor.fetchone()
    conn.close()
    
    if notice_row is None:
        flash("해당 공지사항을 찾을 수 없습니다.", "error")
        return redirect(url_for('hr_management'))

    # ✨ [핵심 수정] DB에서 가져온 notice_row(읽기 전용)를 수정 가능한 dict로 변환
    notice = dict(notice_row)
    
    # ✨ [핵심 수정] 'created_at' 문자열을 datetime 객체로 변환
    if notice['created_at']:
        try:
            # SQLite의 기본 DATETIME 형식(YYYY-MM-DD HH:MM:SS)을 파싱
            notice['created_at'] = datetime.strptime(notice['created_at'], '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # 혹시 다른 형식이거나 파싱 실패 시 None으로 처리
            notice['created_at'] = None
    else:
        notice['created_at'] = None
        
    # Render the detail template with the converted notice data
    return render_template('notice_detail.html', notice=notice)

# ----------------------------------------------------
# 앱 실행
# ----------------------------------------------------

if __name__ == '__main__':
    app.run(debug=True)