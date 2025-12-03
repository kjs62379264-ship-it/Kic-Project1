import sqlite3

def update_database():
    conn = sqlite3.connect('employees.db')
    cursor = conn.cursor()
    
    print("DB 업데이트 시작...")
    
    try:
        # 1. departments 테이블에 is_active 컬럼 추가 (기본값 1: 활성)
        cursor.execute("ALTER TABLE departments ADD COLUMN is_active BOOLEAN DEFAULT 1")
        print("- 'is_active' 컬럼이 추가되었습니다.")
    except sqlite3.OperationalError:
        print("- 'is_active' 컬럼이 이미 존재합니다.")
        
    conn.commit()
    conn.close()
    print("완료되었습니다.")

if __name__ == '__main__':
    update_database()