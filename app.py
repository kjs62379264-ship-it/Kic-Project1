from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, jsonify
import sqlite3
from datetime import datetime, time, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
import os
from werkzeug.utils import secure_filename
import calendar
from dateutil.relativedelta import relativedelta
import math

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# 업로드 폴더 설정
UPLOAD_FOLDER = os.path.join(app.static_folder, 'profile_photos')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------------------------------
# 0. 헬퍼 함수 및 필터 (계산 및 포맷팅)
# ----------------------------------------------------

def get_most_recent_weekday(date_obj):
    """주말(토/일)인 경우, 가장 최근의 금요일 날짜를 반환합니다."""
    weekday = date_obj.weekday()
    if weekday == 5: return date_obj - timedelta(days=1)
    elif weekday == 6: return date_obj - timedelta(days=2)
    else: return date_obj

def get_today_attendance(employee_id):
    """오늘의 근태 기록 조회"""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    today = datetime.now().date()
    
    cursor.execute("""
        SELECT id, clock_in_time, clock_out_time, attendance_status, record_date FROM attendance 
        WHERE employee_id = ? AND record_date = ?
        ORDER BY id DESC LIMIT 1
    """, (employee_id, today))
    today_record = cursor.fetchone()
    conn.close()
    
    if today_record:
        record_dict = dict(today_record)
        if record_dict['clock_in_time']: record_dict['clock_in_time'] = record_dict['clock_in_time'][:5] 
        if record_dict['clock_out_time']: record_dict['clock_out_time'] = record_dict['clock_out_time'][:5]
        return record_dict
    return None

def calculate_work_duration(clock_in_str, clock_out_str, lunch_minutes=60):
    """근무 시간 계산 (4시간 이상 시 휴게시간 차감)"""
    if not clock_in_str or not clock_out_str or clock_in_str == '-' or clock_out_str == '-':
        return 'N/A'
    try:
        in_time = datetime.strptime(clock_in_str, '%H:%M:%S')
        out_time = datetime.strptime(clock_out_str, '%H:%M:%S')
    except ValueError:
        try:
            in_time = datetime.strptime(clock_in_str, '%H:%M')
            out_time = datetime.strptime(clock_out_str, '%H:%M')
        except ValueError:
            return '오류'

    if out_time < in_time:
        duration = (out_time + timedelta(days=1)) - in_time
    else:
        duration = out_time - in_time

    duration_seconds = duration.total_seconds()
    LUNCH_THRESHOLD_SECONDS = 4 * 3600 
    lunch_seconds = lunch_minutes * 60

    if duration_seconds >= LUNCH_THRESHOLD_SECONDS:
        working_seconds = duration_seconds - lunch_seconds
    else:
        working_seconds = duration_seconds
        
    if working_seconds < 0: working_seconds = 0
    return f"{int(working_seconds // 3600)}h {int((working_seconds % 3600) // 60)}m"

def create_attendance_calendar(year, month, records):
    """달력 HTML 생성 함수"""
    attendance_map = {}
    for record in records:
        status = record.get('attendance_status', 'absent')
        record_date = record.get('record_date')
        
        color = 'normal'
        if status == '지각': color = 'late'
        elif status == '휴가': color = 'leave'
        elif status in ['결근', '부재']: color = 'absent'
        
        if isinstance(record_date, date):
            date_str = record_date.strftime('%Y-%m-%d')
            attendance_map[date_str] = color
            
    cal = calendar.Calendar()
    cal.setfirstweekday(calendar.SUNDAY) 
    html = f'<table class="calendar-table" data-month="{month}"><thead><tr>'
    for day_name in ['일', '월', '화', '수', '목', '금', '토']:
        html += f'<th>{day_name}</th>'
    html += '</tr></thead><tbody>'
    today = date.today()
    
    for week in cal.monthdatescalendar(year, month):
        html += '<tr>'
        for day in week:
            date_str = day.strftime('%Y-%m-%d')
            css_class = ""
            if day.month != month: css_class = "other-month"
            elif day > today: css_class = "future-day"
            elif day.weekday() >= 5: css_class = "weekend"
            if date_str in attendance_map: css_class += f" att-{attendance_map[date_str]}"
            if day == today and day.month == month: css_class += " today"
            html += f'<td class="{css_class.strip()}">{day.day}</td>'
        html += '</tr>'
    html += '</tbody></table>'
    return html

# ✨ [신규] 금액 쉼표 포맷 필터
@app.template_filter('comma')
def comma_filter(value):
    try:
        return "{:,}".format(int(value))
    except (ValueError, TypeError):
        return value

@app.template_filter('datetimeformat')
def datetimeformat(value, format='%Y년 %m월 %d일 %H:%M'):
    if isinstance(value, str):
        try: value = datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
        except ValueError: return value 
    if value is None: return ""
    if value == 'now': value = datetime.now()
    return value.strftime(format)

# ✨ [신규] 4대보험 및 소득세 계산 함수 (핵심 로직)
def calculate_deductions_logic(monthly_salary, non_taxable_amount=200000):
    taxable_income = monthly_salary - non_taxable_amount
    if taxable_income < 0: taxable_income = 0

    pension_base = min(max(monthly_salary, 370000), 5900000)
    national_pension = int(pension_base * 0.045)
    national_pension = (national_pension // 10) * 10 

    health_insurance = int(monthly_salary * 0.03545)
    health_insurance = (health_insurance // 10) * 10

    care_insurance = int(health_insurance * 0.1295)
    care_insurance = (care_insurance // 10) * 10

    employment_insurance = int(monthly_salary * 0.009)
    employment_insurance = (employment_insurance // 10) * 10

    annual_income = taxable_income * 12
    if annual_income <= 5000000: deduction = annual_income * 0.7
    elif annual_income <= 15000000: deduction = 3500000 + (annual_income - 5000000) * 0.4
    elif annual_income <= 45000000: deduction = 7500000 + (annual_income - 15000000) * 0.15
    elif annual_income <= 100000000: deduction = 12000000 + (annual_income - 45000000) * 0.05
    else: deduction = 14750000 + (annual_income - 100000000) * 0.02
    
    tax_base = annual_income - deduction - 1500000 
    if tax_base < 0: tax_base = 0

    if tax_base <= 14000000: calculated_tax = tax_base * 0.06
    elif tax_base <= 50000000: calculated_tax = 840000 + (tax_base - 14000000) * 0.15
    elif tax_base <= 88000000: calculated_tax = 6240000 + (tax_base - 50000000) * 0.24
    else: calculated_tax = 15360000 + (tax_base - 88000000) * 0.35

    income_tax = int(calculated_tax / 12) 
    income_tax = (income_tax // 10) * 10

    local_tax = int(income_tax * 0.1)
    local_tax = (local_tax // 10) * 10

    total_deduction = national_pension + health_insurance + care_insurance + employment_insurance + income_tax + local_tax

    return {
        'national_pension': national_pension,
        'health_insurance': health_insurance,
        'care_insurance': care_insurance,
        'employment_insurance': employment_insurance,
        'income_tax': income_tax,
        'local_tax': local_tax,
        'total_deduction': total_deduction
    }

# ----------------------------------------------------
# 1. 인증 및 미들웨어
# ----------------------------------------------------

@app.before_request
def load_logged_in_user():
    user_id = session.get('user_id')
    g.user = None
    if user_id is not None:
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        cursor.execute("""
            SELECT e.*, u.role, u.password_hash 
            FROM employees e 
            JOIN users u ON e.id = u.employee_id 
            WHERE e.id = ?
        """, (user_id,))
        row = cursor.fetchone()
        if row: g.user = dict(row)
        conn.close()

def login_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            flash("로그인이 필요합니다.", "error")
            return redirect(url_for('login'))
        return view(**kwargs)
    return wrapped_view

def admin_required(view):
    @wraps(view)
    def wrapped_view(**kwargs):
        if g.user is None:
            return redirect(url_for('login'))
        if g.user['role'] != 'admin':
            flash("관리자 권한이 필요합니다.", "error")
            return redirect(url_for('hr_management')) 
        return view(**kwargs)
    return wrapped_view

# ----------------------------------------------------
# 2. 기본 라우트 (로그인, 로그아웃, 메인)
# ----------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if g.user: return redirect(url_for('hr_management'))
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
            flash(f"환영합니다, {user_record['username']}님!", "success")
            return redirect(url_for('hr_management'))
        else:
            flash("ID 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))

@app.route('/')
@login_required
def root():
    return redirect(url_for('hr_management'))

@app.route('/change_password', methods=['GET', 'POST'])
@login_required
def change_password():
    if request.method == 'POST':
        current = request.form['current_password']
        new = request.form['new_password']
        confirm = request.form['confirm_password']
        
        if not check_password_hash(g.user['password_hash'], current):
            flash("현재 비밀번호가 일치하지 않습니다.", "error")
            return redirect(url_for('change_password'))
        if new != confirm:
            flash("새 비밀번호가 일치하지 않습니다.", "error")
            return redirect(url_for('change_password'))
            
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        cursor.execute("UPDATE users SET password_hash = ? WHERE employee_id = ?", 
                       (generate_password_hash(new), g.user['id']))
        conn.commit()
        conn.close()
        flash("비밀번호가 변경되었습니다.", "success")
        return redirect(url_for('hr_management'))
    return render_template('change_password.html')

# ----------------------------------------------------
# 3. 근태 관리 라우트
# ----------------------------------------------------

@app.context_processor
def inject_attendance_status():
    if not g.user: return dict(attendance_button_state=None)
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT clock_out_time FROM attendance WHERE employee_id = ? AND record_date = ? ORDER BY id DESC LIMIT 1", (g.user['id'], today))
    last_record = cursor.fetchone()
    conn.close()
    btn_state = '출근'
    if last_record and last_record['clock_out_time'] is None: btn_state = '퇴근'
    return dict(attendance_button_state=btn_state)

@app.route('/attendance/clock', methods=['POST'])
@login_required
def clock():
    emp_id = g.user['id']
    now = datetime.now()
    today_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT id, clock_in_time, clock_out_time FROM attendance WHERE employee_id = ? AND record_date = ? ORDER BY id DESC LIMIT 1", (emp_id, today_str))
    last = cursor.fetchone()
    
    msg = ""
    new_state = ""
    
    try:
        if last and last['clock_in_time'] and last['clock_out_time'] is None:
            # 퇴근 처리
            cursor.execute("UPDATE attendance SET clock_out_time = ? WHERE id = ?", (time_str, last['id']))
            msg = f"{now.strftime('%H:%M')} 퇴근 처리되었습니다."
            new_state = '출근'
        else:
            # 출근 처리
            status = '지각' if now.time() > time(9, 0, 0) else '정상'
            rec_time = time_str if status == '지각' else "09:00:00"
            cursor.execute("INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status) VALUES (?, ?, ?, ?)", 
                           (emp_id, today_str, rec_time, status))
            msg = f"{now.strftime('%H:%M')} 출근 처리되었습니다. ({status})"
            new_state = '퇴근'
        conn.commit()
        return jsonify({'success': True, 'message': msg, 'new_button_state': new_state})
    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': str(e)})
    finally:
        conn.close()

@app.route('/attendance')
@login_required
def attendance():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 필터링
    id_q = request.args.get('id', '')
    name_q = request.args.get('name', '')
    
    sql = """
        SELECT e.id, e.name, e.department, e.position, 
               a.clock_in_time, a.clock_out_time, 
               COALESCE(a.attendance_status, '부재') as status
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.record_date = ?
        WHERE e.status = '재직' AND e.id != 'admin'
    """
    params = [datetime.now().strftime('%Y-%m-%d')]
    
    if id_q: sql += " AND e.id LIKE ?"; params.append(f"%{id_q}%")
    if name_q: sql += " AND e.name LIKE ?"; params.append(f"%{name_q}%")
    
    cursor.execute(sql, params)
    employees = [dict(row) for row in cursor.fetchall()]
    
    # 2. 통계
    counts = {'재실': 0, '휴가': 0, '외근/출장': 0, '부재': 0}
    for emp in employees:
        s = emp['status']
        if emp['clock_in_time'] and not emp['clock_out_time']: s = '재실'; emp['status'] = '재실'
        elif s == '정상' or s == '지각': s = '재실' # 퇴근했거나 근무중
        
        if s in counts: counts[s] += 1
        else: counts['부재'] += 1
        
        if emp['clock_in_time']: emp['check_in'] = emp['clock_in_time'][:5]
        if emp['clock_out_time']: emp['check_out'] = emp['clock_out_time'][:5]

    # 3. 휴가 요청 (실제 DB)
    cursor.execute("SELECT * FROM vacation_requests WHERE status IN ('대기','승인') ORDER BY request_date DESC")
    reqs = cursor.fetchall()
    
    conn.close()
    return render_template('attendance_page.html', employees=employees, status_counts=counts, 
                           vacation_requests=reqs, total_employees_count=len(employees),
                           departments=[], positions=[])

# ----------------------------------------------------
# [복구] 개별 직원 근태 상세 조회 (최근 5일)
# ----------------------------------------------------
@app.route('/attendance/detail/<employee_id>')
@login_required
def attendance_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 직원 정보 조회
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    
    if not employee:
        flash(f"직원 ID {employee_id}를 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('attendance'))
    
    # 2. 최근 5일 근태 기록 조회
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? 
        ORDER BY record_date DESC LIMIT 5
    """, (employee_id,))
    records_rows = cursor.fetchall()
    
    records = []
    for row in records_rows:
        r = dict(row)
        r['date'] = r['record_date']
        r['clock_in'] = r['clock_in_time'][:5] if r['clock_in_time'] else '-'
        r['clock_out'] = r['clock_out_time'][:5] if r['clock_out_time'] else '-'
        r['status'] = r['attendance_status']
        records.append(r)

    # 3. 오늘 상태 조회
    today = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("SELECT attendance_status FROM attendance WHERE employee_id=? AND record_date=?", (employee_id, today))
    today_row = cursor.fetchone()
    today_status = today_row['attendance_status'] if today_row else '미등록'

    conn.close()
    
    return render_template('attendance_detail.html', 
                           employee=employee,
                           records=records,
                           today_status=today_status)

@app.route('/my_attendance')
@login_required
def my_attendance():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    start_date = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end_date = f"{year}-{month:02d}-{last_day}"
    
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? AND record_date BETWEEN ? AND ?
        ORDER BY record_date DESC
    """, (g.user['id'], start_date, end_date))
    
    rows = cursor.fetchall()
    records = []
    calendar_data = []
    
    late_count = 0
    
    for row in rows:
        d = dict(row)
        d['date'] = d['record_date']
        d['clock_in'] = d['clock_in_time'][:5] if d['clock_in_time'] else '-'
        d['clock_out'] = d['clock_out_time'][:5] if d['clock_out_time'] else '-'
        d['duration'] = calculate_work_duration(d['clock_in_time'], d['clock_out_time'])
        d['status'] = d['attendance_status']
        records.append(d)
        
        calendar_data.append({'record_date': datetime.strptime(d['record_date'], '%Y-%m-%d').date(), 'attendance_status': d['status']})
        if d['status'] == '지각': late_count += 1

    cal_html = create_attendance_calendar(year, month, calendar_data)
    conn.close()
    
    return render_template('my_attendance.html', attendance_records=records, calendar_html=cal_html,
                           current_year=year, current_month=month, current_month_name=f"{year}년 {month}월",
                           monthly_stats={'late_count': late_count, 'remaining_leave': 15}) # 연차는 임시

@app.route('/vacation_request', methods=['GET', 'POST'])
@login_required
def vacation_request():
    if request.method == 'POST':
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        try:
            form_type = request.form.get('form_type')
            common_data = (g.user['id'], g.user['name'], g.user['department'], datetime.now(), '대기')
            
            if form_type == 'vacation':
                cursor.execute("""
                    INSERT INTO vacation_requests (user_id, name, department, request_date, status, 
                    request_type, start_date, end_date, reason) VALUES (?,?,?,?,?, ?,?,?,?)
                """, common_data + (request.form['leave_type'], request.form['start_date'], request.form['end_date'], request.form['reason']))
            elif form_type == 'work':
                dest = request.form.get('destination', '')
                reason = request.form.get('work_reason', '')
                end = request.form.get('work_end_date') or request.form['work_start_date']
                cursor.execute("""
                    INSERT INTO vacation_requests (user_id, name, department, request_date, status, 
                    request_type, start_date, end_date, reason) VALUES (?,?,?,?,?, ?,?,?,?)
                """, common_data + (request.form['work_type'], request.form['work_start_date'], end, f"{dest} / {reason}"))
                
            conn.commit()
            flash("신청이 완료되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"오류: {e}", "error")
        finally:
            conn.close()
        return redirect(url_for('my_attendance'))
    return render_template('vacation_request.html', today_display_date=datetime.now().strftime('%Y년 %m월 %d일'))

# ----------------------------------------------------
# [추가] 휴가/근무 요청 상태 변경 (승인/반려)
# ----------------------------------------------------
@app.route('/request/update/<int:req_id>/<action>', methods=['POST'])
@admin_required
def update_request_status(req_id, action):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    new_status = '대기'
    if action == 'approve':
        new_status = '승인'
    elif action == 'reject':
        new_status = '반려'
        
    try:
        cursor.execute("UPDATE vacation_requests SET status = ? WHERE id = ?", (new_status, req_id))
        
        # (선택 사항) 만약 '승인'이고 날짜가 오늘이라면, attendance 테이블에도 '휴가' 등으로 기록을 남길 수 있습니다.
        # 현재는 요청 상태만 변경합니다.
        
        conn.commit()
        flash(f"요청이 '{new_status}' 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('attendance')) # 관리자 대시보드로 이동

@app.route('/attendance_employee')
@admin_required
def attendance_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT e.id, e.name, e.department, e.position,
               COUNT(CASE WHEN a.attendance_status = '지각' THEN 1 END) as late_count,
               COUNT(CASE WHEN a.attendance_status = '결근' THEN 1 END) as absence_count
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id 
             AND strftime('%Y-%m', a.record_date) = ?
        WHERE e.status = '재직' AND e.id != 'admin'
        GROUP BY e.id
    """, (datetime.now().strftime('%Y-%m'),))
    
    stats = [dict(row) for row in cur.fetchall()]
    for s in stats: 
        s['remaining_leave'] = 15
        s['overtime_hours'] = 0
        
    conn.close()
    return render_template('attendance_employee.html', employee_stats=stats, current_month=datetime.now().month)

@app.route('/attendance_employee_detail/<employee_id>')
@login_required
@admin_required 
def attendance_employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    target_user = cursor.execute("SELECT id, name, department FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not target_user:
        flash("해당 직원을 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('attendance_employee'))

    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    start_date = date(year, month, 1)

    # 통계 요약 (임시)
    employee_stats_summary = {
        'target_month': datetime.now().strftime('%Y년 %m월'),
        'target_year': datetime.now().year,
        'monthly': {'tardy_count': 0, 'absent_count': 0, 'offsite_days': 0, 'business_trip_days': 0, 'leave_days': 0, 'overtime_hours': '0h 0m', 'overtime_days_count': 0},
        'yearly': {'tardy_count': 0, 'absent_count': 0, 'offsite_days': 0, 'business_trip_days': 0, 'leave_days': 0, 'overtime_hours': '0h 0m', 'overtime_days_count': 0}
    }
    
    calendar_records = []
    calendar_html = create_attendance_calendar(year, month, calendar_records)
    
    conn.close()

    return render_template('attendance_employee_detail.html', target_user=target_user, employee_stats_summary=employee_stats_summary, calendar_html=calendar_html, current_year=year, current_month=month, current_month_name=start_date.strftime('%Y년 %m월'))


# ----------------------------------------------------
# 4. 인사 관리 (HR) 라우트
# ----------------------------------------------------

@app.route('/hr')
@login_required
def hr_management():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 검색 조건 처리
    sql = "SELECT * FROM employees WHERE id != 'admin'"
    params = []
    
    id_q = request.args.get('id', '')
    name_q = request.args.get('name', '')
    dept_q = request.args.get('department', '')
    pos_q = request.args.get('position', '')
    status_q = request.args.get('status', '재직')

    if id_q: sql += " AND id LIKE ?"; params.append(f"%{id_q}%")
    if name_q: sql += " AND name LIKE ?"; params.append(f"%{name_q}%")
    if dept_q: sql += " AND department = ?"; params.append(dept_q)
    if pos_q: sql += " AND position = ?"; params.append(pos_q)
    if status_q and status_q != '전체': sql += " AND status = ?"; params.append(status_q)
        
    sql += " ORDER BY id DESC"
        
    cur.execute(sql, params)
    employees = cur.fetchall()
    
    cur.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5")
    notices = cur.fetchall()
    
    cur.execute("SELECT department, COUNT(*) as c FROM employees WHERE status='재직' AND id!='admin' GROUP BY department")
    dept_stats = cur.fetchall()
    
    cur.execute("SELECT name FROM departments")
    depts = cur.fetchall()
    cur.execute("SELECT name FROM positions")
    pos = cur.fetchall()
    
    conn.close()
    return render_template('hr_management.html', employees=employees, notices=notices, 
                           dept_labels=[r[0] for r in dept_stats], dept_counts=[r[1] for r in dept_stats],
                           departments=depts, positions=pos, employee_count=len(employees))

@app.route('/hr/add', methods=['GET', 'POST'])
@admin_required
def add_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            dept = request.form['department']
            cur.execute("SELECT code FROM departments WHERE name=?", (dept,))
            code = cur.fetchone()[0]
            prefix = f"{request.form['hire_date'][2:4]}{code}"
            cur.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (f"{prefix}%",))
            last = cur.fetchone()
            seq = int(last[0][-4:]) + 1 if last else 1
            new_id = f"{prefix}{seq:04d}"
            
            cur.execute("""
                INSERT INTO employees (id, name, department, position, hire_date, phone_number, email, address, gender, status)
                VALUES (?,?,?,?,?,?,?,?,?, '재직')
            """, (new_id, request.form['name'], dept, request.form['position'], request.form['hire_date'],
                  f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}",
                  f"{request.form['email_id']}@{request.form['email_domain']}",
                  request.form['address'], request.form['gender']))
            
            cur.execute("INSERT INTO users (employee_id, username, password_hash, role) VALUES (?,?,?,?)",
                        (new_id, new_id, generate_password_hash(request.form['password']), request.form.get('role', 'user')))
            
            conn.commit()
            flash(f"직원 {request.form['name']}({new_id}) 등록 완료", "success")
            return redirect(url_for('hr_management'))
        except Exception as e:
            conn.rollback()
            flash(f"등록 실패: {e}", "error")
            
    cur.execute("SELECT name FROM departments")
    d = cur.fetchall()
    cur.execute("SELECT name FROM positions")
    p = cur.fetchall()
    cur.execute("SELECT domain FROM email_domains")
    e = cur.fetchall()
    conn.close()
    return render_template('add_employee.html', departments=d, positions=p, email_domains=e)

# ✨ [수정] 라우트 변수명 통일 (id -> employee_id)
@app.route('/hr/employee/<employee_id>')
@login_required
def employee_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM employees WHERE id=?", (employee_id,))
    emp = cur.fetchone()
    conn.close()
    return render_template('employee_detail.html', employee=emp)

# ✨ [수정] 라우트 변수명 통일 (id -> employee_id)
@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
@login_required
def edit_employee(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    if request.method == 'POST':
        img = request.form.get('current_image') 
        if 'profile_image' in request.files:
            f = request.files['profile_image']
            if f.filename:
                fname = secure_filename(f.filename)
                f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                img = fname
        
        cur.execute("""
            UPDATE employees SET name=?, department=?, position=?, phone_number=?, email=?, address=?, profile_image=?
            WHERE id=?
        """, (request.form['name'], request.form['department'], request.form['position'],
              f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}",
              f"{request.form['email_id']}@{request.form['email_domain']}",
              request.form['address'], img, employee_id))
        conn.commit()
        # ✨ [수정] 리다이렉트 시 employee_id 사용
        return redirect(url_for('employee_detail', employee_id=employee_id))

    cur.execute("SELECT * FROM employees WHERE id=?", (employee_id,))
    emp = cur.fetchone()
    cur.execute("SELECT name FROM departments")
    depts = cur.fetchall()
    cur.execute("SELECT name FROM positions")
    pos = cur.fetchall()
    cur.execute("SELECT domain FROM email_domains")
    doms = cur.fetchall()
    conn.close()
    
    phone = emp['phone_number'].split('-') if emp['phone_number'] else ['','','']
    email = emp['email'].split('@') if emp['email'] else ['','']
    return render_template('edit_employee.html', employee=dict(emp), departments=depts, positions=pos, email_domains=doms,
                           phone_parts=phone, email_parts=email)

# ----------------------------------------------------
# [복구된 기능] 명부 인쇄 및 퇴사/재입사 처리
# ----------------------------------------------------

@app.route('/hr/print')
@admin_required
def print_employees():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    id_query = request.args.get('id', '')
    name_query = request.args.get('name', '')
    department_query = request.args.get('department', '')
    position_query = request.args.get('position', '')
    status_query = request.args.get('status', '재직')

    sql = "SELECT * FROM employees WHERE id != 'admin'"
    params = []

    if id_query: sql += " AND id LIKE ?"; params.append(f"%{id_query}%")
    if name_query: sql += " AND name LIKE ?"; params.append(f"%{name_query}%")
    if department_query: sql += " AND department = ?"; params.append(department_query)
    if position_query: sql += " AND position = ?"; params.append(position_query)
    if status_query and status_query != '전체': sql += " AND status = ?"; params.append(status_query)
        
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
        flash(f"오류 발생: {e}", "error")
    finally:
        conn.close()
    # ✨ [수정] 리다이렉트 시 employee_id 사용
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
    # ✨ [수정] 리다이렉트 시 employee_id 사용
    return redirect(url_for('employee_detail', employee_id=employee_id))

# ----------------------------------------------------
# 5. ✨ [신규] 급여 관리 (Payroll) 섹션
# ----------------------------------------------------

@app.route('/salary/payroll', methods=['GET'])
@admin_required
def salary_payroll():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    year = datetime.now().year
    month = datetime.now().month
    
    cur.execute("""
        SELECT p.*, e.name, e.department, e.position 
        FROM salary_payments p
        JOIN employees e ON p.employee_id = e.id
        WHERE p.payment_year = ? AND p.payment_month = ?
    """, (year, month))
    existing_payroll = cur.fetchall()
    is_calculated = len(existing_payroll) > 0
    conn.close()
    
    return render_template('salary_list.html', year=year, month=month, payrolls=existing_payroll, is_calculated=is_calculated)

# ----------------------------------------------------
# [추가] 급여 계약 정보 관리 (연봉/계좌 수정)
# ----------------------------------------------------
@app.route('/salary/contracts', methods=['GET', 'POST'])
@admin_required
def salary_contracts():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        # 수정 폼 제출 처리
        emp_id = request.form['employee_id']
        annual_salary = int(request.form['annual_salary'].replace(',', '')) # 쉼표 제거
        bank_name = request.form['bank_name']
        account_number = request.form['account_number']
        
        # 기본급 자동 계산 (연봉 / 12)
        base_salary = annual_salary // 12
        
        try:
            # 기존 계약이 있는지 확인
            cursor.execute("SELECT id FROM salary_contracts WHERE employee_id=?", (emp_id,))
            exists = cursor.fetchone()
            
            if exists:
                cursor.execute("""
                    UPDATE salary_contracts 
                    SET annual_salary=?, base_salary=?, bank_name=?, account_number=?
                    WHERE employee_id=?
                """, (annual_salary, base_salary, bank_name, account_number, emp_id))
            else:
                cursor.execute("""
                    INSERT INTO salary_contracts (employee_id, annual_salary, base_salary, bank_name, account_number)
                    VALUES (?, ?, ?, ?, ?)
                """, (emp_id, annual_salary, base_salary, bank_name, account_number))
                
            conn.commit()
            flash(f"{emp_id} 사원의 급여 계약 정보가 저장되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"저장 중 오류 발생: {e}", "error")
            
        return redirect(url_for('salary_contracts'))

    # 조회 로직
    # 직원 정보와 급여 계약 정보를 LEFT JOIN하여 가져옴 (계약 정보가 없는 직원도 표시)
    cursor.execute("""
        SELECT e.id, e.name, e.department, e.position, 
               s.annual_salary, s.base_salary, s.bank_name, s.account_number
        FROM employees e
        LEFT JOIN salary_contracts s ON e.id = s.employee_id
        WHERE e.status = '재직' AND e.id != 'admin'
        ORDER BY e.id DESC
    """)
    contracts = cursor.fetchall()
    conn.close()
    
    return render_template('salary_contracts.html', contracts=contracts)

@app.route('/salary/calculate_all', methods=['POST'])
@admin_required
def calculate_all_salary():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    year = datetime.now().year
    month = datetime.now().month
    payment_date = f"{year}-{month:02d}-25" 
    
    try:
        cur.execute("DELETE FROM salary_payments WHERE payment_year=? AND payment_month=?", (year, month))
        cur.execute("""
            SELECT e.id, s.base_salary 
            FROM employees e
            JOIN salary_contracts s ON e.id = s.employee_id
            WHERE e.status = '재직'
        """)
        employees = cur.fetchall()
        
        count = 0
        for emp in employees:
            emp_id = emp['id']
            base_salary = emp['base_salary']
            cur.execute("SELECT SUM(amount) FROM fixed_allowances WHERE employee_id=?", (emp_id,))
            allowance_sum = cur.fetchone()[0] or 0
            cur.execute("SELECT SUM(amount) FROM fixed_allowances WHERE employee_id=? AND is_taxable=0", (emp_id,))
            non_taxable = cur.fetchone()[0] or 0
            
            total_monthly_income = base_salary + allowance_sum
            deductions = calculate_deductions_logic(total_monthly_income, non_taxable)
            net_salary = total_monthly_income - deductions['total_deduction']
            
            cur.execute("""
                INSERT INTO salary_payments (
                    employee_id, payment_year, payment_month, payment_date,
                    total_base, total_allowance, total_deduction, net_salary,
                    national_pension, health_insurance, care_insurance, employment_insurance,
                    income_tax, local_tax
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                emp_id, year, month, payment_date,
                base_salary, allowance_sum, deductions['total_deduction'], net_salary,
                deductions['national_pension'], deductions['health_insurance'], 
                deductions['care_insurance'], deductions['employment_insurance'],
                deductions['income_tax'], deductions['local_tax']
            ))
            count += 1
            
        conn.commit()
        flash(f"총 {count}명의 급여 정산이 완료되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"급여 계산 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('salary_payroll'))

@app.route('/my_salary')
@login_required
def my_salary():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("SELECT * FROM salary_payments WHERE employee_id = ? ORDER BY payment_year DESC, payment_month DESC LIMIT 1", (g.user['id'],))
    last_pay = cur.fetchone()
    cur.execute("SELECT * FROM salary_payments WHERE employee_id = ? ORDER BY payment_year DESC, payment_month DESC", (g.user['id'],))
    history = cur.fetchall()
    cur.execute("SELECT bank_name, account_number FROM salary_contracts WHERE employee_id=?", (g.user['id'],))
    account = cur.fetchone()
    conn.close()
    
    return render_template('my_salary.html', payment=last_pay, history=history, account=account)

# ----------------------------------------------------
# 6. 기타 설정 및 공지사항 라우트
# ----------------------------------------------------

@app.route('/hr/notices/<int:notice_id>')
@login_required
def view_notice(notice_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM notices WHERE id=?", (notice_id,))
    notice = cur.fetchone()
    conn.close()
    return render_template('notice_detail.html', notice=notice)

@app.route('/hr/notices/add', methods=['GET', 'POST'])
@admin_required
def add_notice_page():
    if request.method == 'POST':
        conn = sqlite3.connect('employees.db')
        cur = conn.cursor()
        cur.execute("INSERT INTO notices (title, content) VALUES (?, ?)", (request.form['title'], request.form['content']))
        conn.commit()
        conn.close()
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

@app.route('/hr/settings')
@admin_required
def settings_management():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute("SELECT * FROM departments")
    d = cur.fetchall()
    cur.execute("SELECT * FROM positions")
    p = cur.fetchall()
    conn.close()
    return render_template('settings_management.html', departments=d, positions=p)

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
    if cursor.fetchone()[0] > 0:
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
    if cursor.fetchone()[0] > 0:
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

if __name__ == '__main__':
    app.run(debug=True)