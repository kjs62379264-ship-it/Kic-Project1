from flask import Flask, render_template, request, redirect, url_for, session

app = Flask(__name__)
# 세션을 사용하려면 비밀 키가 필요합니다. 실제 배포 시에는 복잡하고 안전한 키로 변경하세요.
app.secret_key = 'your_super_secret_key' 

# 더미 사용자 데이터 (실제로는 데이터베이스를 사용해야 함)
USERS = {
    "admin": "1234", # 아이디: admin, 비밀번호: 1234
    "user1": "password"
}

# --- 1. 로그인 페이지 렌더링 및 처리 ---
@app.route('/login', methods=['GET', 'POST'])
def login():
    # POST 요청 (로그인 시도)
    if request.method == 'POST':
        username = request.form['username']
        password = request.form['password']

        # 사용자 인증 확인
        if username in USERS and USERS[username] == password:
            # 로그인 성공 시 세션에 사용자 정보 저장
            session['logged_in'] = True
            session['username'] = username
            
            # 메인 페이지로 리디렉션
            return redirect(url_for('index'))
        else:
            # 로그인 실패 시 에러 메시지와 함께 로그인 페이지 다시 표시
            error = '아이디 또는 비밀번호가 올바르지 않습니다.'
            return render_template('login.html', error=error)
    
    # GET 요청 (로그인 페이지 접속)
    return render_template('login.html')

# --- 2. 메인 페이지 렌더링 및 접근 제어 ---
@app.route('/')
def index():
    # 세션에 'logged_in' 정보가 없으면 (로그인되지 않았으면)
    if 'logged_in' not in session or not session['logged_in']:
        # 로그인 페이지로 강제 리디렉션
        return redirect(url_for('login'))
    
    # 로그인된 경우에만 메인 페이지 (index.html)를 렌더링
    return render_template('index.html')

# --- 3. 로그아웃 처리 ---
@app.route('/logout')
def logout():
    # 세션에서 사용자 정보 삭제
    session.pop('logged_in', None)
    session.pop('username', None)
    # 로그인 페이지로 리디렉션
    return redirect(url_for('login'))

if __name__ == '__main__':
    # 디버그 모드는 개발 중에만 사용하고, 실제 배포 시에는 False로 설정하세요.
    app.run(debug=True)