from flask import Flask, render_template

app = Flask(__name__)

# 대시보드 (메인 화면) 라우트 설정
@app.route('/')
def dashboard():
    return render_template('dashboard.html')

# 인사 관리 페이지 라우트 설정
@app.route('/hr')
def hr_management():
    return render_template('hr_management.html')

# (선택 사항) 근태 관리 페이지 라우트 설정
@app.route('/attendance')
def attendance():
    return render_template('attendance.html')


if __name__ == '__main__':
    app.run(debug=True)