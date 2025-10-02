from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
# 세션을 사용하려면 비밀 키가 필요합니다. 실제 배포 시에는 복잡하고 안전한 키로 변경하세요.
app.secret_key = 'your_super_secret_key' 

# 더미 사용자 데이터 (실제로는 데이터베이스를 사용해야 함)
USERS = {
    "admin": "1234", # 아이디: admin, 비밀번호: 1234
    "user1": "password"
}

# --------------------------------------------------
# 공통 함수: 로그인 여부 확인
# --------------------------------------------------
def check_login():
    """로그인되지 않았을 경우 로그인 페이지로 리디렉션하는 헬퍼 함수."""
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login'))
    return None # 로그인 상태일 경우 None 반환

# --------------------------------------------------
# 인증 (로그인/로그아웃) 및 메인 페이지 라우트
# --------------------------------------------------

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        if username in USERS and USERS[username] == password:
            session['logged_in'] = True
            session['username'] = username
            return redirect(url_for('index'))
        else:
            error = '아이디 또는 비밀번호가 올바르지 않습니다.'
            return render_template('login.html', error=error)
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

@app.route('/')
def index():
    if check_login():
        return check_login()
    return render_template('index.html')


# --------------------------------------------------
# 인사 관리 중분류 페이지 라우트
# --------------------------------------------------

# 1. 사원 정보 관리 페이지
@app.route('/employee_info')
def employee_info():
    if check_login():
        return check_login()
    # templates/hr/employee_info.html 렌더링
    return render_template('hr/employee_info.html') 

# 2. 조직 및 부서 관리 페이지
@app.route('/organization')
def organization():
    if check_login():
        return check_login()
    # templates/hr/organization.html 렌더링
    return render_template('hr/organization.html') 

# 3. 평가 및 교육 관리 페이지
@app.route('/performance_education')
def performance_education():
    if check_login():
        return check_login()
    # templates/hr/performance_education.html 렌더링
    return render_template('hr/performance_education.html') 

# 4. 발령 및 경력 관리 페이지
@app.route('/assignment_career')
def assignment_career():
    if check_login():
        return check_login()
    # templates/hr/assignment_career.html 렌더링
    return render_template('hr/assignment_career.html') 


if __name__ == '__main__':
    # 디버그 모드는 개발 중에만 사용하고, 실제 배포 시에는 False로 설정하세요.
    app.run(debug=True)