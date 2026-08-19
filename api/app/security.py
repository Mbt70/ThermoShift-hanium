"""비밀번호 해싱.

기존 프론트 auth_store는 평문 비밀번호를 JSON에 저장했다. API로 옮기면서
표준 라이브러리만으로 PBKDF2-HMAC-SHA256 해시로 전환한다.
저장 형식: pbkdf2_sha256$<iterations>$<salt_hex>$<hash_hex>
"""

import hashlib
import hmac
import os

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 260_000
SALT_BYTES = 16


def hash_password(password: str) -> str:
    salt = os.urandom(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, ITERATIONS)
    return f"{ALGORITHM}${ITERATIONS}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algorithm, iterations, salt_hex, hash_hex = stored.split("$")
    except ValueError:
        return False
    if algorithm != ALGORITHM:
        return False
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), bytes.fromhex(salt_hex), int(iterations)
    )
    # 타이밍 공격을 피하기 위해 상수 시간 비교를 쓴다.
    return hmac.compare_digest(digest.hex(), hash_hex)
