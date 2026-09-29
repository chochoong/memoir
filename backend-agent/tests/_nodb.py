"""
TestClient 로 앱을 띄울 때 실제 DB 에 붙지 않게 한다.

TestClient 는 lifespan 을 돌리고, lifespan 은 .env 의 PG_* 로 풀을 연다.
그대로 두면 라우트 검사가 만든 회차가 개발 DB 의 「지난 회차」에 쌓인다 —
대화 없는 「시험」 회차가 목록을 채워 진짜 회차가 묻힌다. 배포 DB 에서
돌리면 어르신 목록에도 섞인다.

풀이 없으면 store 의 읽기·쓰기는 전부 조용히 건너뛴다 (store.open_pool 참조).
DB 를 보는 검사는 저마다 store 함수를 가짜로 바꿔 끼운다.
"""

from __future__ import annotations

from app.session import store


class NoDb:
    def __enter__(self):
        self._open = store.open_pool

        async def _skip() -> None:
            store._pool = None

        store.open_pool = _skip
        return self

    def __exit__(self, *a):
        store.open_pool = self._open
