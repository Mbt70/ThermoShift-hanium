"""데스크톱 대시보드용 auth_store.

모바일과 완전히 같은 로직이라 app/components/auth_store.py 를 그대로 재사용한다.
사본을 두면 세션 토큰 같은 상태가 두 모듈에 나뉘어 서로 안 보이게 된다.

web/pages/*.py 는 `from components.auth_store import ...` 로 부르므로
이 얇은 재-export 모듈이 필요하다.
"""

from app.components.auth_store import (  # noqa: F401
    check_credentials,
    current_user_email,
    current_user_name,
    delete_user,
    is_logged_in,
    is_registered,
    log_out,
    register_user,
    set_current_user,
    sync_token,
    update_password,
    update_user_name,
)
