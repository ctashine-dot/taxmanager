#!/usr/bin/env python3
"""세무사랑 창/컨트롤 구조를 확인하기 위한 도구 (Windows 전용).

automate 모드를 쓰려면 config.json의 window_title_regex, menu_paths를
실제 세무사랑 화면 구조에 맞게 채워야 한다. 이 스크립트는 그 정보를
얻기 위한 용도로, 세무사랑을 켜 둔 상태에서 실행한다.

사용법:
    python inspect_semusarang.py --list
        현재 열려 있는 모든 창의 제목을 나열한다. 이 중 세무사랑 창 제목을 확인해
        config.json의 window_title_regex에 반영한다.

    python inspect_semusarang.py --title "세무사랑"
        제목에 "세무사랑"이 포함된 창을 찾아 컨트롤(메뉴/버튼 등) 구조를
        control_tree.txt 파일로 저장한다. 이 파일 내용을 참고해
        config.json의 menu_paths(메뉴 이름 목록)를 채운다.
"""
import argparse
import sys

try:
    from pywinauto import Desktop
except ImportError:
    print("pywinauto가 설치되어 있지 않습니다. Windows에서: pip install -r requirements.txt", file=sys.stderr)
    sys.exit(1)


def list_windows():
    for w in Desktop(backend="uia").windows():
        title = w.window_text()
        if title:
            print(f"- {title!r}")


def dump_controls(title_substr, out_path="control_tree.txt"):
    matches = [w for w in Desktop(backend="uia").windows() if title_substr in w.window_text()]
    if not matches:
        print(f'제목에 "{title_substr}"이(가) 포함된 창을 찾지 못했습니다. --list로 전체 창 목록을 먼저 확인하세요.')
        return
    win = matches[0]
    print(f"연결됨: {win.window_text()!r}")
    import io
    import contextlib
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        win.print_control_identifiers()
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(buf.getvalue())
    print(f"컨트롤 구조를 {out_path}에 저장했습니다. 이 파일에서 메뉴/버튼 이름을 확인해 config.json의 menu_paths를 채우세요.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="열려 있는 창 제목 목록 출력")
    parser.add_argument("--title", help="컨트롤 구조를 덤프할 창 제목(부분 일치)")
    parser.add_argument("--out", default="control_tree.txt", help="컨트롤 구조 저장 파일 경로")
    args = parser.parse_args()

    if args.list:
        list_windows()
    elif args.title:
        dump_controls(args.title, args.out)
    else:
        parser.print_help()
