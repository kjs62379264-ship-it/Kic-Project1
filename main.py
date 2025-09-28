import http.server
import socketserver

# 포트 번호를 지정합니다. 8000번을 흔히 사용합니다.
PORT = 8000

# 서버 핸들러를 설정합니다.
Handler = http.server.SimpleHTTPRequestHandler

# 서버를 실행합니다.
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print("간이 웹 서버를 시작합니다.")
    print(f"http://localhost:{PORT} 에서 접속 가능합니다.")

    # 서버를 계속 실행 상태로 유지합니다.
    httpd.serve_forever()