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
import random

app = Flask(__name__)
app.secret_key = 'your_super_secret_key' 

app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=3000)
# 업로드 폴더 설정
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'profile_photos')
app.config['UPLOAD_FOLDER'] = UPLOAD_FOLDER

# ----------------------------------------------------
# 0. 헬퍼 함수 및 필터 (계산 및 포맷팅)
# ----------------------------------------------------
# [추가] 연출용 시간 고정 함수
# (수정 후 - 추천 코드)
def get_mock_now():
    real_now = datetime.now()
    # 날짜는 2025-12-11 고정, 시간은 현재 컴퓨터 시간 사용
    return datetime(2025, 12, 11, real_now.hour, real_now.minute, real_now.second)
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
    """이번 달의 지각, 연장(주말포함), 야간 근무 시간 및 일수 계산"""
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    start_date = f"{year}-{month:02d}-01"
    if month == 12: next_month = f"{year+1}-01-01"
    else: next_month = f"{year}-{month+1:02d}-01"
        
    cursor.execute("""
        SELECT record_date, clock_in_time, clock_out_time, attendance_status
        FROM attendance 
        WHERE employee_id = ? 
          AND record_date >= ? AND record_date < ?
    """, (employee_id, start_date, next_month))
    
    records = cursor.fetchall()
    conn.close()
    
    late_count = 0
    extended_seconds = 0 # 연장+휴일 총 시간
    night_seconds = 0    # 야간 총 시간
    
    # ✅ [추가] 연장 근무 일수 카운트 변수
    overtime_days_count = 0 

    for row in records:
        if row['attendance_status'] == '지각':
            late_count += 1
            
        if not row['clock_out_time'] or not row['clock_in_time']:
            continue

        try:
            r_date = datetime.strptime(row['record_date'], '%Y-%m-%d').date()
            t_in = row['clock_in_time']
            t_out = row['clock_out_time']
            
            fmt_in = '%H:%M:%S' if len(t_in) >= 8 else '%H:%M'
            fmt_out = '%H:%M:%S' if len(t_out) >= 8 else '%H:%M'
            
            in_dt = datetime.combine(r_date, datetime.strptime(t_in, fmt_in).time())
            out_dt = datetime.combine(r_date, datetime.strptime(t_out, fmt_out).time())
            
            if out_dt < in_dt: out_dt += timedelta(days=1)
            
            is_weekend = r_date.weekday() >= 5
            
            standard_start = in_dt.replace(hour=9, minute=0, second=0)
            standard_end = in_dt.replace(hour=18, minute=0, second=0)
            night_start = in_dt.replace(hour=22, minute=0, second=0)
            
            # 야간 계산
            if out_dt > night_start:
                night_seconds += (out_dt - night_start).total_seconds()
                calc_end = night_start
            else:
                calc_end = out_dt
                
            # ✅ [수정] 오늘 연장 근무가 발생했는지 체크하는 플래그
            is_overtime_today = False

            # 연장 계산
            if is_weekend:
                if calc_end > in_dt:
                    diff = (calc_end - in_dt).total_seconds()
                    extended_seconds += diff
                    if diff > 0: is_overtime_today = True
            else:
                if calc_end > standard_end:
                    start_calc = max(in_dt, standard_end)
                    if calc_end > start_calc:
                        diff = (calc_end - start_calc).total_seconds()
                        extended_seconds += diff
                        if diff > 0: is_overtime_today = True
            
            # ✅ [추가] 오늘 연장 근무가 있었으면 일수 +1
            if is_overtime_today:
                overtime_days_count += 1
                        
        except:
            continue

    def sec_to_hm(sec):
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        return f"{h}h {m}m"

    return {
        'late_count': late_count,
        'extended_str': sec_to_hm(extended_seconds),
        'night_str': sec_to_hm(night_seconds),
        'overtime_days': overtime_days_count  # ✅ 계산된 일수 반환
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
# ✅ [헬퍼 함수] 특정 년/월의 랜덤 근태 기록 생성 (데이터가 없을 때만 동작)
# ✅ [수정됨] 근태 데이터 생성/보정 함수
def ensure_monthly_dummy_data(year, month):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    # 1. 직원 목록 가져오기
    employees = cursor.execute("SELECT id FROM employees").fetchall()
    _, last_day = calendar.monthrange(year, month)
    
    start_date_str = f"{year}-{month:02d}-01"
    end_date_str = f"{year}-{month:02d}-{last_day}"

    for emp in employees:
        emp_id = emp[0]
        
        # 2. 해당 직원의 이번 달 기록이 있는지 확인
        records = cursor.execute("""
            SELECT count(*), 
                   SUM(CASE WHEN clock_out_time > '18:00:00' THEN 1 ELSE 0 END) as ov_cnt 
            FROM attendance 
            WHERE employee_id = ? AND record_date BETWEEN ? AND ?
        """, (emp_id, start_date_str, end_date_str)).fetchone()
        
        has_records = records[0] > 0
        overtime_count = records[1] if records[1] else 0

        # 3. 기록이 아예 없으면 -> 전체 신규 생성
        # 4. 기록은 있는데 초과근무가 너무 적으면(0회) -> 기존 기록을 UPDATE해서 야근 추가!
        
        # (A) 신규 생성 모드
        if not has_records:
            # 직원별 성향 (야근 확률 높임: 10% ~ 60%)
            overtime_prob = random.randint(10, 60)
            late_prob = random.randint(0, 15) 
            absent_prob = random.randint(0, 3)

            for day in range(1, last_day + 1):
                current_date = datetime(year, month, day)
                if current_date.weekday() >= 5: continue # 주말 제외
                
                date_str = current_date.strftime("%Y-%m-%d")
                rand = random.randint(1, 100)
                
                status = '정상'
                in_time = f"08:{random.randint(30, 59)}:00"
                out_time = f"18:{random.randint(0, 30):02d}:00" # 기본 칼퇴

                # 결근/지각 로직
                if rand <= absent_prob:
                    status = '결근'; in_time = None; out_time = None
                elif rand <= (absent_prob + late_prob):
                    status = '지각'
                    in_time = f"09:{random.randint(1, 59):02d}:00"
                
                # 초과 근무 로직 (결근 아닐 때)
                if status != '결근':
                    # 야근 당첨!
                    if random.randint(1, 100) <= overtime_prob:
                        # 19시 ~ 22시 사이 퇴근 (1~4시간 야근)
                        ov_h = random.randint(19, 22)
                        ov_m = random.randint(0, 55)
                        out_time = f"{ov_h}:{ov_m:02d}:00"

                if in_time:
                    cursor.execute("INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status) VALUES (?,?,?,?,?)", 
                                   (emp_id, date_str, in_time, out_time, status))
                else:
                    cursor.execute("INSERT INTO attendance (employee_id, record_date, attendance_status) VALUES (?,?,?)", 
                                   (emp_id, date_str, status))

        # (B) 보정 모드: 기록은 있는데 야근이 0회인 경우 -> 강제로 몇 개 수정
        elif overtime_count == 0:
            # 이 직원은 이번 달 야근을 2~7회 정도 강제로 시킴
            force_overtime_days = random.randint(2, 7)
            
            # 이번 달 평일 날짜들을 가져옴
            existing_dates = cursor.execute("""
                SELECT record_date FROM attendance 
                WHERE employee_id = ? AND record_date BETWEEN ? AND ? AND attendance_status != '결근'
            """, (emp_id, start_date_str, end_date_str)).fetchall()
            
            if existing_dates:
                # 랜덤으로 날짜 몇 개 뽑기
                target_days = random.sample(existing_dates, k=min(len(existing_dates), force_overtime_days))
                
                for row in target_days:
                    r_date = row[0]
                    # 19:00 ~ 23:00 사이로 퇴근 시간 수정
                    new_h = random.randint(19, 22)
                    new_m = random.randint(0, 59)
                    new_out = f"{new_h}:{new_m:02d}:00"
                    
                    cursor.execute("""
                        UPDATE attendance SET clock_out_time = ? 
                        WHERE employee_id = ? AND record_date = ?
                    """, (new_out, emp_id, r_date))

    conn.commit()
    conn.close()

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
        except: return value 
    if value is None: return ""
    
    # [수정] 'now'일 경우 모의 시간 사용
    if value == 'now': 
        value = get_mock_now()
        
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
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']
        
        conn = sqlite3.connect('employees.db')
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        
        # 1. 사용자 정보 조회 (이름을 얻기 위해 employees 테이블과 조인)
        # ✅ 여기서 'user' 변수를 정의합니다. (이 부분이 없어서 에러가 난 것)
        cursor.execute("""
            SELECT u.*, e.name, e.id as emp_id 
            FROM users u
            JOIN employees e ON u.employee_id = e.id
            WHERE u.username = ?
        """, (username,))
        
        user = cursor.fetchone() # DB에서 가져온 정보를 'user' 변수에 담음
        
        conn.close()

        # 2. 비밀번호 확인 및 로그인 처리
        if user and check_password_hash(user['password_hash'], password):
            session.clear()
            session['user_id'] = user['emp_id']
            session.permanent = True # 30분 자동 로그아웃 설정
            
            # ✅ 이제 'user' 변수가 존재하므로 에러가 나지 않습니다.
            log_activity('LOGIN', '보안', f"{user['name']}({user['emp_id']}) 로그인 성공")
            
            return redirect(url_for('dashboard'))
            
        else:
            flash('아이디 또는 비밀번호가 올바르지 않습니다.', 'error')
            # 로그인 실패 로그 (선택 사항)
            # log_activity('LOGIN_FAIL', '보안', f"로그인 실패: {username}")
            
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.clear()
    flash("로그아웃되었습니다.", "success")
    return redirect(url_for('login'))
# ==========================================
# [보안] 세션 연장 (자동 로그아웃 방지)
# ==========================================
@app.route('/extend_session', methods=['POST'])
@login_required
def extend_session():
    session.modified = True  # 세션을 갱신하여 시간 초기화
    return jsonify({"status": "success", "msg": "세션이 30분 연장되었습니다."})
from datetime import datetime # (파일 상단에 필수)

@app.route('/dashboard')
@login_required
def dashboard():
    employee_id = g.user['id']
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # ✅ [수정 1] 가짜 시간(Mock) 삭제 -> 실제 현재 시간 사용
    now = datetime.now() 
    year = now.year
    month = now.month
    today_day = now.day
    today_str = now.strftime('%Y-%m-%d')
    
    # (화면 처음 켤 때 보여줄 현재 시간 문자열 - 예: "14:25:30")
    current_time_str = now.strftime('%H:%M:%S')

    # 2. 근태 현황 통계 (로직 동일)
    all_attendance = cursor.execute("SELECT attendance_status, clock_out_time FROM attendance WHERE record_date = ?", (today_str,)).fetchall()
    
    status_counts = {'출근': 0, '휴가': 0, '외근/출장': 0, '부재': 0, '재실_상세': 0, '퇴근_상세': 0}
    
    recorded_ids = []
    for row in all_attendance:
        status = row['attendance_status']
        if status in ['정상', '지각']:
            status_counts['출근'] += 1
            if row['clock_out_time']: status_counts['퇴근_상세'] += 1
            else: status_counts['재실_상세'] += 1
        elif status == '휴가': status_counts['휴가'] += 1
        elif status in ['외근', '출장']: status_counts['외근/출장'] += 1
        else: status_counts['부재'] += 1
    
    total_emp = cursor.execute("SELECT COUNT(*) FROM employees WHERE status='재직' AND id != 'admin'").fetchone()[0]
    recorded_count = len(all_attendance)
    status_counts['부재'] += (total_emp - recorded_count)

    # 3. 달력 데이터
    month_calendar = calendar.monthcalendar(year, month)
    events = {}
    events[25] = "💰 월급날"
    if month == 12: events[25] = "🎄 성탄절 / 💰 월급날"
    elif month == 1: events[1] = "🌅 신정"

    # 4. 공지사항
    notices = cursor.execute("SELECT * FROM notices ORDER BY created_at DESC LIMIT 5").fetchall()

    # 5. 나의 오늘 근태 정보
    today_attendance = cursor.execute("SELECT * FROM attendance WHERE employee_id = ? AND record_date = ?", (employee_id, today_str)).fetchone()

    # 6. 부서별 통계
    dept_stats = cursor.execute("SELECT department, COUNT(*) as cnt FROM employees WHERE status='재직' AND id != 'admin' GROUP BY department").fetchall()
    dept_labels = [row['department'] for row in dept_stats]
    dept_counts = [row['cnt'] for row in dept_stats]

    # 7. 날씨 정보 (API 연동 유지)
    weather_data = None
    API_KEY = "d5d02c8ce25a904d5dd64a317fba7f14"
    LAT = "37.584649"
    LON = "126.925693"
    
    try:
        url = f"http://api.openweathermap.org/data/2.5/weather?lat={LAT}&lon={LON}&appid={API_KEY}&units=metric&lang=kr"
        response = requests.get(url, timeout=3)
        if response.status_code == 200:
            data = response.json()
            weather_data = {
                'temp': round(data['main']['temp'], 1),
                'desc': data['weather'][0]['description'],
                'icon': data['weather'][0]['icon']
            }
    except Exception as e:
        print(f"날씨 API 호출 에러: {e}")

    if not weather_data:
        weather_data = {'temp': 22.5, 'desc': '맑음(데이터 없음)', 'icon': '01d'}

    conn.close()

    return render_template('dashboard.html', 
                           status_counts=status_counts,
                           total_employees_count=total_emp,
                           month_calendar=month_calendar,
                           events=events,
                           current_month=month,
                           today_day=today_day,
                           notices=notices,
                           dept_labels=dept_labels,
                           dept_counts=dept_counts,
                           today_attendance=today_attendance,
                           weather=weather_data,
                           server_time=current_time_str) # ✅ [수정 2] 서버 시간을 HTML로 넘겨줌
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
    now = get_mock_now()
    
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
    
    # 1. 필터링 파라미터
    id_q = request.args.get('id', '')
    name_q = request.args.get('name', '')
    dept_q = request.args.get('department', '')
    pos_q = request.args.get('position', '')
    status_q = request.args.get('status', '')

    # 2. 날짜 기준 (모의 날짜 12월 11일)
    mock_now = get_mock_now()
    query_date = request.args.get('date') or mock_now.strftime('%Y-%m-%d')

    sql = """
        SELECT e.id, e.name, e.department, e.position, 
               a.clock_in_time, a.clock_out_time, 
               COALESCE(a.attendance_status, '부재') as status
        FROM employees e
        LEFT JOIN attendance a ON e.id = a.employee_id AND a.record_date = ?
        WHERE e.status = '재직' AND e.id != 'admin'
    """
    
    params = [query_date]
    if id_q: sql += " AND e.id LIKE ?"; params.append(f"%{id_q}%")
    if name_q: sql += " AND e.name LIKE ?"; params.append(f"%{name_q}%")
    if dept_q: sql += " AND e.department = ?"; params.append(dept_q)
    if pos_q: sql += " AND e.position = ?"; params.append(pos_q)
    sql += " ORDER BY e.id ASC"
    
    rows = cursor.execute(sql, params).fetchall()
    
    employees = []
    
    # ✅ [핵심 수정] 딕셔너리 초기화 시 '재실_상세', '퇴근_상세'를 꼭 넣어야 합니다!
    counts = {
        '출근': 0, 
        '재실_상세': 0, 
        '퇴근_상세': 0, 
        '휴가': 0, 
        '외근/출장': 0, 
        '부재': 0
    }
    
    for row in rows:
        d = dict(row)
        
        # 1. DB 상태 가져오기
        db_status = d.get('status')
        
        # 2. 화면 표시용 상태 결정 (우선순위 로직)
        if d['clock_out_time']: 
            d['status'] = '퇴근'
        elif db_status in ['외근', '출장']: 
            d['status'] = db_status
        elif db_status == '지각':         
            d['status'] = '지각'
        elif d['clock_in_time']:          
            d['status'] = '재실'
        else:
            d['status'] = db_status       

        # 3. 통계 카운트 집계
        s = d['status']
        
        # (1) 출근 (재실 + 퇴근 + 지각)
        if s in ['재실', '퇴근', '지각']: 
            counts['출근'] += 1
            if s == '재실' or s == '지각': 
                counts['재실_상세'] += 1 # ✅ 이제 에러 안 남
            else: 
                counts['퇴근_상세'] += 1
            
        # (2) 휴가
        elif s == '휴가': 
            counts['휴가'] += 1
            
        # (3) 외근/출장
        elif s in ['외근', '출장']: 
            counts['외근/출장'] += 1
            
        # (4) 부재
        else: 
            counts['부재'] += 1
            
        d['check_in'] = d['clock_in_time'][:5] if d['clock_in_time'] else '-'
        d['check_out'] = d['clock_out_time'][:5] if d['clock_out_time'] else '-'

        if status_q and status_q != '-- 전체 --' and s != status_q: continue
        employees.append(d)

    # 3. 휴가 요청 (페이지네이션)
    page = request.args.get('page', 1, type=int)
    per_page = 3
    offset = (page - 1) * per_page
    
    cursor.execute("SELECT COUNT(*) FROM vacation_requests WHERE status IN ('대기','승인','반려')")
    total_req_count = cursor.fetchone()[0]
    total_pages = math.ceil(total_req_count / per_page)

    cursor.execute("SELECT * FROM vacation_requests WHERE status IN ('대기','승인','반려') ORDER BY request_date DESC LIMIT ? OFFSET ?", (per_page, offset))
    reqs = cursor.fetchall()
    
    # 4. 드롭다운 데이터
    depts = [r[0] for r in cursor.execute("SELECT name FROM departments ORDER BY name").fetchall()]
    pos = [r[0] for r in cursor.execute("SELECT name FROM positions").fetchall()]
    
    conn.close()
    
    return render_template('attendance_page.html', 
                           employees=employees, 
                           status_counts=counts, 
                           vacation_requests=reqs, 
                           total_employees_count=len(employees), 
                           departments=depts, 
                           positions=pos,
                           current_page=page, 
                           total_pages=total_pages)

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

# ==========================================
# [필수] 도우미 함수들 (my_attendance 실행을 위해 필요)
# ==========================================
def get_mock_now():
    from datetime import datetime
    return datetime.now()

def calculate_work_duration(t1_str, t2_str):
    if not t1_str or not t2_str: return '-'
    try:
        from datetime import datetime
        t1 = datetime.strptime(t1_str, "%H:%M:%S")
        t2 = datetime.strptime(t2_str, "%H:%M:%S")
        diff = t2 - t1
        hours = diff.seconds // 3600
        mins = (diff.seconds % 3600) // 60
        return f"{hours}시간 {mins}분"
    except: return '-'

def get_today_attendance(user_id):
    from datetime import datetime
    today = datetime.now().strftime("%Y-%m-%d")
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    row = cursor.execute("SELECT * FROM attendance WHERE employee_id=? AND record_date=?", (user_id, today)).fetchone()
    conn.close()
    return dict(row) if row else None

def calculate_monthly_stats(user_id, year, month):
    # 간단한 통계 계산 로직
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    rows = cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? 
        AND strftime('%Y', record_date) = ? 
        AND strftime('%m', record_date) = ?
    """, (user_id, str(year), f"{month:02d}")).fetchall()
    
    late = 0
    ext = 0
    night = 0
    
    for r in rows:
        if r['attendance_status'] == '지각': late += 1
        # 퇴근 시간이 있고 19시 넘으면 연장, 22시 넘으면 야간 (예시 로직)
        if r['clock_out_time']:
            if r['clock_out_time'] > '19:00:00': ext += 1
            if r['clock_out_time'] > '22:00:00': night += 1
            
    conn.close()
    return {'late_count': late, 'extended_str': f"{ext}회", 'night_str': f"{night}회"}

# ==========================================
# [라우트] 나의 근태 현황 (사용자님이 원하시는 코드)
# ==========================================
@app.route('/my_attendance')
@login_required
def my_attendance():
    import calendar
    from datetime import datetime, timedelta

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. 날짜 설정
    today = datetime.now()
    try:
        year = request.args.get('year', today.year, type=int)
        month = request.args.get('month', today.month, type=int)
    except:
        year = today.year
        month = today.month

    # 2. 조회 범위
    last_day = calendar.monthrange(year, month)[1]
    default_start = f"{year}-{month:02d}-01"
    default_end = f"{year}-{month:02d}-{last_day}"
    
    # 3. 필터
    start_date_filter = request.args.get('start_date') or default_start
    end_date_filter = request.args.get('end_date') or default_end
    status_filter = request.args.get('status_filter')

    # 4. DB 조회
    sql = "SELECT * FROM attendance WHERE employee_id = ? AND record_date BETWEEN ? AND ?"
    params = [g.user['id'], start_date_filter, end_date_filter]
    
    if status_filter:
        sql += " AND attendance_status = ?"
        params.append(status_filter)
        
    sql += " ORDER BY record_date DESC"
    
    rows = cur.execute(sql, params).fetchall()
    
    # 5. 데이터 가공
    attendance_records = []
    daily_attendance = {}
    
    cnt_late = 0
    cnt_extended = 0
    cnt_night = 0
    sec_extended = 0
    sec_night = 0

    for r in rows:
        d = dict(r)
        cin = d['clock_in_time'][:5] if d['clock_in_time'] else '-'
        cout = d['clock_out_time'][:5] if d['clock_out_time'] else '-'
        
        duration = '-'
        if d['clock_in_time'] and d['clock_out_time']:
            try:
                t_in = datetime.strptime(d['clock_in_time'], "%H:%M:%S")
                t_out = datetime.strptime(d['clock_out_time'], "%H:%M:%S")
                diff = t_out - t_in
                duration = f"{diff.seconds // 3600}시간 {(diff.seconds % 3600) // 60}분"
                
                base_19 = t_out.replace(hour=19, minute=0, second=0)
                base_22 = t_out.replace(hour=22, minute=0, second=0)
                
                if t_out > base_19:
                    cnt_extended += 1
                    sec_extended += (t_out - base_19).seconds
                if t_out > base_22:
                    cnt_night += 1
                    sec_night += (t_out - base_22).seconds
            except: pass

        attendance_records.append({
            'date': d['record_date'],
            'clock_in': cin, 'clock_out': cout, 'duration': duration,
            'status': d['attendance_status'], 'note': d['note']
        })
        
        try:
            r_date = datetime.strptime(d['record_date'], '%Y-%m-%d')
            if r_date.year == year and r_date.month == month:
                day_int = r_date.day
                css = 'status-normal'
                if d['attendance_status'] == '지각': css = 'status-late'; cnt_late += 1
                elif d['attendance_status'] == '휴가': css = 'status-leave'
                elif d['attendance_status'] in ['결근', '부재']: css = 'status-absent'
                
                daily_attendance[day_int] = {
                    'status': d['attendance_status'],
                    'clock_in': cin, 'clock_out': cout,
                    'css_class': css, 'note': d['note']
                }
        except: continue

    conn.close()

    # 6. 달력 구조 생성 (✅ 일요일 시작으로 수정됨!)
    cal = calendar.Calendar(firstweekday=6).monthdayscalendar(year, month)
    
    # 7. 통계 텍스트
    def format_time(seconds):
        if seconds <= 0: return ""
        h = seconds // 3600
        m = (seconds % 3600) // 60
        return f"({h}시간 {m}분)"

    str_extended = f"{cnt_extended}회"
    if cnt_extended > 0: str_extended += f" <br><span style='font-size:0.6em; color:#888;'>{format_time(sec_extended)}</span>"

    str_night = f"{cnt_night}회"
    if cnt_night > 0: str_night += f" <br><span style='font-size:0.6em; color:#888;'>{format_time(sec_night)}</span>"

    monthly_stats = {
        'remaining_leave': 12.0,
        'late_count': cnt_late,
        'extended_work': str_extended,
        'night_work': str_night
    }

    return render_template('my_attendance.html',
                           attendance_records=attendance_records,
                           month_calendar=cal,
                           daily_attendance=daily_attendance,
                           current_year=year,
                           current_month=month,
                           current_month_name=f"{year}년 {month}월",
                           monthly_stats=monthly_stats,
                           start_date_filter=start_date_filter,
                           end_date_filter=end_date_filter,
                           status_filter_value=status_filter,
                           events=[])


# ==========================================
# [관리자] 근태 요청 상태 변경 (이름 변경됨: process_request -> admin_process_request)
# ==========================================
# ✅ URL도 겹치지 않게 /admin/... 을 앞에 붙였습니다.
@app.route('/admin/process_request/<int:request_id>/<action>', methods=['POST'])
@login_required
def admin_process_request(request_id, action):  # ✅ 함수 이름 변경!
    # 관리자 체크 (필요시 주석 해제)
    # if g.user['role'] != 'admin':
    #     return redirect(url_for('dashboard'))

    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        new_status = ''
        msg = ''
        
        if action == 'approve':
            new_status = '승인'
            msg = '요청이 [승인] 처리되었습니다.'
        elif action == 'reject':
            new_status = '반려'
            msg = '요청이 [반려] 처리되었습니다.'
        elif action == 'reset':  
            new_status = '대기'
            msg = '요청이 [대기] 상태로 복구되었습니다.'
        
        cursor.execute("""
            UPDATE vacation_requests 
            SET status = ? 
            WHERE id = ?
        """, (new_status, request_id))
        
        conn.commit()
        flash(msg, 'success')
        
    except Exception as e:
        conn.rollback()
        print(f"Error processing request: {e}")
        flash(f"처리 중 오류 발생: {e}", 'error')
        
    finally:
        conn.close()
        
    return redirect(url_for('attendance_request'))
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
@login_required
def attendance_employee():
    # 1. 파라미터 받기 (기본값: 현재 년/월)
    now = datetime.now()
    try:
        current_year = int(request.args.get('year', now.year))
        current_month = int(request.args.get('month', now.month))
    except:
        current_year = now.year
        current_month = now.month

    # ✅ [핵심] 해당 월의 데이터가 없거나 부족하면 생성/보정하는 함수 호출
    # (이 함수는 app.py 상단에 정의되어 있어야 합니다)
    ensure_monthly_dummy_data(current_year, current_month)

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. 검색 필터 값 받기
    id_query = request.args.get('id_query', '')
    name_query = request.args.get('name_query', '')
    dept_query = request.args.get('department_query', '')
    pos_query = request.args.get('position_query', '')
    
    # 3. 메인 쿼리 작성
    # - 지각/결근: 횟수 카운트
    # - 초과근무: 18:00 이후 퇴근 시간을 '초(Second)' 단위로 합산
    query = f"""
        SELECT 
            e.id, e.name, e.department, e.position,
            (
                SELECT COUNT(*) FROM attendance a 
                WHERE a.employee_id = e.id 
                  AND strftime('%Y-%m', a.record_date) = '{current_year}-{current_month:02d}'
                  AND a.attendance_status = '지각'
            ) as late_count,
            (
                SELECT COUNT(*) FROM attendance a 
                WHERE a.employee_id = e.id 
                  AND strftime('%Y-%m', a.record_date) = '{current_year}-{current_month:02d}'
                  AND a.attendance_status = '결근'
            ) as absence_count,
            (
                SELECT IFNULL(SUM(
                    (strftime('%s', a.clock_out_time) - strftime('%s', '18:00:00'))
                ), 0)
                FROM attendance a 
                WHERE a.employee_id = e.id 
                  AND strftime('%Y-%m', a.record_date) = '{current_year}-{current_month:02d}'
                  AND a.clock_out_time > '18:00:00'
            ) as overtime_seconds
        FROM employees e
        WHERE 1=1
    """
    
    params = []
    
    # 4. 검색 조건 적용
    if id_query:
        query += " AND e.id LIKE ?"
        params.append(f"%{id_query}%")
    if name_query:
        query += " AND e.name LIKE ?"
        params.append(f"%{name_query}%")
    if dept_query:
        query += " AND e.department = ?"
        params.append(dept_query)
    if pos_query:
        query += " AND e.position = ?"
        params.append(pos_query)

    employees = cursor.execute(query, params).fetchall()
    
    result_list = []
    
    # 추가 필터링 값 가져오기
    leave_filter = request.args.get('leave_filter')
    late_absent_filter = request.args.get('late_absent_filter')
    overtime_filter = request.args.get('overtime_filter')

    # 5. 데이터 가공 및 파이썬 레벨 필터링
    for emp in employees:
        # 잔여 연차 (시드 고정 랜덤)
        random.seed(f"{emp['id']}_{current_year}") 
        remaining_leave = random.randint(0, 15)
        
        # 초과근무 시간 포맷팅 (초 -> A시간 B분)
        total_seconds = emp['overtime_seconds']
        hours = int(total_seconds // 3600)
        minutes = int((total_seconds % 3600) // 60)
        
        # 필터링 비교용 시간(숫자)
        ot_hours_numeric = round(total_seconds / 3600, 1)

        # 화면 표시용 문자열 생성
        if hours > 0 and minutes > 0:
            formatted_overtime = f"{hours}시간 {minutes}분"
        elif hours > 0:
            formatted_overtime = f"{hours}시간"
        else:
            formatted_overtime = f"{minutes}분" if minutes > 0 else "0시간"

        late_cnt = emp['late_count']
        absent_cnt = emp['absence_count']
        
        # 필터링 로직 (조건에 안 맞으면 건너뜀)
        if leave_filter and remaining_leave < int(leave_filter): continue
        if late_absent_filter and (late_cnt + absent_cnt) < int(late_absent_filter): continue
        if overtime_filter and ot_hours_numeric < int(overtime_filter): continue
        
        result_list.append({
            'id': emp['id'],
            'name': emp['name'],
            'department': emp['department'],
            'position': emp['position'],
            'remaining_leave': remaining_leave,
            'late_count': late_cnt,
            'absence_count': absent_cnt,
            'overtime_hours': formatted_overtime # ✅ 문자열(예: "4시간 30분")로 전달
        })

    # 6. 드롭다운 메뉴 채우기
    depts = [r[0] for r in cursor.execute("SELECT DISTINCT department FROM employees").fetchall()]
    positions = [r[0] for r in cursor.execute("SELECT DISTINCT position FROM employees").fetchall()]
    
    conn.close()
    
    return render_template('attendance_employee.html', 
                           employee_stats=result_list, 
                           current_year=current_year, 
                           current_month=current_month,
                           departments=depts,
                           positions=positions)

@app.route('/attendance_employee_detail/<employee_id>')
@login_required
def attendance_employee_detail(employee_id):
    import calendar # 상단에 import가 없다면 여기서라도 로드

    # 1. 파라미터 받기 (기본값: 현재 년/월)
    try:
        now = datetime.now()
        year = int(request.args.get('year', now.year))
        month = int(request.args.get('month', now.month))
        source = request.args.get('source', 'employee_list')
    except:
        year = datetime.now().year
        month = datetime.now().month
        source = 'employee_list'

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 2. 직원 정보 조회
    target_user = cursor.execute("SELECT * FROM employees WHERE id = ?", (employee_id,)).fetchone()
    if not target_user:
        conn.close()
        return "<p>직원 정보를 찾을 수 없습니다.</p>"

    # 3. [월간] 데이터 조회 (달력 및 월간 통계용)
    start_date = f"{year}-{month:02d}-01"
    end_date = f"{year}-{month:02d}-31"
    
    monthly_records = cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? AND record_date BETWEEN ? AND ?
        ORDER BY record_date ASC
    """, (employee_id, start_date, end_date)).fetchall()

    # 4. [연간] 데이터 조회 (누적 통계용)
    yearly_records = cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? AND strftime('%Y', record_date) = ?
    """, (employee_id, str(year))).fetchall()
    
    conn.close()

    # 5. [헬퍼 함수] 초(Seconds) -> "A시간 B분" 변환
    def fmt_time(seconds):
        if seconds == 0: return "0시간"
        h = seconds // 3600
        m = (seconds % 3600) // 60
        if h > 0 and m > 0:
            return f"{h}시간 {m}분"
        elif h > 0:
            return f"{h}시간"
        else:
            return f"{m}분"

    # 6. 통계 계산 로직
    
    # (A) 월간 통계 계산
    m_stats = {'late': 0, 'absent': 0, 'out': 0, 'trip': 0, 'leave': 0, 'ov_days': 0, 'ov_sec': 0}
    daily_attendance = {} # 달력 매핑용

    for rec in monthly_records:
        st = rec['attendance_status']
        
        # 상태 카운트
        if st == '지각': m_stats['late'] += 1
        elif st == '결근': m_stats['absent'] += 1
        elif st == '외근': m_stats['out'] += 1
        elif st == '출장': m_stats['trip'] += 1
        elif st == '휴가': m_stats['leave'] += 1

        # 초과 근무 (18시 이후 퇴근) 누적
        if rec['clock_out_time'] and rec['clock_out_time'] > '18:00:00':
            m_stats['ov_days'] += 1
            try:
                out_dt = datetime.strptime(rec['clock_out_time'], "%H:%M:%S")
                std_dt = datetime.strptime("18:00:00", "%H:%M:%S")
                m_stats['ov_sec'] += (out_dt - std_dt).seconds
            except: pass

        # 달력 표시용 데이터 가공
        try:
            day_num = int(rec['record_date'].split('-')[2])
            css_class = 'status-normal'
            if st == '지각': css_class = 'status-late'
            elif st == '결근': css_class = 'status-absent'
            elif st == '휴가': css_class = 'status-leave'
            
            cin = rec['clock_in_time'][:5] if rec['clock_in_time'] else ''
            cout = rec['clock_out_time'][:5] if rec['clock_out_time'] else ''
            
            daily_attendance[day_num] = {
                'status': st, 'clock_in': cin, 'clock_out': cout, 'css_class': css_class
            }
        except: pass

    # (B) 연간 통계 계산
    y_stats = {'late': 0, 'absent': 0, 'out': 0, 'trip': 0, 'leave': 0, 'ov_days': 0, 'ov_sec': 0}

    for rec in yearly_records:
        st = rec['attendance_status']
        if st == '지각': y_stats['late'] += 1
        elif st == '결근': y_stats['absent'] += 1
        elif st == '외근': y_stats['out'] += 1
        elif st == '출장': y_stats['trip'] += 1
        elif st == '휴가': y_stats['leave'] += 1

        if rec['clock_out_time'] and rec['clock_out_time'] > '18:00:00':
            y_stats['ov_days'] += 1
            try:
                out_dt = datetime.strptime(rec['clock_out_time'], "%H:%M:%S")
                std_dt = datetime.strptime("18:00:00", "%H:%M:%S")
                y_stats['ov_sec'] += (out_dt - std_dt).seconds
            except: pass

    # (C) 잔여 연차 (랜덤 고정)
    # 리스트 화면과 동일한 시드 사용 -> 동일한 값 보장
    random.seed(f"{target_user['id']}_{year}")
    remaining_leave = random.randint(0, 15)

    # 7. 템플릿 변수 구성
    
    # [상단 요약용 간단 통계]
    stats = {
        'late': m_stats['late'],
        'absent': m_stats['absent'],
        'remaining_leave': remaining_leave,
        'overtime_count': m_stats['ov_days'],
        'overtime_hours': fmt_time(m_stats['ov_sec']) # "A시간 B분"
    }
    
    # [모달 내부 탭용 상세 통계]
    summary = {
        'target_month': f"{year}년 {month}월",
        'target_year': year,
        'monthly': {
            'tardy_count': m_stats['late'],
            'absent_count': m_stats['absent'],
            'offsite_days': m_stats['out'],
            'business_trip_days': m_stats['trip'],
            'leave_days': m_stats['leave'],
            'overtime_days_count': m_stats['ov_days'],
            'overtime_hours': fmt_time(m_stats['ov_sec'])
        },
        'yearly': {
            'tardy_count': y_stats['late'],
            'absent_count': y_stats['absent'],
            'offsite_days': y_stats['out'],
            'business_trip_days': y_stats['trip'],
            'leave_days': y_stats['leave'],
            'remaining_leave': remaining_leave,
            'overtime_days_count': y_stats['ov_days'],
            'overtime_hours': fmt_time(y_stats['ov_sec'])
        }
    }

    # 달력 데이터 생성
    cal = calendar.Calendar(firstweekday=6)
    month_calendar = cal.monthdayscalendar(year, month)

    return render_template('attendance_employee_detail.html',
                           target_user=target_user,
                           employee=target_user, # 혹시 모를 호환성 위해 추가
                           stats=stats,
                           employee_stats_summary=summary,
                           month_calendar=month_calendar,
                           daily_attendance=daily_attendance,
                           current_year=year,
                           current_month=month,
                           current_month_name=f"{year}년 {month}월",
                           source=source)

# ----------------------------------------------------
# 13. [신규] 관리자 근태 기록 수정 (Admin Update)
# ----------------------------------------------------
@app.route('/attendance/update', methods=['POST'])
@login_required
@admin_required 
def update_attendance():
    employee_id = request.form.get('employee_id')
    record_date = request.form.get('record_date')
    clock_in = request.form.get('clock_in_time')
    clock_out = request.form.get('clock_out_time')
    
    # ✅ [신규] 상태 값 받기
    new_status = request.form.get('attendance_status')

    # 시간 포맷 처리 (빈 문자열이면 None으로 저장)
    # HTML time input은 'HH:MM' 형식이지만 DB는 'HH:MM:SS'를 쓸 수 있으므로 초(:00) 추가
    if clock_in: 
        if len(clock_in) == 5: clock_in += ':00'
    else: clock_in = None
        
    if clock_out:
        if len(clock_out) == 5: clock_out += ':00'
    else: clock_out = None

    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    try:
        # 해당 날짜 기록이 있는지 확인
        cursor.execute("SELECT id FROM attendance WHERE employee_id=? AND record_date=?", (employee_id, record_date))
        row = cursor.fetchone()
        
        if row:
            # ✅ [수정] 상태(status)도 함께 업데이트
            cursor.execute("""
                UPDATE attendance 
                SET clock_in_time=?, clock_out_time=?, attendance_status=? 
                WHERE id=?
            """, (clock_in, clock_out, new_status, row[0]))
        else:
            # 기록 없으면 새로 생성 (거의 없을 케이스지만 안전장치)
            cursor.execute("""
                INSERT INTO attendance (employee_id, record_date, clock_in_time, clock_out_time, attendance_status)
                VALUES (?, ?, ?, ?, ?)
            """, (employee_id, record_date, clock_in, clock_out, new_status))
            
        conn.commit()
        flash("근태 기록이 수정되었습니다.", "success")
        
    except Exception as e:
        conn.rollback()
        flash(f"수정 실패: {e}", "error")
    finally:
        conn.close()
        
    # 원래 페이지로 돌아가기
    return redirect(url_for('attendance'))

# ==========================================
# [근태] 1. 직원 휴가/근무/퇴직 신청 (통합)
# ==========================================
@app.route('/attendance/vacation_request', methods=['GET', 'POST'])
@login_required
def vacation_request():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        form_type = request.form.get('form_type') # vacation, work, resign
        
        # 공통 변수 초기화
        req_type = ""
        start_date = ""
        end_date = ""
        reason = ""
        
        # 1. 휴가 신청일 때
        if form_type == 'vacation':
            req_type = request.form.get('leave_type')
            start_date = request.form.get('start_date')
            end_date = request.form.get('end_date')
            reason = request.form.get('reason')
            
        # 2. 근무 신청일 때 (외근/출장 등)
        elif form_type == 'work':
            req_type = request.form.get('work_type')
            start_date = request.form.get('work_start_date')
            end_date = request.form.get('work_end_date')
            
            # 외근/재택은 종료일이 없으면 시작일과 동일하게
            if not end_date: end_date = start_date
            
            destination = request.form.get('destination', '')
            work_reason = request.form.get('work_reason', '')
            reason = f"[장소: {destination}] {work_reason}" # 사유에 장소 합침

        # 3. 퇴직/휴직 신청일 때
        elif form_type == 'resign':
            req_type = request.form.get('resign_type') # 퇴직 or 휴직
            category = request.form.get('resign_category', '')
            detail = request.form.get('resign_reason', '')
            contact = request.form.get('emergency_contact', '')
            
            start_date = request.form.get('resign_start_date')
            end_date = request.form.get('resign_end_date')
            
            if req_type == '퇴직': end_date = start_date # 퇴직은 당일
            
            reason = f"[{category}] {detail} / 비상연락: {contact}"

        # DB 저장
        try:
            cursor.execute("""
                INSERT INTO vacation_requests (user_id, name, department, request_type, start_date, end_date, reason)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (g.user['id'], g.user['name'], g.user['department'], req_type, start_date, end_date, reason))
            conn.commit()
            
            log_activity('INSERT', '근태', f"{g.user['name']} {req_type} 신청서 제출")
            flash('신청서가 성공적으로 제출되었습니다.', 'success')
            
        except Exception as e:
            conn.rollback()
            flash(f'오류 발생: {e}', 'error')

        return redirect(url_for('vacation_request'))

    # 내 신청 내역 조회
    my_requests = cursor.execute("""
        SELECT * FROM vacation_requests WHERE user_id = ? ORDER BY request_date DESC
    """, (g.user['id'],)).fetchall()
    
    conn.close()
    
    # 오늘 날짜 (서명용)
    today_display = datetime.now().strftime("%Y년 %m월 %d일")
    
    return render_template('vacation_request.html', requests=my_requests, today_display_date=today_display)

# ==========================================
# [근태] 2. 관리자 요청 조회 (대기/완료 분리 + 통계)
# ==========================================
@app.route('/attendance/request_list')
@login_required
@admin_required
def attendance_request():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 1. 대기 중인 목록
    pending_list = cursor.execute("""
        SELECT * FROM vacation_requests WHERE status = '대기' ORDER BY request_date ASC
    """).fetchall()
    
    # 2. 처리 완료된 목록 (승인 or 반려)
    processed_list = cursor.execute("""
        SELECT * FROM vacation_requests WHERE status IN ('승인', '반려') ORDER BY request_date DESC LIMIT 50
    """).fetchall()
    
    # 3. 상단 통계 카운트 계산
    counts = cursor.execute("""
        SELECT 
            COUNT(*) as total,
            SUM(CASE WHEN status='대기' THEN 1 ELSE 0 END) as waiting,
            SUM(CASE WHEN status='승인' THEN 1 ELSE 0 END) as approved,
            SUM(CASE WHEN status='반려' THEN 1 ELSE 0 END) as rejected
        FROM vacation_requests
    """).fetchone()
    
    request_counts = {
        'TOTAL': counts['total'],
        '대기': counts['waiting'],
        '승인': counts['approved'],
        '반려': counts['rejected']
    }
    
    conn.close()
    return render_template('attendance_request.html', 
                           pending_requests=pending_list, 
                           processed_requests=processed_list,
                           request_counts=request_counts)

# ==========================================
# [근태] 3. 요청 상태 변경 처리 (승인/반려/초기화 통합)
# ==========================================
@app.route('/admin/process_request/<int:request_id>/<action>', methods=['POST'])
@login_required
@admin_required
def process_request(request_id, action):
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    req = cursor.execute("SELECT * FROM vacation_requests WHERE id=?", (request_id,)).fetchone()
    if not req:
        flash('존재하지 않는 요청입니다.', 'error')
        return redirect(url_for('attendance_request'))

    try:
        # 1. 승인 처리
        if action == 'approve':
            cursor.execute("UPDATE vacation_requests SET status='승인' WHERE id=?", (request_id,))
            
            # 근태 테이블 반영 로직
            s_date = datetime.strptime(req['start_date'], "%Y-%m-%d")
            e_date = datetime.strptime(req['end_date'], "%Y-%m-%d")
            delta = (e_date - s_date).days
            
            for i in range(delta + 1):
                curr = s_date + timedelta(days=i)
                if curr.weekday() < 5: # 주말 제외
                    curr_str = curr.strftime("%Y-%m-%d")
                    # 기존 기록 삭제 후 덮어쓰기
                    cursor.execute("DELETE FROM attendance WHERE employee_id=? AND record_date=?", (req['user_id'], curr_str))
                    cursor.execute("INSERT INTO attendance (employee_id, record_date, attendance_status, note) VALUES (?, ?, ?, ?)", 
                                   (req['user_id'], curr_str, '휴가', req['request_type']))
                                   
            log_activity('UPDATE', '근태', f"{req['name']} 요청 승인 ({req['request_type']})")
            flash('승인 처리되었습니다.', 'success')

        # 2. 반려 처리
        elif action == 'reject':
            cursor.execute("UPDATE vacation_requests SET status='반려' WHERE id=?", (request_id,))
            
            # (선택) 반려 시 이미 등록된 근태가 있다면 삭제해야 할 수도 있음
            # 여기서는 상태만 변경
            
            log_activity('UPDATE', '근태', f"{req['name']} 요청 반려")
            flash('반려 처리되었습니다.', 'warning')

        # 3. 초기화 (대기로 되돌리기)
        elif action == 'reset':
            cursor.execute("UPDATE vacation_requests SET status='대기' WHERE id=?", (request_id,))
            
            # 승인 취소 시 근태 기록도 삭제
            s_date = datetime.strptime(req['start_date'], "%Y-%m-%d")
            e_date = datetime.strptime(req['end_date'], "%Y-%m-%d")
            delta = (e_date - s_date).days
            for i in range(delta + 1):
                curr = s_date + timedelta(days=i)
                curr_str = curr.strftime("%Y-%m-%d")
                # 해당 기간의 '휴가' 기록 삭제
                cursor.execute("DELETE FROM attendance WHERE employee_id=? AND record_date=? AND attendance_status='휴가'", (req['user_id'], curr_str))

            log_activity('UPDATE', '근태', f"{req['name']} 요청 상태 초기화(대기)")
            flash('대기 상태로 초기화되었습니다.', 'info')

        conn.commit()
        
    except Exception as e:
        conn.rollback()
        flash(f'처리 중 오류 발생: {e}', 'error')
        
    finally:
        conn.close()

    return redirect(url_for('attendance_request'))

# ==========================================
# [근태] 4. 휴가 반려
# ==========================================
@app.route('/attendance/reject/<int:req_id>')
@login_required
@admin_required
def reject_vacation(req_id):
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    cursor.execute("UPDATE vacation_requests SET status='반려' WHERE id=?", (req_id,))
    conn.commit()
    
    # 누구 건지 이름 가져오기 (로그용)
    name = cursor.execute("SELECT name FROM vacation_requests WHERE id=?", (req_id,)).fetchone()[0]
    
    log_activity('UPDATE', '근태', f"{name}님의 휴가 반려 처리")
    flash('휴가 신청이 반려되었습니다.', 'warning')
    
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

@app.route('/add_employee', methods=['GET', 'POST'])
@login_required
@admin_required
def add_employee():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    if request.method == 'POST':
        try:
            # 1. 폼 데이터 수집
            name = request.form['name']
            # emp_id = request.form['employee_id']  <-- ❌ 삭제 (사용자 입력 안 받음)
            
            department_name = request.form['department'] # HTML에서 value가 부서명으로 넘어옴
            position_name = request.form['position']
            hire_date = request.form['hire_date']
            birth_date = request.form['birth_date']
            phone = f"{request.form['phone1']}-{request.form['phone2']}-{request.form['phone3']}"
            email = f"{request.form['email_id']}@{request.form['email_domain']}"
            address = request.form['address']
            gender = request.form['gender']
            
            # 초기 비밀번호 (입력받은 것 사용 or 없으면 1234)
            raw_password = request.form.get('password', '1234')

            has_vehicle = (request.form.get('has_vehicle') == '1')

            # -------------------------------------------------------
            # ✅ [수정] 사번(ID) 자동 생성 로직
            # 형식: {년도2자리}{부서코드}{일련번호4자리} (예: 25HR0001)
            # -------------------------------------------------------
            
            # 1. 입사년도 2자리
            year_prefix = hire_date[2:4] 
            
            # 2. 부서 코드 조회
            dept_row = cursor.execute("SELECT code FROM departments WHERE name=?", (department_name,)).fetchone()
            dept_code = dept_row['code'] if dept_row else 'GEN' # 코드가 없으면 GEN(General)
            
            # 3. 일련번호 생성 (현재 가장 큰 번호 + 1)
            prefix = f"{year_prefix}{dept_code}"
            cursor.execute("SELECT id FROM employees WHERE id LIKE ? ORDER BY id DESC LIMIT 1", (f"{prefix}%",))
            last_id_row = cursor.fetchone()
            
            if last_id_row:
                # 마지막 번호가 있으면 +1 (예: 25HR0005 -> 0005 추출 -> 6)
                last_seq = int(last_id_row['id'][len(prefix):])
                new_seq = last_seq + 1
            else:
                # 없으면 1번부터 시작
                new_seq = 1
                
            # 최종 사번 생성
            emp_id = f"{prefix}{new_seq:04d}" 
            # -------------------------------------------------------

            # 프로필 이미지 처리
            file = request.files['profile_image']
            filename = 'default.jpg'
            if file and file.filename != '':
                filename = secure_filename(file.filename)
                file.save(os.path.join(app.config['UPLOAD_FOLDER'], filename))

            # 3. 직원 기본 정보 저장 (자동 생성된 emp_id 사용)
            cursor.execute("""
                INSERT INTO employees (
                    id, name, department, position, hire_date, birth_date, 
                    phone_number, email, address, gender, profile_image, has_vehicle
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (emp_id, name, department_name, position_name, hire_date, birth_date, phone, email, address, gender, filename, has_vehicle))

            # 4. 사용자 계정 생성
            cursor.execute("INSERT INTO users (employee_id, username, password_hash, role) VALUES (?, ?, ?, ?)", 
                           (emp_id, emp_id, generate_password_hash(raw_password), 'user'))
            # 5. 급여 계약 정보 등록 (기본 연봉 설정)
            # (입력받지 않았으므로 직급별 기본급으로 자동 설정하거나 0으로 초기화)
            # 여기서는 편의상 0원으로 초기화 후 '급여 관리'에서 수정하도록 유도
            cursor.execute("""
                INSERT INTO salary_contracts (employee_id, base_salary, annual_salary, bank_name, account_number) 
                VALUES (?, 0, 0, '', '')
            """, (emp_id,))

            # ---------------------------------------------------------
            # ✅ 6. 수당 자동 등록 로직
            # ---------------------------------------------------------
            
            # (1) 식대: 전 직원 공통 (200,000원)
            cursor.execute("""
                INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable) 
                VALUES (?, ?, ?, ?)
            """, (emp_id, '식대', 200000, 0)) # 비과세

            # (2) 자가운전보조금: 차량 소유자만 (200,000원)
            if has_vehicle:
                cursor.execute("""
                    INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable) 
                    VALUES (?, ?, ?, ?)
                """, (emp_id, '자가운전보조금', 200000, 0)) # 비과세

            # (3) 직책 수당: 과장, 팀장, 관리자만 (300,000원)
            if position_name in ['과장', '팀장', '관리자']:
                cursor.execute("""
                    INSERT INTO fixed_allowances (employee_id, allowance_name, amount, is_taxable) 
                    VALUES (?, ?, ?, ?)
                """, (emp_id, '직책수당', 300000, 1)) # 과세

            conn.commit()
            flash(f"신규 직원 '{name}'님이 성공적으로 등록되었습니다.", "success")
            return redirect(url_for('hr_management'))

        except sqlite3.IntegrityError:
            conn.rollback()
            flash("이미 존재하는 사번이거나 데이터 오류가 발생했습니다.", "error")
        except Exception as e:
            conn.rollback()
            flash(f"등록 중 오류 발생: {str(e)}", "error")

    # GET 요청 시 폼 렌더링 데이터 준비
    departments = cursor.execute("SELECT * FROM departments WHERE is_active=1 ORDER BY name").fetchall()
    positions = cursor.execute("SELECT * FROM positions WHERE is_active=1 ORDER BY id").fetchall() # 직급 순서 중요
    email_domains = cursor.execute("SELECT * FROM email_domains ORDER BY domain").fetchall()
    
    conn.close()
    return render_template('add_employee.html', departments=departments, positions=positions, email_domains=email_domains)

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
            return redirect(url_for('hr_management', open_modal=employee_id))
            
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
# ✅ [수정] has_vehicle 컬럼 추가 조회 (e.has_vehicle)
    sql = """
        SELECT p.*, e.name, e.department, e.position, e.has_vehicle
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

@app.route('/download_salary_excel')
@login_required
def download_salary_excel():
    import openpyxl 
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from io import BytesIO
    from flask import send_file

    year = request.args.get('year')
    month = request.args.get('month')

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 데이터 조회
    query = """
        SELECT 
            s.*, 
            e.name, e.department, e.position, e.has_vehicle
        FROM salary_payments s
        JOIN employees e ON s.employee_id = e.id
        WHERE s.payment_year = ? AND s.payment_month = ?
        ORDER BY e.department, e.position, e.name
    """
    rows = cursor.execute(query, (year, month)).fetchall()
    conn.close()

    # 2. 엑셀 워크북 생성
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = f"{year}년 {month}월 급여대장"

    # --- 스타일 정의 ---
    # 헤더 스타일
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill(start_color="34495E", end_color="34495E", fill_type="solid")
    header_align = Alignment(horizontal="center", vertical="center")
    
    # 테두리 (얇은 선)
    border_style = Border(
        left=Side(style='thin'), right=Side(style='thin'), 
        top=Side(style='thin'), bottom=Side(style='thin')
    )
    
    # 데이터 정렬 스타일
    center_align = Alignment(horizontal="center", vertical="center")
    right_align = Alignment(horizontal="right", vertical="center") # 금액용

    # 3. 헤더 작성
    headers = [
        "사번", "이름", "부서", "직급", 
        "기본급", "식대", "차량유지비", 
        "연장수당", "야간수당", "초과근무계", "기타수당", 
        "지급총액",
        "국민연금", "건강보험", "장기요양", "고용보험", "소득세", "지방세", "기타공제", 
        "공제총액", "실수령액"
    ]

    ws.append(headers)

    # 헤더 스타일 적용
    for col_num, header in enumerate(headers, 1):
        cell = ws.cell(row=1, column=col_num)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_align
        cell.border = border_style

    # 4. 데이터 작성
    for row in rows:
        # 수당 계산
        total_base = row['total_base'] if row['total_base'] else 0
        ext_pay = row['allowance_extended'] if row['allowance_extended'] else 0
        night_pay = row['allowance_night'] if row['allowance_night'] else 0
        overtime_pay = ext_pay + night_pay
        
        total_other = row['allowance_other'] if row['allowance_other'] else 0
        meal_allowance = 200000
        drive_allowance = 200000 if row['has_vehicle'] else 0
        
        real_other = total_other - meal_allowance - drive_allowance
        if real_other < 0: real_other = 0

        total_pay = total_base + (row['total_allowance'] if row['total_allowance'] else 0)

        data = [
            row['employee_id'],
            row['name'],
            row['department'],
            row['position'],
            
            total_base,       
            meal_allowance,     
            drive_allowance,    
            ext_pay,            
            night_pay,          
            overtime_pay,       
            real_other,         
            
            total_pay,          
            
            row['national_pension'],
            row['health_insurance'],
            row['care_insurance'],
            row['employment_insurance'],
            row['income_tax'],
            row['local_tax'],
            row['deduction_other'],
            
            row['total_deduction'],
            row['net_salary']
        ]
        
        ws.append(data)

    # 5. ✅ [핵심] 데이터 셀 서식 적용 (콤마, 정렬, 테두리)
    # iter_rows를 통해 2번째 줄(데이터 시작)부터 끝까지 순회
    for row in ws.iter_rows(min_row=2, max_row=ws.max_row, min_col=1, max_col=len(headers)):
        for cell in row:
            cell.border = border_style  # 모든 셀에 테두리 적용
            
            # 5번째 컬럼(기본급)부터 끝까지는 '금액'이므로 콤마+우측정렬
            if cell.column >= 5: 
                cell.number_format = '#,##0'  # ✅ 엑셀 천단위 콤마 서식
                cell.alignment = right_align
            else:
                # 1~4번째 컬럼(사번~직급)은 텍스트므로 가운데 정렬
                cell.alignment = center_align

    # 6. 열 너비 자동 조정
    for col in ws.columns:
        max_length = 0
        column = col[0].column_letter
        for cell in col:
            try:
                # 콤마가 들어간 길이만큼 공간 확보를 위해 약간 보정
                val_len = len(str(cell.value))
                if cell.number_format == '#,##0': 
                    val_len += (val_len // 3) # 콤마 개수만큼 대략 추가
                
                if val_len > max_length:
                    max_length = val_len
            except:
                pass
        adjusted_width = (max_length + 2) * 1.2
        # 너무 좁으면 최소 10, 너무 넓으면 최대 50
        if adjusted_width < 10: adjusted_width = 10
        if adjusted_width > 50: adjusted_width = 50
            
        ws.column_dimensions[column].width = adjusted_width

    # 7. 파일 전송
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f"급여대장_{year}년_{month}월.xlsx"
    )

@app.route('/salary_contracts', methods=['GET', 'POST'])
@login_required
@admin_required
def salary_contracts():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # 1. 저장(POST) 처리
    if request.method == 'POST':
        emp_id = request.form['employee_id']
        annual_salary = request.form['annual_salary']
        bank_name = request.form['bank_name']
        account_number = request.form['account_number']
        
        try:
            base_salary = int(annual_salary) // 12
        except:
            base_salary = 0

        exist = cursor.execute("SELECT id FROM salary_contracts WHERE employee_id = ?", (emp_id,)).fetchone()
        
        if exist:
            cursor.execute("""
                UPDATE salary_contracts 
                SET annual_salary=?, base_salary=?, bank_name=?, account_number=?, updated_at=datetime('now')
                WHERE employee_id=?
            """, (annual_salary, base_salary, bank_name, account_number, emp_id))
        else:
            cursor.execute("""
                INSERT INTO salary_contracts (employee_id, annual_salary, base_salary, bank_name, account_number, created_at)
                VALUES (?, ?, ?, ?, ?, datetime('now'))
            """, (emp_id, annual_salary, base_salary, bank_name, account_number))
            
        conn.commit()
        flash("계약 정보가 저장되었습니다.", "success")
        
        # 리다이렉트 시 검색 조건 유지
        id_q = request.form.get('current_id_query', '')
        name_q = request.form.get('current_name_query', '')
        
        conn.close()
        return redirect(url_for('salary_contracts', id_query=id_q, name_query=name_q))

    # 2. 조회(GET) 처리
    id_query = request.args.get('id_query', '')
    name_query = request.args.get('name_query', '')
    dept_query = request.args.get('department_query', '')
    pos_query = request.args.get('position_query', '')

    # ✅ [핵심 수정] 관리자(홍길동) 제외 쿼리
    # WHERE 1=1 대신 name != '홍길동'을 기본 조건으로 넣습니다.
    # 만약 아이디로 제외하고 싶다면 e.id != 'admin' 등을 쓰면 됩니다.
    query = """
        SELECT e.id, e.name, e.department, e.position, 
               s.annual_salary, s.base_salary, s.bank_name, s.account_number
        FROM employees e
        LEFT JOIN salary_contracts s ON e.id = s.employee_id
        WHERE e.name != '홍길동'
    """
    params = []

    # 동적 쿼리 추가 (AND로 연결)
    if id_query:
        query += " AND e.id LIKE ?"
        params.append(f"%{id_query}%")
    if name_query:
        query += " AND e.name LIKE ?"
        params.append(f"%{name_query}%")
    if dept_query:
        query += " AND e.department = ?"
        params.append(dept_query)
    if pos_query:
        query += " AND e.position = ?"
        params.append(pos_query)
        
    query += " ORDER BY e.id ASC"

    contracts = cursor.execute(query, params).fetchall()

    # 드롭다운 목록 (관리자는 제외하고 싶은 경우 여기 쿼리도 수정 가능하나, 보통은 둬도 무방함)
    depts = [r[0] for r in cursor.execute("SELECT DISTINCT department FROM employees").fetchall()]
    positions = [r[0] for r in cursor.execute("SELECT DISTINCT position FROM employees").fetchall()]

    conn.close()
    
    return render_template('salary_contracts.html', 
                           contracts=contracts, 
                           departments=depts, 
                           positions=positions)

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
@login_required
@admin_required
def calculate_all_salary():
    import calendar # 달력 모듈 필요

    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    
    # 1. 날짜 설정 (현재 기준)
    now = datetime.now()
    year = now.year
    month = now.month
    payment_date = f"{year}-{month:02d}-10"  # 매월 10일 지급

    try:
        # 2. 4대보험 요율 가져오기
        cur.execute("SELECT * FROM payroll_rates WHERE id = 1")
        rate_row = cur.fetchone()
        
        current_rates = {
            'pension': rate_row['national_pension_rate'],
            'health': rate_row['health_insurance_rate'],
            'care': rate_row['care_insurance_rate'],
            'employment': rate_row['employment_insurance_rate']
        }

        # 3. 기존 데이터 삭제 (재계산 위해)
        cur.execute("DELETE FROM salary_payments WHERE payment_year=? AND payment_month=?", (year, month))
        
        # 4. 재직 중인 직원 조회
        cur.execute("""
            SELECT e.id, e.has_vehicle, s.base_salary 
            FROM employees e
            JOIN salary_contracts s ON e.id = s.employee_id
            WHERE e.status = '재직'
        """)
        employees = cur.fetchall()
        
        count = 0
        
        # 5. 직원별 급여 계산 시작
        for emp in employees:
            emp_id = emp['id']
            base_salary = emp['base_salary'] if emp['base_salary'] else 0
            
            # (1) 고정 수당 합계
            cur.execute("SELECT SUM(amount) FROM fixed_allowances WHERE employee_id=?", (emp_id,))
            allowance_sum = cur.fetchone()[0] or 0
            
            # (2) 비과세액 조회 (식대, 차량 등)
            # 여기서는 편의상 DB에 있는 비과세 항목 합계 + 차량유지비 로직 등을 합산
            cur.execute("SELECT SUM(amount) FROM fixed_allowances WHERE employee_id=? AND is_taxable=0", (emp_id,))
            non_taxable = cur.fetchone()[0] or 0
            
            # 식대/차량유지비 등 별도 계산 로직이 있다면 여기서 non_taxable에 추가
            meal_allowance = 200000 # 예시
            drive_allowance = 200000 if emp['has_vehicle'] else 0
            
            # 총 수당에 식대/차량 포함 (이미 fixed_allowances에 있다면 중복 주의)
            # 여기서는 allowance_sum에 포함되어 있지 않다고 가정하고 더해줍니다.
            # (만약 fixed_allowances 테이블에 이미 식대가 들어있다면 이 부분 조정 필요)
            total_fixed_allowance = allowance_sum + meal_allowance + drive_allowance
            
            # (3) ✨ [핵심 수정] 연장/야간 수당 직접 계산 (DB 컬럼에 맞추기 위해)
            # 해당 월의 근태 기록 조회
            _, last_day = calendar.monthrange(year, month)
            start_date = f"{year}-{month:02d}-01"
            end_date = f"{year}-{month:02d}-{last_day}"
            
            att_records = cur.execute("""
                SELECT clock_out_time FROM attendance 
                WHERE employee_id = ? AND record_date BETWEEN ? AND ?
            """, (emp_id, start_date, end_date)).fetchall()
            
            extended_pay = 0
            night_pay = 0
            hourly_wage = (base_salary + 200000) / 209 # 통상임금(기본급+식대) / 209시간
            
            for att in att_records:
                if att['clock_out_time'] and att['clock_out_time'] > '18:00:00':
                    out_dt = datetime.strptime(att['clock_out_time'], "%H:%M:%S")
                    std_dt = datetime.strptime("18:00:00", "%H:%M:%S")
                    diff_hours = (out_dt - std_dt).seconds / 3600
                    
                    # 연장 (1.5배)
                    extended_pay += (diff_hours * hourly_wage * 1.5)
                    
                    # 야간 (22시 이후 0.5배 추가)
                    if att['clock_out_time'] > '22:00:00':
                        night_dt = datetime.strptime("22:00:00", "%H:%M:%S")
                        night_hours = (out_dt - night_dt).seconds / 3600
                        night_pay += (night_hours * hourly_wage * 0.5)

            # 원 단위 절삭
            extended_pay = int(extended_pay / 10) * 10
            night_pay = int(night_pay / 10) * 10
            
            # (4) 총 급여 합산 (기본급 + 고정수당 + 연장 + 야간)
            total_monthly_income = base_salary + total_fixed_allowance + extended_pay + night_pay
            
            # (5) 공제 계산 (4대보험 + 세금)
            # 비과세액 재조정 (식대, 차량 등은 비과세)
            final_non_taxable = non_taxable + 200000 + (200000 if emp['has_vehicle'] else 0) # 최대 한도 체크 로직은 생략
            
            # 공제 로직 함수 호출 (없으면 아래 약식 로직 사용)
            # deductions = calculate_deductions_logic(...) 대신 직접 계산
            
            national_pension = int(total_monthly_income * (current_rates['pension'] / 100) / 10) * 10
            health_insurance = int(total_monthly_income * (current_rates['health'] / 100) / 10) * 10
            care_insurance = int(health_insurance * (current_rates['care'] / 100) / 10) * 10
            employment_insurance = int(total_monthly_income * (current_rates['employment'] / 100) / 10) * 10
            
            # 소득세 약식 (3%)
            taxable_income = total_monthly_income - final_non_taxable
            income_tax = int(taxable_income * 0.03 / 10) * 10 
            local_tax = int(income_tax * 0.1 / 10) * 10
            
            total_deduction = national_pension + health_insurance + care_insurance + employment_insurance + income_tax + local_tax
            
            # (6) 실수령액
            net_salary = total_monthly_income - total_deduction
            
            # (7) DB 저장 (INSERT)
            # 🚨 [수정] overtime_pay를 빼고 allowance_extended, allowance_night를 넣습니다.
            cur.execute("""
                INSERT INTO salary_payments (
                    employee_id, payment_year, payment_month, payment_date,
                    total_base, total_allowance, 
                    allowance_extended, allowance_night, allowance_other,
                    total_deduction, net_salary, 
                    national_pension, health_insurance, care_insurance, employment_insurance,
                    income_tax, local_tax
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                emp_id, year, month, payment_date,
                base_salary, total_fixed_allowance, 
                extended_pay, night_pay, 0, # allowance_other (기타)
                total_deduction, net_salary,
                national_pension, health_insurance, 
                care_insurance, employment_insurance,
                income_tax, local_tax
            ))
            count += 1
            
        conn.commit()
        # ✅ [추가] 급여 재계산 로그 남기기
        log_activity('UPDATE', '급여', f"{year}년 {month}월 급여 일괄 재계산 수행 (총 {count}명)")
        flash(f"총 {count}명의 급여가 재계산되었습니다. (연장/야간 수당 포함)", "success")
        
    except Exception as e:
        conn.rollback()
        # ✅ [추가] 실패 시에도 에러 로그 남기기
        log_activity('ERROR', '급여', f"급여 재계산 중 오류: {str(e)}")
        flash(f"급여 계산 중 오류 발생: {e}", "error")
    finally:
        conn.close()
        
    return redirect(url_for('salary_payroll'))

@app.route('/my_salary')
@login_required
def my_salary():
    employee_id = g.user['id']
    conn = sqlite3.connect('employees.db'); conn.row_factory = sqlite3.Row; cur = conn.cursor()
    
    # 1. 현재 시간 기준
    now = get_mock_now()
    selected_year = request.args.get('year', now.year, type=int)
    selected_month = request.args.get('month', now.month, type=int)

    # 2. 해당 연/월 급여 내역 조회
    cur.execute("SELECT * FROM salary_payments WHERE employee_id = ? AND payment_year = ? AND payment_month = ?", (employee_id, selected_year, selected_month))
    payment_row = cur.fetchone()
    
    # 3. 계좌 정보 조회
    cur.execute("SELECT * FROM salary_contracts WHERE employee_id = ?", (employee_id,))
    account = cur.fetchone()
    
    # 4. 전체 급여 이력 조회
    history = cur.execute("SELECT * FROM salary_payments WHERE employee_id = ? ORDER BY payment_year DESC, payment_month DESC", (employee_id,)).fetchall()
    fixed_allowances = cur.execute("SELECT * FROM fixed_allowances WHERE employee_id=?", (employee_id,)).fetchall()
    # -----------------------------------------------------------
    # ✅ [핵심 수정] 근태 기반 수당 재계산 (리얼리티 보정)
    # -----------------------------------------------------------
    payment = None
    if payment_row:
        payment = dict(payment_row) # 수정 가능하게 딕셔너리로 변환
        
        # (1) 해당 월의 근태 통계 가져오기
        stats = calculate_monthly_stats(employee_id, selected_year, selected_month)
        
        # (2) 시간 문자열("4h 30m") 파싱 -> 시간 단위(float)로 변환
        def parse_time_str(t_str):
            if not t_str: return 0.0
            try:
                h = int(t_str.split('h')[0])
                m = int(t_str.split('h')[1].split('m')[0])
                return h + (m / 60)
            except: return 0.0

        ext_hours = parse_time_str(stats['extended_str']) # 연장 근무 시간
        night_hours = parse_time_str(stats['night_str'])  # 야간 근무 시간
        
        # (3) 시급 계산 (통상임금 / 209시간)
        hourly_wage = payment['total_base'] / 209
        
        # (4) 수당 계산 (연장 1.5배, 야간 0.5배 가산)
        # 야간은 연장과 겹치므로 보통 0.5배만 가산하지만, 여기서는 단순하게 계산
        calc_ext_pay = int(ext_hours * hourly_wage * 1.5)
        calc_night_pay = int(night_hours * hourly_wage * 0.5) 
        
        # (5) 값 덮어쓰기
        payment['allowance_extended'] = calc_ext_pay
        payment['allowance_night'] = calc_night_pay
        
        # (6) 총 지급액 및 실수령액 재계산
        # 기존 기타수당 + 새로 계산한 연장/야간 수당
        payment['total_allowance'] = payment['allowance_other'] + calc_ext_pay + calc_night_pay
        
        gross = payment['total_base'] + payment['total_allowance']
        payment['net_salary'] = gross - payment['total_deduction'] # 공제는 복잡하니 기존값 유지 (약간의 오차 허용)

    conn.close()
    
    return render_template('my_salary.html', 
                           payment=payment, 
                           account=account, 
                           history=history,
                           fixed_allowances=fixed_allowances, # 템플릿으로 전달
                           selected_year=selected_year,
                           selected_month=selected_month)

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
    
    # 1. 급여 계약 정보
    cursor.execute("SELECT * FROM salary_contracts WHERE employee_id = ?", (employee_id,))
    contract = cursor.fetchone()
    
    # ✅ [핵심 수정] 현재 시간 대신 '모의 시간(12월 11일)' 사용
    now = get_mock_now()
    
    # 2. 이번 달 상세 통계 계산 (헬퍼 함수 사용)
    # calculate_monthly_stats 함수가 연장/야간 시간을 계산해서 줍니다.
    stats = calculate_monthly_stats(employee_id, now.year, now.month)
    
    # 3. DB에서 결근 횟수 등 추가 조회
    current_month_str = now.strftime('%Y-%m')
    current_year_str = now.strftime('%Y')
    
    # 이번 달 결근
    cursor.execute("SELECT COUNT(*) FROM attendance WHERE employee_id=? AND attendance_status='결근' AND strftime('%Y-%m', record_date)=?", (employee_id, current_month_str))
    month_absent = cursor.fetchone()[0]

    # 올해 누적 (지각/결근)
    cursor.execute("SELECT COUNT(CASE WHEN attendance_status='지각' THEN 1 END) as late, COUNT(CASE WHEN attendance_status='결근' THEN 1 END) as absent FROM attendance WHERE employee_id=? AND strftime('%Y', record_date)=?", (employee_id, current_year_str))
    year_row = cursor.fetchone()
    
    # 4. 템플릿으로 보낼 데이터 구성
    monthly_stats = {
        'late_count': stats.get('late_count', 0),
        'absent_count': month_absent,
        
        # 'extended_str'이 없으면 '0회'로 표시
        'overtime_hours': stats.get('extended_str', '0회'),
        
        # ✅ [핵심 수정] 'overtime_days' 키가 없으면 0으로 처리 (KeyError 해결!)
        'overtime_days': stats.get('overtime_days', 0), 
        
        'night_work': stats.get('night_str', '0회')
    }

    yearly_stats = {
        'late_count': year_row['late'],
        'absent_count': year_row['absent'],
        'overtime_hours': '12h 30m', # (올해 누적은 임시 데이터 유지)
        'overtime_days': 5
    }
    
    remaining_leave = 12.0 
    # ✅ [추가] 관리자인 경우 3.0일로 변경
    if g.user['id'] == 'admin':
        remaining_leave = 3.0

    # 5. 근속 기간 계산 (모의 날짜 기준)
    tenure_text = ""
    try:
        hire_date = datetime.strptime(g.user['hire_date'], '%Y-%m-%d')
        diff = relativedelta(now, hire_date) # ✅ now 사용
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
    mock_now = get_mock_now()
    thirty_days_ago = (mock_now - timedelta(days=30)).strftime('%Y-%m-%d')
    
    cursor.execute("""
        SELECT * FROM attendance 
        WHERE employee_id = ? AND record_date >= ?
        ORDER BY record_date DESC
    """, (employee_id, thirty_days_ago))
    attendance_records = cursor.fetchall()

    # 3. 근태 통계 (이번 달 - 12월)
    current_month_str = mock_now.strftime('%Y-%m')
    cursor.execute("""
        SELECT 
            COUNT(CASE WHEN attendance_status='지각' THEN 1 END) as late,
            COUNT(CASE WHEN attendance_status='결근' THEN 1 END) as absent,
            COUNT(CASE WHEN attendance_status='조퇴' THEN 1 END) as early_leave
        FROM attendance 
        WHERE employee_id = ? AND strftime('%Y-%m', record_date) = ?
    """, (employee_id, current_month_str))
    stats = cursor.fetchone()
    
    # -------------------------------------------------------------
    # 4. 올해 누적 초과근무 계산 (및 연출용 고정)
    # -------------------------------------------------------------
    current_year_str = mock_now.strftime('%Y')
    cursor.execute("""
        SELECT record_date, clock_in_time, clock_out_time 
        FROM attendance 
        WHERE employee_id = ? 
          AND strftime('%Y', record_date) = ?
          AND clock_in_time IS NOT NULL 
          AND clock_out_time IS NOT NULL
    """, (employee_id, current_year_str))
    year_records = cursor.fetchall()

    ov_count = 0  
    ov_sec = 0    

    for row in year_records:
        try:
            r_date = datetime.strptime(row['record_date'], '%Y-%m-%d').date()
            t_in = row['clock_in_time']; t_out = row['clock_out_time']
            fmt_in = '%H:%M:%S' if len(t_in) >= 8 else '%H:%M'
            fmt_out = '%H:%M:%S' if len(t_out) >= 8 else '%H:%M'
            in_dt = datetime.combine(r_date, datetime.strptime(t_in, fmt_in).time())
            out_dt = datetime.combine(r_date, datetime.strptime(t_out, fmt_out).time())
            if out_dt < in_dt: out_dt += timedelta(days=1)

            std_end = in_dt.replace(hour=18, minute=0, second=0)
            is_weekend = r_date.weekday() >= 5
            day_ov_sec = 0
            
            if is_weekend: day_ov_sec = (out_dt - in_dt).total_seconds()
            else:
                if out_dt > std_end:
                    calc_start = max(in_dt, std_end)
                    day_ov_sec = (out_dt - calc_start).total_seconds()
            
            if day_ov_sec > 600:
                ov_count += 1
                ov_sec += day_ov_sec
        except: continue

    # 기본 계산 결과 포맷팅
    ov_hours = int(ov_sec // 3600)
    ov_minutes = int((ov_sec % 3600) // 60)
    ov_display = f"{ov_hours}시간 {ov_minutes}분"

    # =========================================================
    # ✅ [연출용] 이승엽(25DS0001) 데이터 강제 덮어쓰기
    # =========================================================
    if employee_id == '25DS0001':
        ov_count = 4
        ov_display = "8시간 14분"
    # =========================================================

    attendance_stats = {
        'late': stats['late'], 
        'absent': stats['absent'], 
        'early_leave': stats['early_leave'],
        'ov_cnt': ov_count,
        'ov_time': ov_display
    }
    
    # 5. 고정 수당/공제
    cursor.execute("SELECT allowance_name, amount FROM fixed_allowances WHERE employee_id = ?", (employee_id,))
    allowances = cursor.fetchall()
    
    conn.close()
    
    return render_template('modal_employee_detail.html', 
                           employee=employee,
                           attendance_records=attendance_records,
                           attendance_stats=attendance_stats,
                           allowances=allowances)
# ==========================================
# ✅ [실제] 출근 처리 (현재 시간 반영)
# ==========================================
@app.route('/check_in', methods=['POST'])
@login_required
def check_in():
    employee_id = g.user['id']
    
    # 1. 실제 현재 날짜와 시간 구하기
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')  # 예: 2024-12-15
    time_str = now.strftime('%H:%M:%S')  # 예: 08:55:12
    
    # 2. [로직] 09:00:00 기준으로 지각 여부 자동 판단
    standard_start_time = "09:00:00"
    
    if time_str > standard_start_time:
        status = "지각"
    else:
        status = "정상" # 혹은 '출근'

    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # 이미 출근했는지 확인 (오늘 날짜 기준)
    cursor.execute("SELECT id FROM attendance WHERE employee_id = ? AND record_date = ?", (employee_id, date_str))
    row = cursor.fetchone()

    if row:
        flash('이미 출근 처리가 되었습니다.', 'warning')
    else:
        # DB 저장 (계산된 실제 시간과 상태를 넣음)
        cursor.execute("""
            INSERT INTO attendance (employee_id, record_date, clock_in_time, attendance_status) 
            VALUES (?, ?, ?, ?)
        """, (employee_id, date_str, time_str, status))
        
        conn.commit()
        # 메시지도 실제 시간으로 보여줌
        flash(f'출근 완료! ({time_str} - {status})', 'success')

    conn.close()
    return redirect(request.referrer or url_for('dashboard'))


# ==========================================
# ✅ [실제] 퇴근 처리 (현재 시간 반영)
# ==========================================
@app.route('/check_out', methods=['POST'])
@login_required
def check_out():
    employee_id = g.user['id']
    
    # 1. 실제 현재 날짜와 시간 구하기
    now = datetime.now()
    date_str = now.strftime('%Y-%m-%d')
    time_str = now.strftime('%H:%M:%S')

    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()

    # 출근 기록이 있는지 확인하고 퇴근 시간 업데이트
    # (퇴근은 상태 변경 로직이 보통 없으므로 시간만 업데이트)
    cursor.execute("""
        UPDATE attendance 
        SET clock_out_time = ? 
        WHERE employee_id = ? AND record_date = ?
    """, (time_str, employee_id, date_str))
    
    if cursor.rowcount > 0:
        conn.commit()
        flash(f'퇴근 완료! ({time_str})', 'success')
    else:
        flash('오늘 출근 기록이 없어 퇴근 처리를 할 수 없습니다.', 'warning')

    conn.close()
    return redirect(request.referrer or url_for('dashboard'))
# ==========================================
# [시스템] 활동 로그 저장 함수 (공통 모듈)
# ==========================================
def log_activity(action_type, target_category, details):
    """
    사용자의 중요 활동을 DB에 기록합니다.
    사용법: log_activity('UPDATE', '급여', '홍길동 급여 수정됨')
    """
    try:
        conn = sqlite3.connect('employees.db')
        cursor = conn.cursor()
        
        # 현재 로그인한 사용자 정보 (없으면 SYSTEM)
        if g.user:
            user_id = g.user['id']
            user_name = g.user['name']
        else:
            user_id = 'SYSTEM'
            user_name = 'System'
            
        ip_address = request.remote_addr
        
        cursor.execute("""
            INSERT INTO activity_logs (user_id, user_name, action_type, target_category, details, ip_address)
            VALUES (?, ?, ?, ?, ?, ?)
        """, (user_id, user_name, action_type, target_category, details, ip_address))
        
        conn.commit()
        conn.close()
    except Exception as e:
        print(f"로그 저장 실패: {e}") # 로그 실패로 메인 로직이 죽지 않게 예외처리

# ==========================================
# [시스템] 활동 로그 조회 (부서 검색 기능 추가)
# ==========================================
@app.route('/system/logs')
@login_required
@admin_required
def system_logs():
    conn = sqlite3.connect('employees.db')
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # --- [1] 검색 파라미터 받기 ---
    keyword = request.args.get('keyword', '').strip()
    action_type = request.args.get('action_type', '')
    department = request.args.get('department', '') # ✅ 부서 파라미터 추가
    start_date = request.args.get('start_date')
    end_date = request.args.get('end_date')

    # --- [2] SQL 쿼리 구성 ---
    # 먼저 department를 계산해서 가상 테이블처럼 만듭니다 (WITH절 사용 or 서브쿼리)
    # 하지만 SQLite 버전에 따라 복잡할 수 있으니 WHERE 절에서 직접 처리합니다.
    
    query = """
        SELECT 
            a.*, 
            CASE 
                WHEN a.user_name = '홍길동' THEN '인사팀' 
                WHEN a.user_id = 'admin' THEN '인사팀'
                ELSE e.department 
            END as department
        FROM activity_logs a
        LEFT JOIN employees e ON a.user_id = e.id
        WHERE 1=1 
    """
    
    params = []
    
    # ✅ 조건 1: 부서 검색 (가장 중요)
    if department:
        # 화면에 보이는 'department' 값과 일치하는지 확인 (CASE문 전체를 조건으로 씀)
        query += """ AND (
            CASE 
                WHEN a.user_name = '홍길동' THEN '인사팀' 
                WHEN a.user_id = 'admin' THEN '인사팀'
                ELSE e.department 
            END
        ) = ? """
        params.append(department)

    # 조건 2: 검색어 (이름, 아이디, 상세내용)
    if keyword:
        query += " AND (a.user_name LIKE ? OR a.user_id LIKE ? OR a.details LIKE ?)"
        like_pattern = f"%{keyword}%"
        params.extend([like_pattern, like_pattern, like_pattern])
        
    # 조건 3: 유형
    if action_type:
        query += " AND a.action_type = ?"
        params.append(action_type)
        
    # 조건 4: 날짜 범위
    if start_date:
        query += " AND date(a.timestamp) >= ?"
        params.append(start_date)
    if end_date:
        query += " AND date(a.timestamp) <= ?"
        params.append(end_date)
        
    # 정렬 및 제한
    query += " ORDER BY a.timestamp DESC LIMIT 100"
    
    # --- [3] 실행 ---
    logs = cursor.execute(query, params).fetchall()
    conn.close()
    
    return render_template('log_view.html', logs=logs)
if __name__ == '__main__':
    app.run(debug=True)