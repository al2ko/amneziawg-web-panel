"""Хеширует пароль из stdin для неинтерактивной установки без argv/env leakage."""
import sys

from amnezia_panel.security import AuthService


def main() -> None:
    """▶ stdin secret → policy → Argon2id hash; plaintext never printed."""
    password = sys.stdin.readline().rstrip("\r\n")
    print(AuthService.hash_password(password))


if __name__ == "__main__":
    main()
