from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, jsonify
import sqlite3
from datetime import datetime, time, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
import os
from werkzeug.utils import secure_filename
import calendar
from dateutil.relativedelta import relativedelta

# --- 0. 헬퍼 함수 정의 ---

def get_most_recent_weekday(date_obj):
    """주말(토/일)인 경우, 가장 최근의 평일 날짜를 반환합니다."""
    weekday = date_obj.weekday()  # 월요일=0, 일요일=6

    if weekday == 5:  # 토요일
        return date_obj - timedelta(days=1)
    elif weekday == 6:  # 일요일
        return date_obj - timedelta(days=2)
    else:
        return date_obj

def calculate_work_duration(clock_in_str, clock_out_str, lunch_minutes=60):
    """
    출퇴근 시간 문자열을 받아 총 근무시간(휴게시간 제외)을 계산합니다.
    - 4시간 이상 근무 시에만 60분의 휴게 시간을 차감합니다.
    """
    if not clock_in_str or not clock_out_str or clock_in_str == '-' or clock_out_str == '-':
        return 'N/A'
    
    # DB에 YYYY-MM-DD HH:MM:SS 형식이 저장된다고 가정하고 시간만 추출하여 계산합니다.
    try:
        in_time_str = clock_in_str.split(' ')[-1]
        out_time_str = clock_out_str.split(' ')[-1]
        
        in_time = datetime.strptime(in_time_str, '%H:%M:%S')
        out_time = datetime.strptime(out_time_str, '%H:%M:%S')
    except ValueError:
        return '오류'

    # 자정 넘김 처리 (간단화: 퇴근 시간이 출근 시간보다 앞선 경우 1일 추가)
    if out_time < in_time:
        duration = (out_time + timedelta(days=1)) - in_time
    else:
        duration = out_time - in_time

    duration_seconds = duration.total_seconds()
    
    LUNCH_THRESHOLD_SECONDS = 4 * 3600 # 4시간
    lunch_seconds = lunch_minutes * 60

    if duration_seconds >= LUNCH_THRESHOLD_SECONDS:
        working_seconds = duration_seconds - lunch_seconds
    else:
        working_seconds = duration_seconds
        
    if working_seconds < 0:
        working_seconds = 0
        
    hours = int(working_seconds // 3600)
    minutes = int((working_seconds % 3600) // 60)
    
    return f"{hours}h {minutes}m"

def get_today_attendance(employee_id):
    """오늘의 근태 기록(최종 레코드)을 조회합니다."""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    today = datetime.now().date().strftime('%Y-%m-%d')
    
    cursor.execute("""
        SELECT clock_in_time, clock_out_time, attendance_status
        FROM attendance 
        WHERE employee_id = ? AND record_date = ?
    """, (employee_id, today))
    record = cursor.fetchone()
    conn.close()
    
    return record

def get_last_attendance_record(employee_id):
    """가장 최근의 출퇴근 기록을 조회하여 버튼 상태를 결정합니다."""
    record = get_today_attendance(employee_id)
    
    if record:
        # 출근 기록은 있으나 퇴근 기록이 없으면 '퇴근' 버튼 표시
        if record['clock_in_time'] and not record['clock_out_time']:
            return '퇴근'
        # 출퇴근 기록이 모두 있으면 '근무 완료'
        elif record['clock_in_time'] and record['clock_out_time']:
            return '근무 완료'
    
    # 기록이 없으면 '출근' 버튼 표시
    return '출근'
    
def get_attendance_records_for_month(employee_id, target_date):
    """특정 월의 모든 근태 기록을 조회하여 캘린더 구성에 사용합니다."""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    start_of_month = target_date.replace(day=1).strftime('%Y-%m-%d')
    end_of_month = (target_date + relativedelta(months=1)).replace(day=1) - timedelta(days=1)
    end_of_month = end_of_month.strftime('%Y-%m-%d')

    cursor.execute("""
        SELECT record_date, attendance_status
        FROM attendance 
        WHERE employee_id = ? AND record_date BETWEEN ? AND ?
    """, (employee_id, start_of_month, end_of_month))
    
    records = cursor.fetchall()
    conn.close()

    daily_records = {}
    for r in records:
        daily_records[r['record_date']] = {'status': r['attendance_status']}
    return daily_records

def get_employee_salary_details(employee_id):
    """모든 급여 관련 정보 (연봉, 수당, 공제)를 한 번에 조회하는 헬퍼 함수"""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    salary_info = cursor.execute("SELECT * FROM salary WHERE employee_id = ?", (employee_id,)).fetchone()
    allowances = cursor.execute("SELECT * FROM allowances WHERE employee_id = ? ORDER BY type", (employee_id,)).fetchall()
    deductions = cursor.execute("SELECT * FROM deductions WHERE employee_id = ? ORDER BY type", (employee_id,)).fetchall()
    
    conn.close()
    
    return salary_info, allowances, deductions

def create_attendance_calendar(year, month, calendar_records):
    """캘린더 HTML 생성 함수 (my_attendance에서 사용)"""
    # (캘린더 HTML 생성 로직은 너무 길어 생략하며, 기존 코드를 사용합니다.)
    # 이 함수는 기존 app.py에 정의되어 있다고 가정합니다.
    pass # 실제 구현 시 여기에 캘린더 생성 로직이 있어야 함

# --- 1. 플라스크 앱 설정 ---
app = Flask(__name__)
app.secret_key = 'your_secret_key'
app.config['UPLOAD_FOLDER'] = os.path.join(os.getcwd(), 'static', 'profile_photos') # 정적 파일 경로 사용
app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif'}

# --- 2. 데코레이터 정의 ---
def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or g.user is None:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for('login'))
        return f(*args, **kwargs)
    return decorated_function

def admin_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user_id' not in session or g.user is None or g.user.get('role') != 'admin':
            flash("이 기능은 관리자만 접근 가능합니다.", "error")
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# --- 3. 요청 컨텍스트 관리 ---
@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')

    if user_id is None:
        g.user = None
    else:
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        user_data = conn.execute("""
            SELECT e.*, u.username, u.role
            FROM employees e
            JOIN users u ON e.id = u.employee_id
            WHERE e.id = ?
        """, (user_id,)).fetchone()
        conn.close()
        
        if user_data:
            g.user = dict(user_data)
        else:
            g.user = None
            session.pop('user_id', None)

@app.context_processor
def inject_global_data():
    """템플릿에 g.attendance_button_state를 주입"""
    if g.user:
        return dict(attendance_button_state=get_last_attendance_record(g.user['id']))
    return dict(attendance_button_state='로그인 필요')

# --- 4. 인증 라우트 ---
@app.route('/')
@login_required
def index():
    return redirect(url_for('hr_management')) # 통합 대시보드 역할

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user: return redirect(url_for('index'))
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        conn = sqlite3.connect('employees.db')
        user = conn.execute('SELECT employee_id, password_hash FROM users WHERE username = ?', (username,)).fetchone()
        conn.close()
        if user and check_password_hash(user[1], password):
            session['user_id'] = user[0]
            flash(f"로그인 성공! 환영합니다.", "success")
            return redirect(url_for('index'))
        else:
            flash("사용자 ID 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template('auth/login.html')

@app.route('/logout')
def logout():
    session.pop('user_id', None)
    flash("로그아웃 되었습니다.", "success")
    return redirect(url_for('login'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current_password = request.form['current_password']
        new_password = request.form['new_password']
        confirm_password = request.form['confirm_password']
        employee_id = g.user['id']
        conn = sqlite3.connect('employees.db')
        user_row = conn.execute("SELECT password_hash FROM users WHERE employee_id = ?", (employee_id,)).fetchone()
        if not check_password_hash(user_row[0], current_password):
            flash("현재 비밀번호가 일치하지 않습니다.", "error")
        elif new_password != confirm_password:
            flash("새 비밀번호와 확인 비밀번호가 일치하지 않습니다.", "error")
        else:
            new_hash = generate_password_hash(new_password)
            conn.execute("UPDATE users SET password_hash = ? WHERE employee_id = ?", (new_hash, employee_id))
            conn.commit()
            flash("비밀번호가 성공적으로 변경되었습니다. 다시 로그인해 주세요.", "success")
            session.pop('user_id', None) 
            return redirect(url_for('login'))
        conn.close()
    return render_template('auth/change_password.html')

# ----------------------------------------------------
# 5. 근태 기록 라우트 (Clocking)
# ----------------------------------------------------
@app.route('/clock', methods=['POST'])
@login_required
def clock():
    employee_id = g.user['id']
    action = get_last_attendance_record(employee_id)
    current_time = datetime.now()
    today_date = current_time.strftime('%Y-%m-%d')
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        if action == '출근':
            clock_in_time = current_time.strftime('%Y-%m-%d %H:%M:%S')
            if current_time.time() > time(9, 0, 0):
                status = '지각'
                message = "지각 처리되었습니다."
            else:
                status = '정상'
                message = "출근이 정상적으로 기록되었습니다."
                
            cursor.execute("""
                INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
                VALUES (?, ?, ?, ?)
            """, (current_user_id, today_str, recorded_time_str, status)) 
            
            new_button_state = '퇴근'
        
        # 3. DB 커밋 (중요)
        conn.commit()

        # 4. AJAX 응답 반환
        return jsonify({
            'success': True,
            'message': message, 
            'new_button_state': new_button_state
        })

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'서버 오류 발생: {str(e)}'}), 500
    finally:
        conn.close()

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
@app.route('/my_attendance')
@login_required 
def my_attendance():
    current_user_id = g.user['id']
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 월/년도 및 기간 필터 파라미터 읽기
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    start_date_str = request.args.get('start_date')
    end_date_str = request.args.get('end_date')
    status_filter = request.args.get('status_filter')

    # 2. 파라미터 유효성 검사 및 datetime.date 객체로 변환
    filter_start_date = None
    filter_end_date = None
    
    try:
        if start_date_str:
            filter_start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
        if end_date_str:
            filter_end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        
        # 월/년도 유효성 검사
        start_date = date(year, month, 1)
    except ValueError:
        flash("유효하지 않은 날짜 또는 월 형식입니다. 현재 날짜로 초기화합니다.", "error")
        start_date_str = None
        end_date_str = None
        status_filter = None
        filter_start_date = None
        filter_end_date = None
        year = datetime.now().year
        month = datetime.now().month
        start_date = date(year, month, 1)

    # ----------------------------------------------------
    # 3. 오늘 기록 DB 조회 및 오늘의 요약 준비
    # ----------------------------------------------------
    today_date_obj = datetime.now().date()
    today_db_record = get_today_attendance(current_user_id) # DB/Mock DB에서 오늘 기록 조회
    
    # 오늘의 요약 카드에 표시할 데이터 설정 (DB 기반)
    today_status = today_db_record['attendance_status'] if today_db_record else '미등록'
    
    today_record_display = {
        'clock_in': today_db_record['clock_in_time'] if today_db_record and today_db_record['clock_in_time'] else '-',
        'clock_out': today_db_record['clock_out_time'] if today_db_record and today_db_record['clock_out_time'] else '-',
        'status': today_status,
        'note': '금일' if today_db_record else '-'
    }
    
    # ----------------------------------------------------
    # 4. 전체 기간 동적 데이터 생성 (90일 전체 기간 시뮬레이션)
    # ----------------------------------------------------
    all_records = []
    
    for i in range(90):
        record_date = today_date_obj - timedelta(days=i)
        
        if record_date.weekday() >= 5: continue # 주말 제외
            
        # 임시 데이터 생성 (실제 DB 데이터라고 가정)
        status = '정상'
        clock_in = '08:55'
        clock_out = '18:00'
        note = '-'
        duration = 'N/A'
        
        if i % 4 == 0 and i != 0:
            status = '지각'
            clock_in = '09:10'
        elif i == 10: # 임시 휴가 데이터 추가
             status = '휴가'
             clock_in = '-'
             clock_out = '-'
             note = '휴가'
             duration = '휴가' # ✅ 휴가일 경우 고정 문자열 할당
        if status in ['정상', '지각']:
             # clock_out이 있을 때만 계산합니다 (현재 임시 데이터는 모두 18:00로 가정)
             duration = calculate_work_duration(clock_in, clock_out)
             
        # ----------------------------------------------------
        # 3. 오늘 날짜 기록 (DB 조회 결과 반영)
        # ----------------------------------------------------
        if record_date == today_date_obj:
            record_clock_in = today_db_record['clock_in_time'] or '-' if today_db_record else '-'
            record_clock_out = today_db_record['clock_out_time'] or '-' if today_db_record else '-'
            record_status = today_db_record['attendance_status'] if today_db_record else '미기록'

            # ✅ [핵심 수정] DB 기록 기반으로 duration 계산
            if record_clock_out != '-':
                record_duration = calculate_work_duration(record_clock_in, record_clock_out)
            elif record_clock_in != '-':
                record_duration = '근무중'
            else:
                record_duration = '-'
                
            record = {
                'date_obj': record_date,
                'date': record_date.strftime('%Y-%m-%d'),
                'clock_in': record_clock_in,
                'clock_out': record_clock_out,
                'duration': record_duration, # ✅ 계산된 근무시간 사용
                'status': record_status,
                'note': '금일'
            }
        else:
            # 4. 과거 임시 레코드 추가 (이미 계산된 duration 사용)
            record = {
                'date_obj': record_date, 
                'date': record_date.strftime('%Y-%m-%d'),
                'clock_in': clock_in,
                # 'clock_out'은 휴가 등 상태에 따라 다를 수 있습니다.
                'clock_out': clock_out if status not in ['휴가', '결근'] else '-',
                'duration': duration, # ✅ 계산된/고정된 duration 사용
                'status': status,
                'note': note
            }

        all_records.append(record)
    
    # 5. 기간 및 상태 필터링 실행
    filtered_records = []
    
    for record in all_records:
        date_match = True
        status_match = True

        if filter_start_date and record['date_obj'] < filter_start_date: date_match = False
        if filter_end_date and record['date_obj'] > filter_end_date: date_match = False 
        if status_filter and record['status'] != status_filter: status_match = False
            
        if date_match and status_match:
            filtered_records.append(record)
    
    # 6. 월별 통계 및 달력 생성
    monthly_stats = {
        'work_days': 20,
        'remaining_leave': 12.0,
        'late_count': 3,
        'overtime_hours': '10h 30m'
    }
    
    calendar_records = []
    for record in all_records:
        if record['date_obj'].year == year and record['date_obj'].month == month:
            calendar_records.append({
                'record_date': record['date_obj'],
                'attendance_status': record['status']
            })
            
    calendar_html = create_attendance_calendar(year, month, calendar_records)

    conn.close()
    
    return render_template('my_attendance.html', 
                            today_record=today_record_display,
                            today_status=today_status,
                            attendance_records=filtered_records, 
                            monthly_stats=monthly_stats,
                            current_year=year,
                            current_month=month,
                            current_month_name=start_date.strftime('%Y년 %m월'),
                            calendar_html=calendar_html,
                            start_date_filter=start_date_str,
                            end_date_filter=end_date_str,
                            status_filter_value=status_filter
                            )
def datetimeformat(value, format='%Y년 %m월 %d일 %H:%M'):
    """datetime 객체를 원하는 형식의 문자열로 변환하는 Jinja 필터"""
    if isinstance(value, str):
        # 만약 문자열로 넘어왔다면 datetime 객체로 변환 시도 (SQLite 기본 형식 가정)
        try:
            value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError:
            # 변환 실패 시 현재 시간을 반환하거나 에러 처리
            return value 
    
    if value is None:
        return ""

    # 'now' 문자열이 넘어오면 현재 시간을 사용합니다.
    if value == 'now':
        value = datetime.now()

    return value.strftime(format)

# 필터를 Jinja2 환경에 등록
app.jinja_env.filters['datetimeformat'] = datetimeformat
import calendar
from datetime import datetime, date # 필요한 임포트가 함수 외부에도 선언되어 있다고 가정합니다.

def create_attendance_calendar(year, month, records):
    """주어진 월의 달력을 생성하고 근태 기록을 매핑합니다. (일요일 시작)"""
    
    # { 'YYYY-MM-DD': 'status_color' } 형태로 데이터를 재구성
    attendance_map = {}
    for record in records:
        status = record.get('attendance_status', 'absent')
        record_date = record.get('record_date')
        
        # 임시 데이터 매핑 (CSS 클래스에 사용될 이름)
        color = 'normal'
        if status == '지각':
            color = 'late'
        elif status == '휴가':
            color = 'leave'
        elif status in ['결근', '부재']:
            color = 'absent'
        
        # 'record_date'가 date 객체인지 확인 후 문자열로 변환하여 맵에 저장
        if isinstance(record_date, date):
            date_str = record_date.strftime('%Y-%m-%d')
            attendance_map[date_str] = color
            
    # HTML 달력 생성
    cal = calendar.Calendar()
    # ✅ [핵심 수정 1] 주 시작 요일을 일요일(6)로 설정
    cal.setfirstweekday(calendar.SUNDAY) 
    
    html = f'<table class="calendar-table" data-month="{month}">'
    
    # 요일 헤더
    html += '<thead><tr>'
    # ✅ [핵심 수정 2] 요일 순서를 일월화수목금토로 변경
    for day_name in ['일', '월', '화', '수', '목', '금', '토']:
        # 주말인 일요일/토요일에 별도 클래스 부여 (선택적)
        css_class = 'weekend-header' if day_name in ['일', '토'] else ''
        html += f'<th class="{css_class}">{day_name}</th>'
    html += '</tr></thead><tbody>'
    
    today = date.today()
    
    # 날짜 채우기 (cal.monthdatescalendar는 이제 일요일부터 시작합니다.)
    for week in cal.monthdatescalendar(year, month):
        html += '<tr>'
        for day in week:
            date_str = day.strftime('%Y-%m-%d')
            css_class = ""
            
            # 1. 현재 달이 아님 (음영 처리)
            if day.month != month:
                css_class = "other-month"
            # 2. 미래 날짜 (비활성 처리)
            elif day > today:
                css_class = "future-day"
            # 3. 주말 (토/일) 처리: 일요일=6, 토요일=5
            elif day.weekday() == 5 or day.weekday() == 6: 
                css_class = "weekend"

            # 4. 근태 상태 매핑
            if date_str in attendance_map:
                css_class += f" att-{attendance_map[date_str]}"
                
            # 5. 오늘 날짜 강조
            if day == today and day.month == month:
                 css_class += " today"
                 
            html += f'<td class="{css_class.strip()}">{day.day}</td>'
        html += '</tr>'
        
    html += '</tbody></table>'
    
    return html

# ----------------------------------------------------
# 5. 인사 관리 (HR) 라우트 (기존 기능 병합 및 수정)
# ----------------------------------------------------

@app.route('/hr')
@login_required
def hr_management():
    # 필터링 파라미터 처리
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    dept_query = request.args.get('department', '')
    pos_query = request.args.get('position', '')
    status_query = request.args.get('status', '재직')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 직원 목록 조회
    query_parts = ["e.id != 'admin'"]
    params = []
    
    if id_query: query_parts.append("e.id LIKE ?"); params.append(f'%{id_query}%')
    if name_query: query_parts.append("e.name LIKE ?"); params.append(f'%{name_query}%')
    if dept_query: query_parts.append("e.department = ?"); params.append(dept_query)
    if pos_query: query_parts.append("e.position = ?"); params.append(pos_query)
    if status_query != '전체': query_parts.append("e.status = ?"); params.append(status_query)

    query = "SELECT e.*, u.role FROM employees e JOIN users u ON e.id = u.employee_id WHERE " + " AND ".join(query_parts) + " ORDER BY e.id"
    employees = cursor.execute(query, params).fetchall()
    
    # 2. 부서, 직급, 공지사항 조회
    departments = cursor.execute("SELECT name, code FROM departments ORDER BY name").fetchall()
    positions = cursor.execute("SELECT name FROM positions ORDER BY name").fetchall()
    chart_data = cursor.execute("SELECT department, COUNT(*) as count FROM employees WHERE status = '재직' AND department != '-' GROUP BY department ORDER BY count DESC").fetchall()
    dept_labels = [row['department'] for row in chart_data]
    dept_counts = [row['count'] for row in chart_data]
    notices = cursor.execute("SELECT id, title, content, created_at FROM notices ORDER BY created_at DESC LIMIT 5").fetchall()
    total_employee_count = cursor.execute("SELECT COUNT(id) FROM employees WHERE id != 'admin'").fetchone()[0]
    
    conn.close()
    
    return render_template('hr/hr_management.html', 
                           employees=employees, employee_count=total_employee_count,
                           departments=departments, positions=positions, 
                           dept_labels=dept_labels, dept_counts=dept_counts,
                           notices=notices, request=request)

# (Add, Edit, Detail, Print, Settings 라우트는 기존 코드를 유지하고 경로만 수정합니다.)
@app.route('/hr/add', methods=['GET', 'POST'])
@admin_required
def add_employee():
    # ... (직원 추가 로직) ...
    return render_template('hr/add_employee.html', departments=departments, positions=positions, email_domains=email_domains) # 경로 수정
# ... (생략) ...

# ----------------------------------------------------
# 7. 나의 근태 현황 (My Attendance) 라우트
# ----------------------------------------------------
@app.route('/my_attendance')
@login_required
def my_attendance():
    employee_id = g.user['id']
    
    # 1. 필터링 및 날짜 파라미터 처리
    # ... (생략) ...
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # DB 조회 및 레코드 포맷팅 로직 (가장 최근에 수정된 DB 연동 로직 사용)
    # ... (생략) ...
    
    # 템플릿 렌더링
    return render_template('attendance/my_attendance.html', 
                           # ... (필요한 변수 전달) ...
                           )

# ----------------------------------------------------
# 8. 연차/휴가 신청 및 관리 라우트
# ----------------------------------------------------
@app.route('/vacation_request', methods=['GET', 'POST'])
@login_required
def vacation_request():
    if request.method == 'POST':
        leave_type = request.form['leave_type']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        reason = request.form.get('reason', '') 
        employee_id = g.user['id']
        conn = sqlite3.connect('employees.db')
        try:
            conn.execute("""
                INSERT INTO leave_requests (employee_id, leave_type, start_date, end_date, reason)
                VALUES (?, ?, ?, ?, ?)
            """, (employee_id, leave_type, start_date, end_date, reason))
            conn.commit()
            flash(f"'{leave_type}' 신청이 완료되었습니다. 관리자의 승인을 기다려 주세요.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"신청 중 오류가 발생했습니다: {e}", "error")
        finally:
            conn.close()
        return redirect(url_for('my_attendance'))
    return render_template('attendance/vacation_request.html')

# ----------------------------------------------------
# 9. 월별 급여 명세서 조회 라우트 (Salary Management)
# ----------------------------------------------------
@app.route('/salary')
@login_required
def salary_management():
    employee_id = g.user['id']
    salary_info_row, allowances_rows, deductions_rows = get_employee_salary_details(employee_id)
    
    if not salary_info_row:
        flash("등록된 급여 정보가 없습니다.", "error")
        return redirect(url_for('my_attendance'))
    
    salary_info = dict(salary_info_row)
    allowances = [dict(row) for row in allowances_rows]
    deductions = [dict(row) for row in deductions_rows]
    
    # 급여 계산 로직 (수당/공제 비율 계산 포함)
    monthly_base = salary_info['monthly_base']
    total_allowance = sum(a['amount'] for a in allowances if a['is_monthly'] == 1)
    total_deduction = 0
    deduction_details = []
    
    for d in deductions:
        deduction_amount = 0
        if d['is_rate'] == 1:
            rate = d['amount'] / 10000.0
            deduction_amount = int(monthly_base * rate)
        else:
            deduction_amount = d['amount']
            
        total_deduction += deduction_amount
        deduction_details.append(dict(d, amount=deduction_amount)) # 계산된 금액으로 업데이트
        
    gross_pay = monthly_base + total_allowance
    net_pay = gross_pay - total_deduction

    calculations = {
        'base': monthly_base,
        'total_allowance': total_allowance,
        'gross_pay': gross_pay,
        'total_deduction': total_deduction,
        'net_pay': net_pay,
        'allowances_list': [dict(a) for a in allowances if a['is_monthly'] == 1],
        'deductions_list': deduction_details,
    }
    
    return render_template('salary/salary_detail.html', 
                           salary_info=salary_info, calculations=calculations, employee=g.user,
                           current_month=datetime.now().strftime('%Y년 %m월'))

# ----------------------------------------------------
# 10. 관리자 급여 관리 (Salary Admin) 라우트 (신규 추가)
# ----------------------------------------------------
@app.route('/salary/admin/<employee_id>', methods=['GET', 'POST'])
@admin_required
def salary_admin(employee_id):
    # GET 요청 시: 폼 렌더링
    if request.method == 'GET':
        salary_info, allowances, deductions = get_employee_salary_details(employee_id)
        
        conn = sqlite3.connect('employees.db')
        employee_name = conn.execute("SELECT name FROM employees WHERE id = ?", (employee_id,)).fetchone()
        conn.close()

        if not employee_name:
            flash("해당 직원을 찾을 수 없습니다.", "error")
            return redirect(url_for('hr_management'))
            
        return render_template('salary/salary_admin.html', 
                               employee_id=employee_id,
                               employee_name=employee_name[0],
                               salary_info=dict(salary_info) if salary_info else None,
                               allowances=[dict(a) for a in allowances],
                               deductions=[dict(d) for d in deductions])
                               
    # POST 요청 시: DB 업데이트
    if request.method == 'POST':
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        employee_name = cursor.execute("SELECT name FROM employees WHERE id = ?", (employee_id,)).fetchone()
        
        try:
            # --- 1. 기본 급여 (salary) 수정 ---
            annual_salary = int(request.form['annual_salary'].replace(',', ''))
            monthly_base = int(request.form['monthly_base'].replace(',', ''))
            start_date = request.form['start_date']
            
            cursor.execute("UPDATE salary SET annual_salary = ?, monthly_base = ?, start_date = ? WHERE employee_id = ?", 
                           (annual_salary, monthly_base, start_date, employee_id))
            
            # --- 2. 수당 (allowances) 수정/삭제 ---
            cursor.execute("DELETE FROM allowances WHERE employee_id = ?", (employee_id,))
            allowance_types = request.form.getlist('allowance_type[]')
            allowance_amounts = request.form.getlist('allowance_amount[]')
            
            for type, amount in zip(allowance_types, allowance_amounts):
                if type and amount.replace(',', '').isdigit():
                    amount_val = int(amount.replace(',', ''))
                    # 이 로직은 템플릿의 체크박스 순서와 일치한다고 가정합니다. (단순화)
                    cursor.execute("INSERT INTO allowances (employee_id, type, amount, is_monthly) VALUES (?, ?, ?, ?)", 
                                   (employee_id, type, amount_val, 1)) 

            # --- 3. 공제 (deductions) 수정/삭제 ---
            cursor.execute("DELETE FROM deductions WHERE employee_id = ?", (employee_id,))
            deduction_types = request.form.getlist('deduction_type[]')
            deduction_amounts = request.form.getlist('deduction_amount[]')
            deduction_rates = request.form.getlist('deduction_is_rate[]')

            for index, (type, amount) in enumerate(zip(deduction_types, deduction_amounts)):
                if type and amount.isdigit():
                    amount_val = int(amount)
                    is_rate_val = 1 if index < len(deduction_rates) and deduction_rates[index] == 'on' else 0
                    cursor.execute("INSERT INTO deductions (employee_id, type, amount, is_rate) VALUES (?, ?, ?, ?)", 
                                   (employee_id, type, amount_val, is_rate_val))
            
            conn.commit()
            flash(f"{employee_name[0]} 직원의 급여 정보가 성공적으로 업데이트되었습니다.", "success")
            
        except Exception as e:
            conn.rollback()
            flash(f"급여 정보 업데이트 중 오류 발생: {e}", "error")
        finally:
            conn.close()
            
        return redirect(url_for('salary_admin', employee_id=employee_id))

# ----------------------------------------------------
# 8. 연차/휴가 신청 라우트 (신규 추가)
# ----------------------------------------------------
@app.route('/vacation_request', methods=['GET', 'POST'])
@login_required
def vacation_request():
    
    if request.method == 'POST':
        leave_type = request.form['leave_type']
        start_date = request.form['start_date']
        end_date = request.form['end_date']
        reason = request.form.get('reason', '') 
        
        flash(f"'{leave_type}' 신청이 완료되었습니다. (기간: {start_date} ~ {end_date})", "success")
        return redirect(url_for('my_attendance')) # 신청 후 나의 근태 현황 페이지로 이동

    # GET 요청: vacation_request.html 폼 페이지 렌더링
    return render_template('vacation_request.html')
# ----------------------------------------------------
# 12. 공지사항 라우트
# ----------------------------------------------------
# ... (add_notice_page, delete_notice, view_notice 라우트 생략) ...


if __name__ == '__main__':
    app.run(debug=True)