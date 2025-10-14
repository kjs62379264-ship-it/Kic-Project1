from flask import Flask, render_template, request, redirect, url_for, session, flash
from flask_sqlalchemy import SQLAlchemy 
from sqlalchemy.exc import IntegrityError 

app = Flask(__name__)
# 세션을 사용하려면 비밀 키가 필요합니다.
app.secret_key = 'your_super_secret_key' 

# ==========================================================
# DB 설정 및 SQLAlchemy 객체 생성
# ==========================================================
# SQLite 파일 경로 설정
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///personnel.db' 
# 경고 메시지 비활성화
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)

# ==========================================================
# DB 모델 (Employee) 정의
# ==========================================================
class Employee(db.Model):
    # 'employee'라는 테이블 이름 지정
    __tablename__ = 'employee' 
    
    # 컬럼 정의
    id = db.Column(db.String(10), primary_key=True, unique=True, nullable=False)
    name = db.Column(db.String(50), nullable=False)
    department = db.Column(db.String(50))
    position = db.Column(db.String(50))
    hire_date = db.Column(db.String(10)) # YYYY-MM-DD 형식으로 저장
    status = db.Column(db.String(10), default='재직') # 재직, 퇴사 등

    def __repr__(self):
        return f"<Employee {self.id} - {self.name}>"

# 더미 사용자 데이터 (인증용)
USERS = {
    "admin": "1234", # 아이디: admin, 비밀번호: 1234
    "user1": "password"
}

# --- 1. 로그인 페이지 렌더링 및 처리 ---
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

# --- 2. 메인 페이지 (대시보드) 렌더링 및 접근 제어 ---
@app.route('/')
def index():
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login'))
    
    # index.html은 base.html을 상속받아 대시보드를 표시합니다.
    return render_template('index.html')


# --- 3. 인사 관리 페이지 렌더링 및 접근 제어 (직원 목록 조회) ---
@app.route('/personnel')
def personnel():
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login'))
    
    # DB에서 모든 직원 데이터를 조회합니다.
    employees = Employee.query.all() 
    
    # personnel.html을 렌더링하며 DB에서 가져온 직원 목록 데이터를 전달합니다.
    return render_template('personnel.html', employees=employees)

# --- 4. 새 직원 등록 처리 ---
@app.route('/add_employee', methods=['POST'])
def add_employee():
    if 'logged_in' not in session or not session['logged_in']:
        return redirect(url_for('login'))

    if request.method == 'POST':
        # 폼 데이터 가져오기
        employee_id = request.form.get('employee_id')
        name = request.form.get('name')
        department = request.form.get('department')
        position = request.form.get('position')
        hire_date = request.form.get('hire_date')
        
        # 필수 필드 확인 (사번, 이름)
        if not employee_id or not name:
            print("사번과 이름은 필수 입력 항목입니다.") # 임시 메시지
            return redirect(url_for('personnel'))

        try:
            # 새 Employee 객체 생성
            new_employee = Employee(
                id=employee_id,
                name=name,
                department=department,
                position=position,
                hire_date=hire_date
            )
            
            # DB 세션에 추가 및 커밋
            db.session.add(new_employee)
            db.session.commit()
            
            print(f"직원 {name} ({employee_id}) 등록 성공.") # 임시 메시지
            
        except IntegrityError:
            db.session.rollback() # 오류 발생 시 롤백
            print(f"오류: 사번 {employee_id}가 이미 존재합니다.") # 임시 메시지
        
        except Exception as e:
            db.session.rollback()
            print(f"등록 중 예상치 못한 오류 발생: {e}") # 임시 메시지
            
        # 직원 목록 페이지로 리디렉션하여 결과를 반영합니다.
        return redirect(url_for('personnel'))


# --- 5. 로그아웃 처리 ---
@app.route('/logout')
def logout():
    session.pop('logged_in', None)
    session.pop('username', None)
    return redirect(url_for('login'))

if __name__ == '__main__':
    with app.app_context():
        # DB의 모든 테이블 생성 (초기에 한 번 실행됩니다.)
        db.create_all() 
        
        # 데이터가 비어 있을 경우 초기 데이터 추가
        if not Employee.query.first():
            print(">>> 초기 직원 데이터 추가 중...")
            initial_employees = [
                Employee(id='H001', name='홍길동', department='개발팀', position='대리', hire_date='2020-03-01'),
                Employee(id='H002', name='김철수', department='영업팀', position='사원', hire_date='2023-08-15'),
            ]
            db.session.add_all(initial_employees)
            db.session.commit()

    # 디버그 모드는 개발 중에만 사용합니다.
    app.run(debug=True)
