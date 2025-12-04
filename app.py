from flask import Flask, render_template, request, redirect, url_for, flash, session, g, abort, jsonify
import csv
import io
import sqlite3
from datetime import datetime, time, date, timedelta
from werkzeug.security import generate_password_hash, check_password_hash
from functools import wraps 
import os
from werkzeug.utils import secure_filename
import calendar
from dateutil.relativedelta import relativedelta
import math
import uuid
import requests

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

# 업로드 폴더 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'profile_photos')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------------------------------
# 0. 헬퍼 함수 및 필터 (계산 및 포맷팅)
# ----------------------------------------------------
def get_real_weather():
    API_KEY = "d5d02c8ce25a904d5dd64a317fba7f14" 
    
    # ✅ [수정] 우리 회사 좌표 (예: 강남역 부근)
    # 구글 지도에서 복사한 값을 여기에 넣으세요.
    LAT = "37.584649"  
    LON = "126.925693" 
    
    # ✅ [수정] 쿼리 변경: q={CITY} -> lat={LAT}&lon={LON}
    URL = f"http://api.openweathermap.org/data/2.5/weather?lat={LAT}&lon={LON}&appid={API_KEY}&units=metric&lang=kr"

    try:
        response = requests.get(URL, timeout=5)
        if response.status_code == 200:
            data = response.json()
            return {
                "temp": round(data["main"]["temp"]),
                "desc": data["weather"][0]["description"],
                "icon": data["weather"][0]["icon"],
                # "city": data["name"] # API가 주는 동네 이름은 영어거나 부정확할 수 있음
            }
        return None
    except:
        return None

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

def calculate_monthly_stats(employee_id, year, month):
    """이번 달의 지각, 연장(주말포함), 야간 근무 시간을 계산"""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    start_date = f"{year}-{month:02d}-01"
    # 다음 달 1일 계산
    if month == 12: next_month = f"{year+1}-01-01"
    else: next_month = f"{year}-{month+1:02d}-01"
        
    # 이번 달 기록 조회
    cursor.execute("""
        SELECT record_date, clock_in_time, clock_out_time, attendance_status
        FROM attendance 
        WHERE employee_id = ? 
          AND record_date >= ? AND record_date < ?
    """, (employee_id, start_date, next_month))
    
    records = cursor.fetchall()
    conn.close()
    
    late_count = 0
    extended_seconds = 0 # 연장+휴일 (1.5배 구간)
    night_seconds = 0    # 야간 (0.5배 가산 구간, 즉 22시 이후)

    for row in records:
        if row['attendance_status'] == '지각':
            late_count += 1
            
        if not row['clock_out_time'] or not row['clock_in_time']:
            continue

        try:
            # 날짜/시간 파싱
            r_date = datetime.strptime(row['record_date'], '%Y-%m-%d').date()
            t_in = row['clock_in_time']
            t_out = row['clock_out_time']
            
            # 초 단위 유무 처리
            fmt_in = '%H:%M:%S' if len(t_in) >= 8 else '%H:%M'
            fmt_out = '%H:%M:%S' if len(t_out) >= 8 else '%H:%M'
            
            in_dt = datetime.combine(r_date, datetime.strptime(t_in, fmt_in).time())
            out_dt = datetime.combine(r_date, datetime.strptime(t_out, fmt_out).time())
            
            if out_dt < in_dt: out_dt += timedelta(days=1) # 자정 넘김
            
            is_weekend = r_date.weekday() >= 5 # 토, 일
            
            # 기준 시간
            standard_start = in_dt.replace(hour=9, minute=0, second=0)
            standard_end = in_dt.replace(hour=18, minute=0, second=0)
            night_start = in_dt.replace(hour=22, minute=0, second=0)
            
            # 퇴근이 야간(22:00)을 넘긴 경우 -> 야간 시간 누적
            if out_dt > night_start:
                night_seconds += (out_dt - night_start).total_seconds()
                # 연장 계산을 위해 퇴근 시간을 22:00로 캡(Cap) 씌움 (야간은 별도니까)
                calc_end = night_start
            else:
                calc_end = out_dt
                
            # 연장/휴일 근무 계산 (1.5배 구간)
            if is_weekend:
                # 주말: 출근부터 22시(혹은 퇴근)까지 전부 연장(특근)
                if calc_end > in_dt:
                    extended_seconds += (calc_end - in_dt).total_seconds()
            else:
                # 평일: 18시부터 22시(혹은 퇴근)까지 연장
                if calc_end > standard_end:
                    # 18시 이전에 출근했어도 18시부터 계산
                    start_calc = max(in_dt, standard_end)
                    if calc_end > start_calc:
                        extended_seconds += (calc_end - start_calc).total_seconds()
                        
        except:
            continue

    # 초 -> 시간:분 변환
    def sec_to_hm(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        return f"{h}h {m}m"

    return {
        'late_count': late_count,
        'extended_str': sec_to_hm(extended_seconds),
        'night_str': sec_to_hm(night_seconds)
    }

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

# ✨ [신규] 초과 근무(야근) 수당 계산 함수
def calculate_overtime_pay(employee_id, year, month, base_salary):
    """
    [수당 계산 로직]
    1. 시급 환산: 월 기본급 / 209
    2. 평일: 18:00 ~ 22:00 (1.5배), 22:00 ~ 06:00 (2.0배)
    3. 주말: 09:00 ~ 22:00 (1.5배), 22:00 ~ 06:00 (2.0배) - 하루 종일 수당 처리
    """
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 해당 월의 검색 범위 설정
    start_date = f"{year}-{month:02d}-01"
    if month == 12:
        next_month = f"{year+1}-01-01"
    else:
        next_month = f"{year}-{month+1:02d}-01"
        
    # ✅ [수정] 출근 시간(clock_in_time)과 날짜(record_date)도 필요함
    cursor.execute("""
        SELECT record_date, clock_in_time, clock_out_time 
        FROM attendance 
        WHERE employee_id = ? 
          AND record_date >= ? AND record_date < ?
          AND clock_out_time IS NOT NULL
          AND clock_in_time IS NOT NULL
    """, (employee_id, start_date, next_month))
    
    records = cursor.fetchall()
    conn.close()
    
    # 1. 통상 시급 계산
    hourly_rate = base_salary / 209
    
    total_overtime_pay = 0
    total_overtime_hours = 0
    
    for row in records:
        try:
            # 날짜 및 시간 파싱
            r_date = datetime.strptime(row['record_date'], '%Y-%m-%d').date()
            
            # 시간 파싱 (초 단위 유무 대응)
            t_in = row['clock_in_time']
            t_out = row['clock_out_time']
            in_time = datetime.strptime(t_in[:8], '%H:%M:%S') if len(t_in) >= 8 else datetime.strptime(t_in[:5], '%H:%M')
            out_time = datetime.strptime(t_out[:8], '%H:%M:%S') if len(t_out) >= 8 else datetime.strptime(t_out[:5], '%H:%M')
            
            # 날짜 정보를 시간에 결합 (주말 계산 및 자정 넘김 처리를 위해)
            in_dt = datetime.combine(r_date, in_time.time())
            out_dt = datetime.combine(r_date, out_time.time())
            
            # 퇴근 시간이 출근보다 빠르면(자정 넘김), 하루 더함
            if out_dt < in_dt:
                out_dt += timedelta(days=1)
                
        except:
            continue
            
        # 주말 여부 확인 (0:월 ~ 4:금, 5:토, 6:일)
        is_weekend = r_date.weekday() >= 5
        
        # 기준 시간 설정
        # 평일은 18:00부터 계산, 주말은 출근시간(in_dt)부터 계산
        calc_start = in_dt if is_weekend else in_dt.replace(hour=18, minute=0, second=0)
        
        # 퇴근이 계산 시작 시간보다 빠르면(예: 평일 17시 퇴근) 패스
        if out_dt <= calc_start:
            continue
            
        # 실제 계산 시작 시간 (출근이 18시보다 늦으면 출근시간부터)
        current = max(in_dt, calc_start)
        
        # -------------------------------------------------
        # 시간대별 누적 계산 (1시간 단위 아님, 초 단위 정밀 계산)
        # -------------------------------------------------
        # 야간(22:00) 기준 설정
        night_start = in_dt.replace(hour=22, minute=0, second=0)
        
        # 1. [주간/연장 구간] (~ 22:00 까지)
        if current < night_start:
            # 퇴근이 22시 전이면 퇴근까지, 넘으면 22시까지
            end_normal = min(out_dt, night_start)
            duration = (end_normal - current).total_seconds() / 3600
            
            # 평일 18시~, 주말 전시간 -> 1.5배
            total_overtime_pay += duration * hourly_rate * 1.5
            total_overtime_hours += duration
            
            # 포인터를 22시로 이동
            current = night_start
            
        # 2. [야간 구간] (22:00 ~ 퇴근)
        if out_dt > night_start:
            # 이미 current는 night_start 이상임
            duration = (out_dt - current).total_seconds() / 3600
            
            # 평일/주말 상관없이 밤 10시 넘으면 -> 2.0배 (연장 1.5 + 야간 0.5)
            total_overtime_pay += duration * hourly_rate * 2.0
            total_overtime_hours += duration
            
    return int(total_overtime_pay), round(total_overtime_hours, 1)


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

def calculate_deductions_logic(monthly_salary, non_taxable_amount=200000, rates=None):
    
    if not rates:
        rates = {'pension': 4.5, 'health': 3.545, 'care': 12.95, 'employment': 0.9}

    taxable_income = monthly_salary - non_taxable_amount
    if taxable_income < 0: taxable_income = 0

    pension_base = min(max(monthly_salary, 370000), 5900000)
    national_pension = int(pension_base * (rates['pension'] / 100))
    national_pension = (national_pension // 10) * 10 

    health_insurance = int(monthly_salary * (rates['health'] / 100))
    health_insurance = (health_insurance // 10) * 10

    care_insurance = int(health_insurance * (rates['care'] / 100))
    care_insurance = (care_insurance // 10) * 10

    employment_insurance = int(monthly_salary * (rates['employment'] / 100))
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
    if g.user: return redirect(url_for('dashboard'))
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
            return redirect(url_for('dashboard'))
        else:
            flash("ID 또는 비밀번호가 올바르지 않습니다.", "error")
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 전체 직원 수
    total_employees_count = cursor.execute("SELECT COUNT(*) FROM employees WHERE id != 'admin'").fetchone()[0]
    
    # 2. 근무 현황 통계 & 부재자 리스트
    today_str = datetime.now().strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT e.id, e.name, e.department, e.position,
               COALESCE(a.attendance_status, '부재') as status,
               a.clock_in_time, a.clock_out_time
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.record_date = ?
        WHERE e.id != 'admin' AND e.status = '재직'
    """, (today_str,))
    employees_status = cursor.fetchall()
    
    status_counts = {'재실': 0, '휴가': 0, '외근/출장': 0, '부재': 0}
    absent_list = []

    for emp in employees_status:
        s = emp['status']
        if emp['clock_in_time'] and not emp['clock_out_time']: s = '재실'
        elif s in ['정상', '지각']: s = '재실'
            
        if s == '재실': status_counts['재실'] += 1
        elif s == '휴가': status_counts['휴가'] += 1
        elif s in ['외근', '출장']: status_counts['외근/출장'] += 1
        else: status_counts['부재'] += 1
        
        if s != '재실':
            badge_color = '#e74c3c' # 기본 레드
            if s == '휴가': badge_color = '#3498db'
            elif s in ['외근', '출장']: badge_color = '#f39c12'
            
            absent_list.append({
                'name': emp['name'], 'department': emp['department'], 'status': s, 'color': badge_color
            })

    # 3. 공지사항
    notices = cursor.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5").fetchall()
    
    # 4. 부서별 차트
    dept_stats = cursor.execute("SELECT department, COUNT(*) as count FROM employees WHERE status='재직' AND id!='admin' GROUP BY department ORDER BY count DESC").fetchall()
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['count'] for row in dept_stats]
    
    # 5. 급여 정보 (본인)
    employee_id = g.user['id']
    cursor.execute("SELECT base_salary FROM salary_contracts WHERE employee_id = ?", (employee_id,))
    contract = cursor.fetchone()
    base_salary = contract['base_salary'] if contract else 0

    cursor.execute("SELECT net_salary, payment_month FROM salary_payments WHERE employee_id = ? ORDER BY payment_year DESC, payment_month DESC LIMIT 1", (employee_id,))
    payment = cursor.fetchone()
    last_net_salary = payment['net_salary'] if payment else 0
    last_payment_month = payment['payment_month'] if payment else 0
    
    #6. 미니 캘린더 및 행사 데이터
    
    now = datetime.now()
    current_year = now.year
    current_month = now.month
    
    # 이번 달 달력 매트릭스 생성 (주 단위 리스트의 리스트)
    # 예: [[0, 0, 1, 2, 3, 4, 5], [6, 7, ...], ...]
    cal = calendar.Calendar(firstweekday=6) # 6 = 일요일부터 시작
    month_calendar = cal.monthdayscalendar(current_year, current_month)
    
    # 행사 데이터 (DB에서 가져오거나 하드코딩)
    # 날짜(day)를 키(key)로 하고 행사명(value)을 저장
    events = {
        25: "월급날 💰",
        15: "가정의 날 👨‍👩‍👧‍👦",
        # 오늘 날짜에 예시 이벤트 추가
        now.day: "오늘 (Today)" 
    }

    conn.close()

    # ✅ [핵심] 날씨 데이터 가져오기 (상단에 정의한 함수 호출)
    weather_data = get_real_weather() 
    
    return render_template('dashboard.html', 
                           total_employees_count=total_employees_count,
                           status_counts=status_counts,
                           absent_list=absent_list,
                           notices=notices,
                           dept_labels=dept_labels,
                           dept_counts=dept_counts,
                           base_salary=base_salary,
                           last_net_salary=last_net_salary,
                           last_payment_month=last_payment_month,
                           weather=weather_data,
                           month_calendar=month_calendar,
                           events=events,
                           current_month=current_month,
                           today_day=now.day) # ✅ 템플릿으로 전달
@app.route('/')
@login_required
def root():
    return redirect(url_for('dashboard')) # 기존: hr_management

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
    
    # DB 저장용 및 비교용 변수
    today_str = now.date().strftime('%Y-%m-%d')
    current_time_str = now.strftime('%H:%M:%S')
    display_time_str = now.strftime('%H:%M')

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ✅ [핵심 수정 1] 날짜 조건 제거. 
    # 어제 출근하고 오늘 퇴근하는 경우를 위해 '가장 최근 기록' 1건을 가져옵니다.
    cursor.execute("""
        SELECT id, clock_in_time, clock_out_time, record_date 
        FROM attendance 
        WHERE employee_id = ? 
        ORDER BY id DESC LIMIT 1
    """, (emp_id,))
    last_record = cursor.fetchone()
    
    # 기준 시간 설정
    late_cutoff_time = time(9, 0, 0)     # 지각 기준
    standard_clock_in_str = "09:00:00"   # 정상 출근 기록용
    night_cutoff_time = time(6, 0, 0)    # 야간 근무 종료 기준 (익일 06:00)
    
    msg = ""
    new_state = ""

    try:
        # ----------------------------------------------------
        # 1. 퇴근 처리 (Clock-Out)
        # ----------------------------------------------------
        # 마지막 기록이 있고, 출근은 찍혔는데 퇴근이 안 찍힌 상태라면
        if last_record and last_record['clock_in_time'] and last_record['clock_out_time'] is None:
            
            final_out_time = current_time_str 
            
            # ✅ [핵심 수정 2] 익일 06:00 이후 퇴근 시 시간 조정 로직
            record_date = datetime.strptime(last_record['record_date'], '%Y-%m-%d').date()
            
            # 날짜가 바뀌었고(다음날 등)
            if now.date() > record_date:
                # 현재 시간이 06:00 이상이라면 (예: 07:00 퇴근)
                if now.time() >= night_cutoff_time: 
                    final_out_time = "06:00:00" # 06:00로 강제 고정
                    msg = f"익일 06:00 이후 퇴근하여 06:00로 조정 기록되었습니다."
                else:
                    # 날짜는 지났지만 06:00 이전 (예: 새벽 4시 퇴근) -> 실제 시간 기록
                    msg = f"{display_time_str}에 퇴근(야근) 기록되었습니다."
            else:
                # 당일 퇴근
                msg = f"{display_time_str}에 퇴근 기록되었습니다. 오늘 근무를 마쳤습니다."

            cursor.execute("""
                UPDATE attendance SET clock_out_time = ? 
                WHERE id = ?
            """, (final_out_time, last_record['id']))
            
            new_state = '출근'
            
        # ----------------------------------------------------
        # 2. 출근 처리 (Clock-In)
        # ----------------------------------------------------
        else:
            status = '정상'
            recorded_time_str = standard_clock_in_str # 기본 09:00:00 저장
            
            # 09:00 초과 시 지각 처리 및 실제 시간 기록
            if now.time() > late_cutoff_time:
                status = '지각'
                recorded_time_str = current_time_str 
                msg = f"경고: {display_time_str}에 지각으로 출근이 기록되었습니다."
            else:
                # 09:00 이전 출근
                msg = f"{display_time_str}에 출근 요청됨 (기록 시간: 09:00)."
            
            cursor.execute("""
                INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status)
                VALUES (?, ?, ?, ?)
            """, (emp_id, today_str, recorded_time_str, status)) 
            
            new_state = '퇴근'
        
        conn.commit()
        return jsonify({'success': True, 'message': msg, 'new_button_state': new_state})

    except Exception as e:
        conn.rollback()
        return jsonify({'success': False, 'message': f'서버 오류: {str(e)}'}), 500
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
        elif s == '정상' or s == '지각': s = '재실'
        
        if s in counts: counts[s] += 1
        else: counts['부재'] += 1
        
        if emp['clock_in_time']: emp['check_in'] = emp['clock_in_time'][:5]
        if emp['clock_out_time']: emp['check_out'] = emp['clock_out_time'][:5]

    # 3. 휴가 요청
    cursor.execute("SELECT * FROM vacation_requests WHERE status IN ('대기','승인', '반려') ORDER BY request_date DESC")
    reqs = cursor.fetchall()
    
    conn.close()
    return render_template('attendance_page.html', employees=employees, status_counts=counts, 
                           vacation_requests=reqs, total_employees_count=len(employees),
                           departments=[], positions=[])

@app.route('/attendance/detail/<employee_id>')
@login_required
def attendance_detail(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone() 
    
    if not employee:
        flash(f"직원 ID {employee_id}를 찾을 수 없습니다.", "error")
        conn.close()
        return redirect(url_for('attendance'))
    
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
    
    # 1. 날짜 파라미터 처리
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    start_date = f"{year}-{month:02d}-01"
    last_day = calendar.monthrange(year, month)[1]
    end_date = f"{year}-{month:02d}-{last_day}"
    
    # 2. 필터링 파라미터 (선택 사항)
    f_start = request.args.get('start_date')
    f_end = request.args.get('end_date')
    f_status = request.args.get('status_filter')
    
    # 3. 기간 내 근태 기록 조회
    sql = "SELECT * FROM attendance WHERE employee_id = ? AND record_date BETWEEN ? AND ? ORDER BY record_date DESC"
    cursor.execute(sql, (g.user['id'], start_date, end_date))
    rows = cursor.fetchall()
    
    records = []
    calendar_data = []
    
    for row in rows:
        d = dict(row)
        # 필터링 적용
        if f_start and d['record_date'] < f_start: continue
        if f_end and d['record_date'] > f_end: continue
        if f_status and d['attendance_status'] != f_status: continue
        
        d['date'] = d['record_date']
        d['clock_in'] = d['clock_in_time'][:5] if d['clock_in_time'] else '-'
        d['clock_out'] = d['clock_out_time'][:5] if d['clock_out_time'] else '-'
        d['duration'] = calculate_work_duration(d['clock_in_time'], d['clock_out_time'])
        d['status'] = d['attendance_status']
        records.append(d)
        
        calendar_data.append({'record_date': datetime.strptime(d['record_date'], '%Y-%m-%d').date(), 'attendance_status': d['status']})

    # 4. ✅ [핵심] 통계 계산 함수 호출 (상단에 정의한 함수 사용)
    stats = calculate_monthly_stats(g.user['id'], year, month)
    
    # 템플릿용 통계 데이터 재구성
    monthly_stats = {
        'remaining_leave': 12.0,               # (임시) 잔여 연차
        'late_count': stats['late_count'],     # 지각 횟수
        'extended_work': stats['extended_str'], # 연장+주말 근무 시간
        'night_work': stats['night_str']        # 야간 근무 시간
    }
    
    # 5. ✅ [복구] 오늘의 근무 요약 데이터 조회 (이게 없으면 하단 좌측 카드가 비어보임)
    today_rec = get_today_attendance(g.user['id'])
    today_status = today_rec['attendance_status'] if today_rec else '미등록'
    
    cal_html = create_attendance_calendar(year, month, calendar_data)
    conn.close()
    
    return render_template('my_attendance.html', 
                           attendance_records=records, 
                           calendar_html=cal_html,
                           current_year=year, 
                           current_month=month, 
                           current_month_name=f"{year}년 {month}월",
                           
                           # ✅ [수정] stats 대신 monthly_stats를 전달해야 함!
                           monthly_stats=monthly_stats, 
                           
                           # ✅ [복구] 오늘의 데이터 전달
                           today_record=today_rec or {}, 
                           today_status=today_status,
                           
                           # 필터 값 유지
                           start_date_filter=f_start,
                           end_date_filter=f_end,
                           status_filter_value=f_status)

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
        conn.commit()
        flash(f"요청이 '{new_status}' 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('attendance'))

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

    # 1. 사용자 요청(URL 파라미터)에서 연/월 가져오기
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    start_date = date(year, month, 1)

    # 2. 통계 데이터 계산 (남은 연차 등 포함)
    # (실제 DB 쿼리는 생략하고 로직만 유지합니다. 필요시 calculate_monthly_stats 활용 가능)
    total_annual_leave = 15.0
    used_leave_yearly = 0 

    employee_stats_summary = {
        # ✅ [수정] 현재 시간이 아니라, 선택된 year/month를 사용하도록 변경!
        'target_month': f"{year}년 {month}월",
        'target_year': year,
        
        'monthly': {
            'tardy_count': 0, 'absent_count': 0, 
            'offsite_days': 0, 'business_trip_days': 0, 
            'leave_days': 0, 
            'overtime_hours': '0h 0m', 'overtime_days_count': 0
        },
        'yearly': {
            'tardy_count': 0, 'absent_count': 0, 
            'offsite_days': 0, 'business_trip_days': 0, 
            'leave_days': used_leave_yearly, 
            'remaining_leave': total_annual_leave - used_leave_yearly,
            'overtime_hours': '0h 0m', 'overtime_days_count': 0
        }
    }
    
    calendar_records = []
    calendar_html = create_attendance_calendar(year, month, calendar_records)
    
    conn.close()

    return render_template('attendance_employee_detail.html', 
                           target_user=target_user, 
                           employee_stats_summary=employee_stats_summary, 
                           calendar_html=calendar_html, 
                           current_year=year, 
                           current_month=month, 
                           current_month_name=f"{year}년 {month}월")

@app.route('/attendance_request')
@login_required
@admin_required
def attendance_request():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, department, request_type, start_date, end_date, reason, request_date, status 
        FROM vacation_requests 
        WHERE status = '대기' 
        ORDER BY request_date DESC
    """)
    pending_requests = cursor.fetchall()

    cursor.execute("""
        SELECT id, name, department, request_type, start_date, end_date, reason, request_date, status 
        FROM vacation_requests 
        WHERE status != '대기' 
        ORDER BY request_date DESC
        LIMIT 10
    """)
    processed_requests = cursor.fetchall()
    
    total_requests_query = """SELECT status, COUNT(id) as count FROM vacation_requests GROUP BY status"""
    counts_raw = cursor.execute(total_requests_query).fetchall()

    request_counts = {'대기': 0, '승인': 0, '반려': 0, 'TOTAL': 0}
    for row in counts_raw:
        status = row['status']
        count = row['count']
        if status in request_counts:
            request_counts[status] = count
        request_counts['TOTAL'] += count
    
    conn.close()
    
    return render_template('attendance_request.html', 
                           pending_requests=pending_requests,
                           processed_requests=processed_requests,
                           request_counts=request_counts)
# ----------------------------------------------------
# 13. [신규] 관리자 근태 기록 수정 (Admin Update)
# ----------------------------------------------------
@app.route('/attendance/update', methods=['POST'])
@login_required
@admin_required
def update_attendance():
    employee_id = request.form['employee_id']
    record_date = request.form['record_date']
    clock_in_time = request.form['clock_in_time']
    clock_out_time = request.form['clock_out_time']
    
    # 빈 값 처리 (None으로 저장하거나, '-'이면 NULL 처리)
    # time type input은 값이 없으면 ''(빈 문자열)을 보냅니다.
    
    # HH:MM 형식이므로 초(:00)를 붙여서 저장하는 것이 일반적입니다.
    if clock_in_time: clock_in_time += ":00"
    if clock_out_time: clock_out_time += ":00"
    
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        # 해당 날짜의 기록이 있는지 확인
        cursor.execute("SELECT id FROM attendance WHERE employee_id = ? AND record_date = ?", (employee_id, record_date))
        exists = cursor.fetchone()
        
        if exists:
            # 있으면 업데이트
            cursor.execute("""
                UPDATE attendance 
                SET clock_in_time = ?, clock_out_time = ?, attendance_status = '수정됨'
                WHERE id = ?
            """, (clock_in_time, clock_out_time, exists[0]))
        else:
            # 없으면 새로 생성 (관리자가 강제 기록)
            cursor.execute("""
                INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status)
                VALUES (?, ?, ?, ?, '수정됨')
            """, (employee_id, record_date, clock_in_time, clock_out_time))
            
        conn.commit()
        flash(f"{employee_id} 직원의 근태 기록이 수정되었습니다.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"수정 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('attendance'))
@app.route('/attendance/process/<int:request_id>/<action>', methods=['POST'])
@login_required
@admin_required
def process_request(request_id, action):
    if action not in ['approve', 'reject']:
        flash("잘못된 요청입니다.", "error")
        return redirect(url_for('attendance_request'))
    
    new_status = '승인' if action == 'approve' else '반려'
    
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        cursor.execute("UPDATE vacation_requests SET status = ? WHERE id = ?", (new_status, request_id))
        conn.commit()
        flash(f"요청이 {new_status} 처리되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"처리 중 오류가 발생했습니다: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('attendance_request'))

# ----------------------------------------------------
# 4. 인사 관리 (HR) 라우트
# ----------------------------------------------------

@app.route('/hr')
@login_required
def hr_management():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
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
            # 1. 프로필 이미지 처리 (기본값 설정)
            profile_image_filename = 'default.jpg' 
            
            if 'profile_image' in request.files:
                f = request.files['profile_image']
                if f.filename:
                    # 확장자 추출 및 UUID 파일명 생성
                    ext = f.filename.rsplit('.', 1)[1].lower()
                    new_filename = f"{uuid.uuid4()}.{ext}"
                    
                    # 폴더가 없으면 생성 후 저장
                    if not os.path.exists(app.config['UPLOAD_FOLDER']):
                        os.makedirs(app.config['UPLOAD_FOLDER'])
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], new_filename))
                    profile_image_filename = new_filename

            # 2. 사번 생성 로직
            dept = request.form['department']
            cur.execute("SELECT code FROM departments WHERE name=?", (dept,))
            code_row = cur.fetchone()
            code = code_row[0] if code_row else 'XX'

            prefix = f"{request.form['hire_date'][2:4]}{code}"
            cur.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (f"{prefix}%",))
            last = cur.fetchone()
            seq = int(last[0][-4:]) + 1 if last else 1
            new_id = f"{prefix}{seq:04d}"
            
            # 3. 직원 기본 정보(employees) 저장
            cur.execute("""
                INSERT INTO employees (id, name, department, position, hire_date, birth_date, phone_number, email, address, gender, status, profile_image)
                VALUES (?,?,?,?,?,?,?,?,?,?, '재직', ?)
            """, (new_id, request.form['name'], dept, request.form['position'], 
                  request.form['hire_date'], 
                  request.form['birth_date'], # 👈 추가됨
                  f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}",
                  f"{request.form['email_id']}@{request.form['email_domain']}",
                  request.form['address'], request.form['gender'], profile_image_filename))
            
            # 4. 로그인 정보(users) 저장
            cur.execute("INSERT INTO users (employee_id, username, password_hash, role) VALUES (?,?,?,?)",
                        (new_id, new_id, generate_password_hash(request.form['password']), request.form.get('role', 'user')))
            
            # ✨ [추가된 부분] 5. 급여/계좌 정보(salary_contracts) 연결 저장
            # 입력폼에서 은행과 계좌번호를 가져옵니다.
            bank_name = request.form.get('bank_name', '')
            account_number = request.form.get('account_number', '')
            
            # 연봉/기본급은 아직 모르므로 0원으로 초기화하여 계좌 정보만 우선 저장합니다.
            cur.execute("""
                INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number)
                VALUES (?, 0, 0, ?, ?)
            """, (new_id, bank_name, account_number))
            
            conn.commit()
            flash(f"직원 {request.form['name']}({new_id}) 등록 및 계좌 연결 완료", "success")
            return redirect(url_for('hr_management'))

        except Exception as e:
            conn.rollback()
            flash(f"등록 실패: {e}", "error")
            
    # GET 요청 처리
    cur.execute("SELECT name FROM departments")
    d = cur.fetchall()
    cur.execute("SELECT name FROM positions")
    p = cur.fetchall()
    cur.execute("SELECT domain FROM email_domains")
    e = cur.fetchall()
    conn.close()
    return render_template('add_employee.html', departments=d, positions=p, email_domains=e)

@app.route('/hr/edit/<employee_id>', methods=['GET', 'POST'])
@login_required
def edit_employee(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    if request.method == 'POST':
        try:
            # 1. 프로필 이미지 처리
            img = request.form.get('current_image')
            if 'profile_image' in request.files:
                f = request.files['profile_image']
                if f.filename:
                    ext = f.filename.rsplit('.', 1)[1].lower()
                    fname = f"{uuid.uuid4()}.{ext}"
                    if not os.path.exists(app.config['UPLOAD_FOLDER']):
                        os.makedirs(app.config['UPLOAD_FOLDER'])
                    f.save(os.path.join(app.config['UPLOAD_FOLDER'], fname))
                    img = fname
            
            # 2. 직원 기본 정보 업데이트 (employees 테이블)
            cur.execute("""
                UPDATE employees 
                SET name=?, department=?, position=?, hire_date=?, birth_date=?, phone_number=?, email=?, address=?, gender=?, status=?, profile_image=? 
                WHERE id=?
            """, (
                request.form['name'], 
                request.form['department'], 
                request.form['position'],
                request.form['hire_date'],
                request.form['birth_date'], # 👈 추가됨
                f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}",
                f"{request.form['email_id']}@{request.form['email_domain']}",
                request.form['address'], 
                request.form['gender'],
                request.form['status'], 
                img, 
                employee_id
            ))
            
            # 3. ✅ [신규] 급여 계좌 정보 업데이트 (salary_contracts 테이블)
            bank_name = request.form.get('bank_name', '')
            account_number = request.form.get('account_number', '')
            
            # 계약 정보가 있는지 확인
            cur.execute("SELECT id FROM salary_contracts WHERE employee_id=?", (employee_id,))
            contract_exist = cur.fetchone()
            
            if contract_exist:
                cur.execute("UPDATE salary_contracts SET bank_name=?, account_number=? WHERE employee_id=?", 
                            (bank_name, account_number, employee_id))
            else:
                # 없으면 새로 생성 (기본급 0원으로)
                cur.execute("INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number) VALUES (?, 0, 0, ?, ?)", 
                            (employee_id, bank_name, account_number))

            conn.commit()
            flash("직원 정보가 수정되었습니다.", "success")
            return redirect(url_for('employee_detail', employee_id=employee_id))
            
        except Exception as e:
            conn.rollback()
            flash(f"수정 중 오류 발생: {e}", "error")

    # --- GET 요청 처리 ---
    emp = cur.execute("SELECT * FROM employees WHERE id=?", (employee_id,)).fetchone()
    
    # ✅ [신규] 계좌 정보 조회 (수정 폼에 채워 넣기 위함)
    contract = cur.execute("SELECT bank_name, account_number FROM salary_contracts WHERE employee_id=?", (employee_id,)).fetchone()
    
    d = cur.execute("SELECT name FROM departments").fetchall()
    p = cur.execute("SELECT name FROM positions").fetchall()
    e = cur.execute("SELECT domain FROM email_domains").fetchall()
    conn.close()
    
    # 데이터 가공
    phone = emp['phone_number'].split('-') if emp['phone_number'] else ['','','']
    email = emp['email'].split('@') if emp['email'] else ['','']
    
    return render_template('edit_employee.html', 
                           employee=dict(emp), 
                           contract=contract, # ✅ 템플릿으로 전달
                           departments=d, positions=p, email_domains=e, 
                           phone_parts=phone, email_parts=email)

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
    
    # 퇴사 처리 (권한 강등 포함)
    cursor.execute("UPDATE employees SET status = '퇴사' WHERE id = ?", (employee_id,))
    cursor.execute("UPDATE users SET role = 'user' WHERE employee_id = ?", (employee_id,)) 
    
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 퇴사 처리되었습니다.", "success")
    
    # ✅ [핵심] 처리가 끝나면 인사 관리 페이지로 돌아가되, 방금 그 직원의 모달을 다시 엽니다.
    return redirect(url_for('hr_management', open_modal=employee_id))

# ✅ [수정] 재입사 처리
@app.route('/hr/rehire/<employee_id>', methods=['POST'])
@admin_required 
def process_rehire(employee_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    cursor.execute("UPDATE employees SET status = '재직' WHERE id = ?", (employee_id,))
    
    conn.commit()
    conn.close()
    flash(f"직원({employee_id})이 재입사 처리되었습니다.", "success")
    
    # ✅ [핵심] 마찬가지로 모달을 다시 엽니다.
    return redirect(url_for('hr_management', open_modal=employee_id))

# ----------------------------------------------------
# 5. 급여 관리 (Payroll) 섹션
# ----------------------------------------------------

@app.route('/salary/payroll', methods=['GET'])
@admin_required
def salary_payroll():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    # 검색 필터 파라미터 받기 (이름, 부서, 직급)
    search_name = request.args.get('search_name', '')
    search_dept = request.args.get('search_dept', '')
    search_pos = request.args.get('search_pos', '') # [추가] 직급 검색 파라미터

    # 기본 쿼리
    sql = """
        SELECT p.*, e.name, e.department, e.position 
        FROM salary_payments p
        JOIN employees e ON p.employee_id = e.id
        WHERE p.payment_year = ? AND p.payment_month = ?
    """
    params = [year, month]

    # [수정] 필터링 조건 추가 (직급 포함)
    if search_name:
        sql += " AND e.name LIKE ?"
        params.append(f"%{search_name}%")
    if search_dept:
        sql += " AND e.department = ?"
        params.append(search_dept)
    if search_pos: # [추가] 직급 조건
        sql += " AND e.position = ?"
        params.append(search_pos)
    
    sql += " ORDER BY e.id ASC"

    cur.execute(sql, params)
    
    existing_payroll = [dict(row) for row in cur.fetchall()]
    is_calculated = len(existing_payroll) > 0
    
    # 총 합계 계산
    grand_total = {
        'base': 0, 'allowance': 0, 'overtime': 0, 
        'total_pay': 0, 'deduction': 0, 'net': 0
    }
    
    for p in existing_payroll:
        grand_total['base'] += p['total_base']
        grand_total['allowance'] += p['total_allowance']
        grand_total['overtime'] += p.get('overtime_pay', 0) # 안전하게 get 사용
        grand_total['total_pay'] += (p['total_base'] + p['total_allowance'] + p.get('overtime_pay', 0))
        grand_total['deduction'] += p['total_deduction']
        grand_total['net'] += p['net_salary']

    # 검색 드롭다운용 목록 가져오기
    cur.execute("SELECT name FROM departments")
    departments = [row['name'] for row in cur.fetchall()]
    
    cur.execute("SELECT name FROM positions") # [추가] 직급 목록 가져오기
    positions = [row['name'] for row in cur.fetchall()]
    
    conn.close()
    
    return render_template('salary_list.html', 
                           year=year, month=month, 
                           payrolls=existing_payroll, 
                           is_calculated=is_calculated,
                           grand_total=grand_total,
                           departments=departments,
                           positions=positions, # [추가] 템플릿 전달
                           search_name=search_name,
                           search_dept=search_dept,
                           search_pos=search_pos) # [추가] 현재 검색어 전달

# [신규 추가] 재직증명서 출력 라우트
@app.route('/hr/certificate/<employee_id>')
@login_required
def print_certificate(employee_id):
    # 본인 또는 관리자만 출력 가능
    if g.user['role'] != 'admin' and g.user['id'] != employee_id:
        flash("권한이 없습니다.", "error")
        return redirect(url_for('hr_management'))

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,))
    employee = cursor.fetchone()
    conn.close()
    
    # 오늘 날짜
    today = datetime.now().strftime('%Y년 %m월 %d일')
    
    return render_template('print_certificate.html', employee=employee, today=today)

@app.route('/salary/download/excel')
@admin_required
def download_salary_excel():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    year = request.args.get('year', datetime.now().year, type=int)
    month = request.args.get('month', datetime.now().month, type=int)
    
    cur.execute("""
        SELECT p.*, e.name, e.department, e.position 
        FROM salary_payments p
        JOIN employees e ON p.employee_id = e.id
        WHERE p.payment_year = ? AND p.payment_month = ?
        ORDER BY e.id
    """, (year, month))
    rows = cur.fetchall()
    conn.close()

    output = io.StringIO()
    output.write(u'\ufeff')
    writer = csv.writer(output)
    
    # 헤더에 '야근수당' 추가
    headers = ['사번', '이름', '부서', '직급', '기본급', '수당', '야근수당', '공제총액', '실수령액', '지급일', 
               '국민연금', '건강보험', '장기요양', '고용보험', '소득세', '지방소득세']
    writer.writerow(headers)
    
    for row in rows:
        writer.writerow([
            row['employee_id'], 
            row['name'], 
            row['department'], 
            row['position'],
            row['total_base'], 
            row['total_allowance'], 
            row['overtime_pay'], # ✨ 추가
            row['total_deduction'], 
            row['net_salary'], 
            row['payment_date'],
            row['national_pension'],
            row['health_insurance'],
            row['care_insurance'],
            row['employment_insurance'],
            row['income_tax'],
            row['local_tax']
        ])
        
    from flask import Response
    return Response(
        output.getvalue(),
        mimetype="text/csv",
        headers={"Content-disposition": f"attachment; filename=payroll_{year}_{month}.csv"}
    )

@app.route('/salary/contracts', methods=['GET', 'POST'])
@admin_required
def salary_contracts():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        emp_id = request.form['employee_id']
        annual_salary = int(request.form['annual_salary'].replace(',', ''))
        bank_name = request.form['bank_name']
        account_number = request.form['account_number']
        base_salary = annual_salary // 12
        
        try:
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

@app.route('/salary/deductions', methods=['GET'])
@admin_required
def salary_deductions():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 직원 목록 조회
    cursor.execute("""
        SELECT e.id, e.name, e.department, e.position
        FROM employees e
        WHERE e.status = '재직' AND e.id != 'admin'
        ORDER BY e.id
    """)
    employees = cursor.fetchall()
    
    # 2. 직원별 공제 항목 매핑
    deduction_map = {}
    for emp in employees:
        cursor.execute("SELECT * FROM fixed_deductions WHERE employee_id=?", (emp['id'],))
        items = cursor.fetchall()
        deduction_map[emp['id']] = items
    
    # ✨ [추가] 3. 부서 및 직급 목록 조회 (드롭다운용)
    cursor.execute("SELECT name FROM departments ORDER BY name")
    departments = [row['name'] for row in cursor.fetchall()]
    
    cursor.execute("SELECT name FROM positions ORDER BY id") # 혹은 순서가 있다면 정렬
    positions = [row['name'] for row in cursor.fetchall()]
        
    conn.close()
    
    # 템플릿에 departments와 positions를 함께 전달
    return render_template('salary_deductions.html', 
                           employees=employees, 
                           deduction_map=deduction_map,
                           departments=departments, 
                           positions=positions)

# ✨ [신규] 그룹별 수당/공제 일괄 추가 기능
@app.route('/salary/add_group_item', methods=['POST'])
@admin_required
def add_group_item():
    target_type = request.form['target_type']  # 'all', 'department', 'position', 'individual'
    target_value = request.form.get('target_value', '') 
    item_type = request.form['item_type']      # 'allowance' or 'deduction'
    name = request.form['item_name']
    amount = int(request.form['amount'].replace(',', ''))
    
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    try:
        sql = "SELECT id FROM employees WHERE status = '재직' AND id != 'admin'"
        params = []
        
        if target_type == 'department':
            sql += " AND department = ?"
            params.append(target_value)
        elif target_type == 'position':
            sql += " AND position = ?"
            params.append(target_value)
        elif target_type == 'individual':
            sql += " AND id = ?"
            params.append(target_value)
        
        cursor.execute(sql, params)
        targets = cursor.fetchall()
        
        count = 0
        for emp in targets:
            if item_type == 'allowance':
                cursor.execute("INSERT INTO fixed_allowances (employee_id, allowance_name, amount) VALUES (?, ?, ?)",
                               (emp['id'], name, amount))
            else:
                cursor.execute("INSERT INTO fixed_deductions (employee_id, deduction_name, amount) VALUES (?, ?, ?)",
                               (emp['id'], name, amount))
            count += 1
            
        conn.commit()
        flash(f"총 {count}명에게 '{name}' 항목이 일괄 등록되었습니다.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('salary_deductions'))

@app.route('/salary/settings', methods=['GET', 'POST'])
@admin_required
def salary_settings():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    if request.method == 'POST':
        try:
            cursor.execute("""
                UPDATE payroll_rates 
                SET national_pension_rate=?, health_insurance_rate=?, 
                    care_insurance_rate=?, employment_insurance_rate=?
                WHERE id=1
            """, (
                float(request.form['pension']),
                float(request.form['health']),
                float(request.form['care']),
                float(request.form['employment'])
            ))
            conn.commit()
            flash("4대보험 요율 설정이 저장되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"오류 발생: {e}", "error")
            
    cursor.execute("SELECT * FROM payroll_rates WHERE id=1")
    rates = cursor.fetchone()
    conn.close()
    
    return render_template('salary_settings.html', rates=rates)

@app.route('/salary/deductions/add', methods=['POST'])
@admin_required
def add_deduction():
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    try:
        emp_id = request.form['employee_id']
        name = request.form['deduction_name']
        amount = int(request.form['amount'].replace(',', ''))
        
        cursor.execute("INSERT INTO fixed_deductions (employee_id, deduction_name, amount) VALUES (?, ?, ?)", 
                       (emp_id, name, amount))
        conn.commit()
        flash(f"{name} 공제 항목이 추가되었습니다.", "success")
    except Exception as e:
        conn.rollback()
        flash(f"오류: {e}", "error")
    finally:
        conn.close()
    return redirect(url_for('salary_deductions'))

@app.route('/salary/deductions/delete/<int:deduction_id>', methods=['POST'])
@admin_required
def delete_deduction(deduction_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM fixed_deductions WHERE id=?", (deduction_id,))
    conn.commit()
    conn.close()
    return redirect(url_for('salary_deductions'))

@app.route('/salary/calculate_all', methods=['POST'])
@admin_required
def calculate_all_salary():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    year = datetime.now().year
    month = datetime.now().month
    payment_date = f"{year}-{month:02d}-10"  # 매월 10일 지급 가정

    try:
        cur.execute("SELECT * FROM payroll_rates WHERE id = 1")
        rate_row = cur.fetchone()
        
        current_rates = {
            'pension': rate_row['national_pension_rate'],
            'health': rate_row['health_insurance_rate'],
            'care': rate_row['care_insurance_rate'],
            'employment': rate_row['employment_insurance_rate']
        }

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
            
            # ✨ [추가] 야근 수당 계산
            overtime_amt, overtime_hours = calculate_overtime_pay(emp_id, year, month, base_salary)
            
            # 야근 수당은 과세 대상이므로 총 소득에 합산
            total_monthly_income += overtime_amt
            
            deductions = calculate_deductions_logic(total_monthly_income, non_taxable, rates=current_rates)
            
            cur.execute("SELECT SUM(amount) FROM fixed_deductions WHERE employee_id=?", (emp_id,))
            extra_deduction_sum = cur.fetchone()[0] or 0
            final_total_deduction = deductions['total_deduction'] + extra_deduction_sum
            net_salary = total_monthly_income - final_total_deduction
            
            cur.execute("""
                INSERT INTO salary_payments (
                    employee_id, payment_year, payment_month, payment_date,
                    total_base, total_allowance, overtime_pay, total_deduction, net_salary, 
                    national_pension, health_insurance, care_insurance, employment_insurance,
                    income_tax, local_tax
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                emp_id, year, month, payment_date,
                base_salary, allowance_sum, overtime_amt, final_total_deduction, net_salary,
                deductions['national_pension'], deductions['health_insurance'], 
                deductions['care_insurance'], deductions['employment_insurance'],
                deductions['income_tax'], deductions['local_tax']
            ))
            count += 1
            
        conn.commit()
        flash(f"총 {count}명의 급여가 최신 요율로 계산되었습니다. (야근수당 포함)", "success")
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
    
    user_id = g.user['id']
    
    # ---------------------------------------------------------
    # 1. 입사일 기준 조회 가능한 날짜 리스트 생성 (입사월 ~ 현재)
    # ---------------------------------------------------------
    try:
        # DB의 hire_date 문자열(YYYY-MM-DD)을 날짜 객체로 변환
        hire_date = datetime.strptime(g.user['hire_date'], '%Y-%m-%d')
    except:
        # 입사일 오류 시 현재 날짜를 기준으로 처리 (방어 코드)
        hire_date = datetime.now()

    today = datetime.now()
    available_periods = []

    # 입사일의 '월' 1일부터 시작 ~ 현재 날짜의 '월' 1일까지 반복
    # 예: 24년 3월 입사 -> 24-3, 24-4, ... 25-12
    curr = hire_date.replace(day=1)
    end = today.replace(day=1)

    while curr <= end:
        available_periods.append((curr.year, curr.month))
        curr += relativedelta(months=1)

    # 최신 날짜가 위로 오도록 정렬 (내림차순)
    available_periods.reverse()

    # ---------------------------------------------------------
    # 2. 사용자가 선택한 날짜 처리 (Dropdown 값)
    # ---------------------------------------------------------
    selected_year = None
    selected_month = None
    
    # HTML form에서 name="period"로 넘겨준 값 (예: "2024-5") 받기
    period = request.args.get('period') 
    
    if period:
        try:
            y_str, m_str = period.split('-')
            selected_year = int(y_str)
            selected_month = int(m_str)
        except:
            pass # 파싱 에러 시 무시

    # 선택값이 없거나(처음 접속), 잘못된 값이면 -> "가장 최신 날짜"로 자동 설정
    if not selected_year or not selected_month:
        if available_periods:
            selected_year, selected_month = available_periods[0]
        else:
            selected_year, selected_month = today.year, today.month

    # ---------------------------------------------------------
    # 3. DB 조회
    # ---------------------------------------------------------
    
    # (1) 선택된 연/월의 급여 정보 (단건 조회)
    cur.execute("""
        SELECT * FROM salary_payments
        WHERE employee_id = ? AND payment_year = ? AND payment_month = ?
    """, (user_id, selected_year, selected_month))
    payment = cur.fetchone() 

    # (2) 전체 급여 이력 조회 (하단 리스트용 - 그대로 유지)
    cur.execute("""
        SELECT * FROM salary_payments
        WHERE employee_id = ?
        ORDER BY payment_year DESC, payment_month DESC
    """, (user_id,))
    history = cur.fetchall()

    # (3) 계좌 정보 조회
    cur.execute("SELECT bank_name, account_number FROM salary_contracts WHERE employee_id=?", (user_id,))
    account = cur.fetchone()

    conn.close()
    
    return render_template('my_salary.html', 
                           payment=payment, 
                           history=history, 
                           account=account,
                           available_periods=available_periods, # [핵심] 날짜 리스트 전달
                           selected_year=selected_year,         # [핵심] 현재 보여주는 연도
                           selected_month=selected_month)       # [핵심] 현재 보여주는 월

@app.route('/salary/print/<int:payment_id>')
@login_required
def print_salary(payment_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    cur.execute("""
        SELECT p.*, e.name, e.department, e.position, e.hire_date
        FROM salary_payments p
        JOIN employees e ON p.employee_id = e.id
        WHERE p.id = ?
    """, (payment_id,))
    payment = cur.fetchone()
    
    if not payment or (g.user['role'] != 'admin' and payment['employee_id'] != g.user['id']):
        flash("접근 권한이 없습니다.", "error")
        conn.close()
        return redirect(url_for('my_salary'))
        
    cur.execute("SELECT bank_name, account_number FROM salary_contracts WHERE employee_id=?", (payment['employee_id'],))
    account = cur.fetchone()
    
    conn.close()
    
    return render_template('print_salary.html', payment=payment, account=account)

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
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()

    if request.method == 'POST':
        try:
            title = request.form['title']
            content = request.form['content']
            cur.execute("INSERT INTO notices (title, content) VALUES (?, ?)", (title, content))
            conn.commit()
            flash("새 공지사항이 등록되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"등록 중 오류가 발생했습니다: {e}", "error")
            
        # ✅ [수정] 작성 후 목록 확인을 위해 '현재 페이지'로 리다이렉트
        return redirect(url_for('add_notice_page'))

    # ✅ [추가] GET 요청 시: 기존 공지사항 목록 조회 (최신순)
    cur.execute("SELECT * FROM notices ORDER BY created_at DESC")
    notices = cur.fetchall()
    conn.close()

    return render_template('add_notice_page.html', notices=notices)

@app.route('/hr/notices/delete/<int:notice_id>', methods=['POST'])
@admin_required
def delete_notice(notice_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    cursor.execute("DELETE FROM notices WHERE id = ?", (notice_id,))
    conn.commit()
    conn.close()
    flash("공지사항이 삭제되었습니다.", "success")
    
    # ✅ [핵심 수정] 삭제 후 '인사 현황'이 아닌 '공지사항 작성/목록' 페이지로 복귀
    # 이전 코드: return redirect(url_for('hr_management'))
    return redirect(url_for('add_notice_page'))

@app.route('/hr/settings')
@admin_required
def settings_management():
    conn = sqlite3.connect('employees.db'); conn.row_factory = sqlite3.Row; cur = conn.cursor()
    
    # 부서 조회 (기존)
    active_depts = cur.execute("SELECT * FROM departments WHERE is_active = 1").fetchall()
    inactive_depts = cur.execute("SELECT * FROM departments WHERE is_active = 0").fetchall()
    
    # ✅ [수정] 직급 조회 (활성/비활성 분리)
    active_positions = cur.execute("SELECT * FROM positions WHERE is_active = 1").fetchall()
    inactive_positions = cur.execute("SELECT * FROM positions WHERE is_active = 0").fetchall()
    
    conn.close()
    
    return render_template('settings_management.html', 
                           active_departments=active_depts, inactive_departments=inactive_depts,
                           active_positions=active_positions, inactive_positions=inactive_positions) # ✅ 전달 변수 변경
@app.route('/hr/settings/toggle_position/<int:pos_id>/<int:status>', methods=['POST'])
@admin_required
def toggle_position_status(pos_id, status):
    conn = sqlite3.connect('employees.db'); cursor = conn.cursor()
    try:
        if status == 0: # 비활성 시도 시 체크
            pos_name = cursor.execute("SELECT name FROM positions WHERE id=?", (pos_id,)).fetchone()[0]
            count = cursor.execute("SELECT COUNT(*) FROM employees WHERE position=? AND status='재직'", (pos_name,)).fetchone()[0]
            if count > 0:
                flash(f"⛔ '{pos_name}' 직급인 직원이 {count}명 있어 비활성할 수 없습니다.", "error")
                return redirect(url_for('settings_management'))
                
        cursor.execute("UPDATE positions SET is_active=? WHERE id=?", (status, pos_id))
        conn.commit()
        flash("직급 상태가 변경되었습니다.", "success")
    except Exception as e:
        conn.rollback(); flash(f"오류: {e}", "error")
    finally: conn.close()
    return redirect(url_for('settings_management'))
@app.route('/hr/settings/toggle_department/<int:dept_id>/<int:status>', methods=['POST'])
@admin_required
def toggle_department_status(dept_id, status):
    """
    부서 상태 변경 (status: 1=활성, 0=비활성)
    안전장치: 비활성(0) 시도 시, 해당 부서에 '재직' 중인 직원이 있으면 막음.
    """
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        # ✅ [안전장치 추가] 비활성화(0)를 시도하는 경우 체크
        if status == 0:
            # 1. 부서 이름 먼저 조회
            cursor.execute("SELECT name FROM departments WHERE id = ?", (dept_id,))
            dept_row = cursor.fetchone()
            
            if dept_row:
                dept_name = dept_row[0]
                
                # 2. 해당 부서에 '재직' 중인 직원 수 확인
                cursor.execute("SELECT COUNT(*) FROM employees WHERE department = ? AND status = '재직'", (dept_name,))
                emp_count = cursor.fetchone()[0]
                
                # 3. 직원이 있으면 거부 (return)
                if emp_count > 0:
                    flash(f"⛔ '{dept_name}' 부서에 재직 중인 직원이 {emp_count}명 있습니다. 먼저 부서 이동 처리를 해주세요.", "error")
                    conn.close()
                    return redirect(url_for('settings_management'))

        # 이상 없으면 상태 변경 진행
        cursor.execute("UPDATE departments SET is_active = ? WHERE id = ?", (status, dept_id))
        conn.commit()
        
        msg = "✅ 부서가 활성화되었습니다." if status == 1 else "✅ 부서가 비활성화되었습니다."
        flash(msg, "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('settings_management'))

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
@app.route('/hr/settings/edit_position', methods=['POST'])
@admin_required
def edit_position():
    position_id = request.form['position_id']
    new_name = request.form['new_position_name'].strip()
    
    if new_name:
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE positions SET name = ? WHERE id = ?", (new_name, position_id))
            # (선택 사항) employees 테이블의 직급명도 같이 바꿔주려면 아래 쿼리 추가
            # cursor.execute("UPDATE employees SET position = ? WHERE position = (SELECT name FROM positions WHERE id = ?)", (new_name, position_id))
            
            conn.commit()
            flash("직급 정보가 수정되었습니다.", "success")
        except Exception as e:
            conn.rollback()
            flash(f"오류 발생: {e}", "error")
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

@app.route('/my_page')
@login_required
def my_page():
    employee_id = g.user['id']
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    cursor.execute("SELECT * FROM salary_contracts WHERE employee_id = ?", (employee_id,))
    contract = cursor.fetchone()
    
    current_month_str = datetime.now().strftime('%Y-%m')
    
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN attendance_status = '지각' THEN 1 END) as late_count,
            COUNT(CASE WHEN attendance_status = '결근' THEN 1 END) as absent_count
        FROM attendance 
        WHERE employee_id = ? AND strftime('%Y-%m', record_date) = ?
    """, (employee_id, current_month_str))
    month_row = cursor.fetchone()
    
    monthly_stats = {
        'late_count': month_row['late_count'],
        'absent_count': month_row['absent_count'],
        'overtime_hours': '0h 0m',
        'overtime_days': 0        
    }

    yearly_stats = {
        'late_count': month_row['late_count'] + 2, 
        'absent_count': month_row['absent_count'],
        'overtime_hours': '12h 30m',
        'overtime_days': 5
    }
    
    remaining_leave = 12.0 

    tenure_text = ""
    try:
        hire_date = datetime.strptime(g.user['hire_date'], '%Y-%m-%d')
        diff = relativedelta(datetime.now(), hire_date)
        if diff.years > 0: tenure_text = f"({diff.years}년 {diff.months}개월차)"
        elif diff.months == 0: tenure_text = "(신입)"
        else: tenure_text = f"({diff.months}개월차)"
    except ValueError:
        tenure_text = ""

    conn.close()
    
    return render_template('my_page.html', 
                           contract=contract, 
                           monthly_stats=monthly_stats, 
                           yearly_stats=yearly_stats,
                           remaining_leave=remaining_leave,
                           tenure_text=tenure_text)

# ==========================================
# [신규 추가] 직원 상세 정보 모달용 데이터 반환
# ==========================================
@app.route('/hr/employee/modal/<employee_id>')
@login_required
def get_employee_detail_modal(employee_id):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 기본 정보 & 급여 계약 정보 조회
    cursor.execute("""
        SELECT e.*, s.base_salary, s.annual_salary 
        FROM employees e
        LEFT JOIN salary_contracts s ON e.id = s.employee_id
        WHERE e.id = ?
    """, (employee_id,))
    employee = cursor.fetchone()

    if not employee:
        conn.close()
        return "직원 정보를 찾을 수 없습니다.", 404

    # 2. 근태 기록 (최근 30일)
    thirty_days_ago = (datetime.now() - timedelta(days=30)).strftime('%Y-%m-%d')
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? AND record_date >= ?
        ORDER BY record_date DESC
    """, (employee_id, thirty_days_ago))
    attendance_records = cursor.fetchall()

    # 3. 근태 통계 (이번 달)
    current_month_str = datetime.now().strftime('%Y-%m')
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN attendance_status='지각' THEN 1 END) as late,
            COUNT(CASE WHEN attendance_status='결근' THEN 1 END) as absent,
            COUNT(CASE WHEN attendance_status='조퇴' THEN 1 END) as early_leave
        FROM attendance 
        WHERE employee_id = ? AND strftime('%Y-%m', record_date) = ?
    """, (employee_id, current_month_str))
    stats = cursor.fetchone()
    attendance_stats = {'late': stats['late'], 'absent': stats['absent'], 'early_leave': stats['early_leave']}
    
    # 4. 고정 수당/공제 (간략히)
    cursor.execute("SELECT allowance_name, amount FROM fixed_allowances WHERE employee_id = ?", (employee_id,))
    allowances = cursor.fetchall()
    
    conn.close()
    
    # ✅ 중요: base.html을 확장하지 않는 '조각 템플릿'을 렌더링합니다.
    return render_template('modal_employee_detail.html', 
                           employee=employee,
                           attendance_records=attendance_records,
                           attendance_stats=attendance_stats,
                           allowances=allowances)

if __name__ == '__main__':
    app.run(debug=True)