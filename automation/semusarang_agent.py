#!/usr/bin/env python3
"""세무사랑 자동화 에이전트.

브라우저(taxmanager 웹앱)는 보안상 데스크톱 프로그램(세무사랑)을 직접 제어할 수
없다. 이 에이전트는 세무사랑이 설치된 바로 그 PC에서 로컬로 실행되어, 웹앱의
요청을 받아 세무사랑이 내보낸 파일을 찾아 돌려주거나(watch 모드), 직접 세무사랑
화면을 조작해 내보내기까지 수행한 뒤(automate 모드) 결과 파일을 돌려준다.

보안: 127.0.0.1(로컬)에만 바인딩하고, 모든 요청에 토큰을 요구하며,
CORS는 설정된 단일 origin만 허용한다. 이 포트를 외부에 노출하거나
포트포워딩하지 말 것.
"""
import base64
import hmac
import json
import os
import secrets
import sys
import time
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

try:
    from pywinauto import Application  # type: ignore
    PYWINAUTO_AVAILABLE = True
except ImportError:
    PYWINAUTO_AVAILABLE = False

CONFIG_PATH = Path(__file__).with_name("config.json")


def load_config(path=CONFIG_PATH):
    if not path.exists():
        example = path.with_name("config.example.json")
        default = json.loads(example.read_text(encoding="utf-8")) if example.exists() else {}
        default["token"] = secrets.token_urlsafe(24)
        path.write_text(json.dumps(default, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[agent] 설정 파일이 없어 새로 생성했습니다: {path}")
        print(f"[agent] 발급된 토큰: {default['token']}")
        print("[agent] config.json을 열어 watch_dir / allowed_origin 등을 실제 환경에 맞게 수정한 뒤 다시 실행하세요.")
        raise SystemExit(1)
    return json.loads(path.read_text(encoding="utf-8"))


def find_latest_export(watch_dir, pattern, max_age_minutes):
    watch_path = Path(watch_dir)
    if not watch_path.is_dir():
        raise RuntimeError(f'watch_dir이 존재하지 않습니다: {watch_dir}')
    now = time.time()
    candidates = []
    for p in watch_path.glob(pattern):
        if not p.is_file():
            continue
        age_min = (now - p.stat().st_mtime) / 60
        if age_min <= max_age_minutes:
            candidates.append(p)
    if not candidates:
        raise RuntimeError(
            f'"{pattern}" 패턴과 일치하는 최근 {max_age_minutes}분 이내 파일을 찾지 못했습니다. '
            '세무사랑에서 먼저 내보내기(엑셀저장)를 실행하세요.'
        )
    candidates.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return candidates[0]


def automate_semusarang(config, doc_type):
    """세무사랑 화면을 직접 조작해 내보내기까지 수행한다 (automate 모드 전용).

    실제 메뉴 구조는 세무사랑 버전마다 다르므로, inspect_semusarang.py로 확인한
    정확한 창 제목·컨트롤 이름으로 config.json의 menu_paths를 먼저 채워야 한다.
    """
    if not PYWINAUTO_AVAILABLE:
        raise RuntimeError("pywinauto가 설치되어 있지 않습니다 (automate 모드는 Windows 전용, requirements.txt 참고).")
    steps = (config.get("menu_paths") or {}).get(doc_type)
    if not steps:
        raise RuntimeError(f'config.json의 menu_paths.{doc_type} 설정이 없습니다.')
    title_re = config.get("window_title_regex")
    if not title_re:
        raise RuntimeError("config.json의 window_title_regex가 설정되지 않았습니다.")
    app = Application(backend="uia").connect(title_re=title_re, timeout=5)
    win = app.top_window()
    win.set_focus()
    for label in steps:
        win.child_window(title=label, control_type="MenuItem").click_input()
        time.sleep(0.4)


def make_handler(config):
    class AgentHandler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"
        cfg = config
        server_version = "SemusarangAgent/1.0"

        def _cors_headers(self):
            origin = self.cfg.get("allowed_origin", "")
            if origin:
                self.send_header("Access-Control-Allow-Origin", origin)
                self.send_header("Vary", "Origin")
            self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Agent-Token")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")

        def _send_json(self, status, payload):
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            self.send_response(status)
            self._cors_headers()
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def _check_token(self):
            expected = self.cfg.get("token", "")
            got = self.headers.get("X-Agent-Token", "")
            return bool(expected) and hmac.compare_digest(got, expected)

        def do_OPTIONS(self):
            self.send_response(204)
            self._cors_headers()
            self.end_headers()

        def do_GET(self):
            if self.path == "/health":
                self._send_json(200, {"status": "ok", "mode": self.cfg.get("mode", "watch")})
            else:
                self._send_json(404, {"error": "not found"})

        def do_POST(self):
            if self.path != "/fetch":
                self._send_json(404, {"error": "not found"})
                return
            if not self._check_token():
                self._send_json(401, {"error": "인증 토큰이 올바르지 않습니다."})
                return
            length = int(self.headers.get("Content-Length", 0) or 0)
            raw = self.rfile.read(length) if length else b"{}"
            try:
                data = json.loads(raw or b"{}")
            except json.JSONDecodeError:
                self._send_json(400, {"error": "잘못된 요청 본문입니다."})
                return
            doc_type = data.get("type", "clients")
            pattern = (self.cfg.get("file_patterns") or {}).get(doc_type)
            if not pattern:
                self._send_json(400, {"error": f"지원하지 않는 유형입니다: {doc_type}"})
                return
            try:
                if self.cfg.get("mode") == "automate":
                    automate_semusarang(self.cfg, doc_type)
                path = find_latest_export(self.cfg["watch_dir"], pattern, self.cfg.get("max_age_minutes", 10))
                content = path.read_bytes()
            except Exception as exc:  # noqa: BLE001 - surface the message to the caller
                self._send_json(502, {"error": str(exc)})
                return
            self._send_json(200, {
                "filename": path.name,
                "content_base64": base64.b64encode(content).decode("ascii"),
            })

        def log_message(self, fmt, *args):
            print("[agent]", fmt % args)

    return AgentHandler


def serve(config, port=None):
    if not config.get("token"):
        raise RuntimeError("config.json에 token이 설정되지 않았습니다.")
    handler_cls = make_handler(config)
    httpd = HTTPServer(("127.0.0.1", port or config.get("port", 5987)), handler_cls)
    print(f"[agent] 세무사랑 자동화 에이전트 실행 중: http://127.0.0.1:{httpd.server_port} (mode={config.get('mode','watch')})")
    print("[agent] 이 창을 닫으면 에이전트가 중지됩니다. Ctrl+C로 종료할 수 있습니다.")
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass


def main():
    config = load_config()
    serve(config)


if __name__ == "__main__":
    sys.exit(main() or 0)
