"""앱 버전 단일 소스 (single source of truth).

이 값 하나만 바꾸면 앱 타이틀, 자동 업데이트 비교 기준, 그리고
build.py가 installer.iss(`AppVersion`)에 주입하는 버전이 모두 갱신된다.

릴리스 시:
  1. 이 파일의 __version__ 을 올린다 (예: "1.0.1").
  2. git tag v1.0.1 후 build.py로 설치파일을 만든다.
  3. release.py 로 공개 릴리스 저장소에 게시한다.

주의: PySide6 등 무거운 모듈을 import 하지 말 것.
build.py가 이 파일을 정규식으로 파싱하므로 __version__ 정의는 단순하게 유지.
"""

__version__ = "1.0.2"
