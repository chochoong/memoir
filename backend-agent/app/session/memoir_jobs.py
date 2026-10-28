"""
자서전 작업 — 시작하고 나중에 받는다 (단위 8S 연결)

    POST   /api/memoirs             검사 · 조회까지 바로 → 202 {job_id, status: running, stage, run}
    GET    /api/memoirs/{job_id}    running (지금 단계) · done (7-C1 결과) · failed (code)
    GET    /api/memoirs/latest      내 가장 최근 작업 — 작업 번호를 잊은 화면(새로고침)이 찾는다
    DELETE /api/memoirs/{job_id}    그만 만든다

**왜 작업인가.** 다섯 단계는 39회차 실측 369초 (분석 90 · 목차 45 · 장마다 25 · 편집 101 ·
검증 30, gemini-3.1-pro-preview · 10-28). Cloudflare 는 100초가 넘는 응답을 끊고 화면은
120초에 접는다. 기다리는 요청(/api/memoirs/preview)은 그대로 둔다 — 예전 화면 · 한 번 호출용.

**저장하지 않는다** (7-C1 §4 · 태헌). 작업은 이 프로세스 메모리에만 있다. 서버를 다시 켜면
사라지고 GET 은 404 job_not_found 다 — 화면은 「다시 만들어 주세요」 로 안내한다. 끝난 작업은
MEMOIR_JOB_KEEP_SECONDS (기본 1800) 동안 둔다.

**한 사람에 하나씩.** 만드는 중인 작업이 있으면 새로 시작하지 않고 409 busy 와 그 job_id 를
준다 — 같은 버튼을 두 번 눌러 모델 호출이 두 배로 나가지 않게. 재시도는 하지 않는다 (8P 0회).

작업은 남의 것을 보여 주지 않는다. 없는 것과 남의 것은 둘 다 404 다.
"""

from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field

from . import memoir
from .conf import env_int

log = logging.getLogger("memoir")

DEFAULT_KEEP_SECONDS = 1800
RUNNING, DONE, FAILED = "running", "done", "failed"


def keep_seconds() -> int:
    return env_int("MEMOIR_JOB_KEEP_SECONDS", DEFAULT_KEEP_SECONDS)


class Cancelled(memoir.MemoirError):
    """DELETE 로 그만두었다. 화면은 code cancelled 를 본다."""


@dataclass
class Job:
    job_id: str
    user_id: str
    ids: list[str]
    style: str
    status: str = RUNNING
    # pipeline: analysis → outline → chapter (chapter / chapters) → edit → verify · single: write
    stage: str = "analysis"
    chapter: int = 0
    chapters: int = 0
    result: dict | None = None
    error: Exception | None = None
    started: float = field(default_factory=time.monotonic)
    finished: float | None = None
    task: asyncio.Task | None = None


_JOBS: dict[str, Job] = {}


def _sweep() -> None:
    now, keep = time.monotonic(), keep_seconds()
    for k in [k for k, j in _JOBS.items() if j.finished is not None and now - j.finished > keep]:
        del _JOBS[k]


def running(user_id: str) -> Job | None:
    return next((j for j in _JOBS.values() if j.user_id == user_id and j.status == RUNNING), None)


def latest(user_id: str) -> Job | None:
    """이 사람의 가장 최근 작업 (보관 시간 안). 없으면 None."""
    _sweep()
    mine = [j for j in _JOBS.values() if j.user_id == user_id]
    return max(mine, key=lambda j: j.started) if mine else None


def get(job_id: str, user_id: str) -> Job | None:
    _sweep()
    job = _JOBS.get(job_id)
    return job if job is not None and job.user_id == user_id else None


async def start(recs: list[dict], ids: list[str], user_id: str, style: str) -> Job:
    """collect 를 지난 회차로 작업을 연다. 만드는 중인 것이 있는지는 라우트가 먼저 본다."""
    _sweep()
    job = Job(uuid.uuid4().hex, user_id, ids, style,
              stage="analysis" if memoir.engine(user_id) == "pipeline" else "write")

    def progress(stage: str, chapter: int, chapters: int) -> None:
        job.stage, job.chapter, job.chapters = stage, chapter, chapters

    async def work() -> None:
        try:
            job.result = await memoir.generate(recs, ids, user_id, style, progress)
            job.status = DONE
        except asyncio.CancelledError:
            job.status, job.error = FAILED, Cancelled("그만두었다")
            raise
        except memoir.MemoirError as e:
            job.status, job.error = FAILED, e
        except Exception as e:                               # noqa: BLE001
            log.exception("자서전 작업 %s 예상 못 한 오류", job.job_id[:8])
            job.status, job.error = FAILED, memoir.GenerationFailed(f"{type(e).__name__}: {e}")
        finally:
            job.finished = time.monotonic()
            log.info("자서전 작업 %s — %s · %.1f초 · %s", job.job_id[:8], job.status,
                     job.finished - job.started, type(job.error).__name__ if job.error else "-")

    _JOBS[job.job_id] = job
    job.task = asyncio.create_task(work())
    log.info("자서전 작업 %s 시작 — 회차 %d개 · 엔진 %s", job.job_id[:8], len(ids), memoir.engine(user_id))
    return job


def cancel(job: Job) -> None:
    if job.status == RUNNING and job.task is not None:
        job.task.cancel()


def elapsed(job: Job) -> int:
    return int((job.finished or time.monotonic()) - job.started)
