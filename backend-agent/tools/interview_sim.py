"""
인터뷰 프롬프트 두 벌을 같은 가상 어르신과 대화시켜 비교한다. 서버 · DB 없이 돈다.

    backend-agent 에서:  python <이 파일> <결과.json> [최대턴]

질문 쪽은 서버와 같은 함수(question.gemini_question · shared.merge)를 그대로 쓰고
프롬프트 파일만 갈아 끼운다. 어르신 쪽은 기억표만 아는 Gemini 가 짧게 답한다.
"""
import asyncio
import json
import os
import sys
import time
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, ".")
from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")
os.environ["GEMINI_TIMEOUT"] = "15"          # 품질을 본다. 시간은 따로 잰다

from google.genai import types  # noqa: E402

from app.session import prompt as promptlib  # noqa: E402
from app.session import question  # noqa: E402
from app.session import shared  # noqa: E402

OUT = Path(sys.argv[1])
MAX_TURN = int(sys.argv[2]) if len(sys.argv) > 2 else 10
DIR = Path("첨부프롬프트_md")
PROMPTS = {"v3": DIR / "인터뷰_v3.md", "육하원칙": DIR / "인터뷰_육하원칙.md"}
SIX = ("event", "who", "when", "place", "how", "why")

PERSONAS = [
    {
        "name": "상경",
        "theme": "self", "topic": "고향을 떠나 서울로 온 날",
        "memory": "1968년쯤, 열아홉 살에 전남 영암에서 서울로 올라왔다. 집이 가난해서 동생들 "
                  "학비를 벌려고 왔다. 밤새 완행열차를 타고 왔고 큰형이 영등포역까지 마중을 "
                  "나왔다. 처음 몇 달은 형의 자취방(영등포)에서 같이 지냈다. 청계천 봉제공장에 "
                  "들어갔다. 무섭기도 했지만 설렜다. 열차에서 먹은 것은 기억이 안 난다.",
    },
    {
        "name": "첫아이",
        "theme": "family", "topic": "첫아이가 태어난 날",
        "memory": "겨울에 부산 시댁 근처 조산원에서 첫딸을 낳았다. 몇 년도인지는 정확히 기억이 "
                  "안 난다(스물네 살 때). 새벽에 진통이 와서 시어머니와 함께 걸어서 조산원에 "
                  "갔다. 남편은 배를 타러 나가 있어서 없었다. 아이가 작아서 걱정했지만 "
                  "건강했다. 왜 조산원이었냐고 하면 그때는 다 그렇게 낳았다.",
    },
    {
        "name": "결혼식",
        "theme": "family", "topic": "결혼식 날",
        "memory": "중매로 만난 남편과 결혼했다. 대구의 작은 예식장이었다. 연도는 기억이 안 난다. "
                  "스물두 살 때였다. 친정어머니가 한복을 지어 주셨다. 비가 왔다. 왜 그 사람과 "
                  "결혼했냐고 하면 부모님이 정해서 했다. 신혼여행은 안 갔다.",
    },
    {
        "name": "어머니",
        "theme": "family", "topic": "어머니와의 마지막 기억",
        "memory": "어머니는 내가 서른 살 때 병원에서 돌아가셨다. 마지막으로 뵌 날 어머니가 "
                  "'밥은 먹고 다니냐'고 하셨다. 이 이야기를 하면 목이 멘다. 두세 번 이야기한 뒤에는 "
                  "'이 얘기는 그만하자, 마음이 아파'라고 말한다.",
    },
    {
        "name": "낚시",
        "theme": "hobby", "topic": "낚시를 시작한 이야기",
        "memory": "예순 살쯤 퇴직하고 나서 낚시를 시작했다. 집에만 있으니 답답해서였다. 친구 "
                  "철수가 낡은 낚싯대를 하나 주면서 데려갔다. 처음 간 곳은 충주호였다. 첫날은 "
                  "한 마리도 못 잡았다. 그 뒤로 주말마다 다녔다. 아내 이야기는 하고 싶지 않다 "
                  "(물어보면 그건 말하기 싫다고 답한다).",
    },
]

ELDER_SYS = (
    "당신은 일흔이 넘은 한국 어르신 역할입니다. 아래 [기억]에 있는 것만 말합니다. "
    "없는 것을 물으면 '글쎄, 그건 잘 기억이 안 나네'처럼 답합니다. "
    "질문이 물은 것 하나만, 한 문장 이하의 짧은 구어체로 답합니다. 묻지 않은 기억을 한꺼번에 꺼내지 않습니다. "
    "맨 처음 질문에는 '글쎄, 오래돼서…'처럼 머뭇거리고, 그다음부터는 질문과 닿는 기억을 하나씩 꺼냅니다. "
    "넓게 물으면 아직 말하지 않은 기억 하나를 꺼냅니다. 가끔은 '응, 그랬지'처럼 아주 짧게만 답합니다. "
    "설명이나 따옴표 없이 대답만 씁니다.")


async def elder(client, memory: str, history: list[dict], q: str) -> str:
    talk = "\n".join(f"질문: {h['question']}\n나: {h['answer']}" for h in history)
    res = await client.aio.models.generate_content(
        model=question.DEFAULT_MODEL,
        contents=f"[기억]\n{memory}\n\n[지금까지]\n{talk}\n\n질문: {q}\n나:",
        config=types.GenerateContentConfig(
            system_instruction=ELDER_SYS, temperature=0.6, max_output_tokens=120,
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL"),
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True)))
    return (res.text or "").strip()


async def fallback(ctl):
    return "(대체 질문 — 6턴 전 마무리를 서버가 막음, 또는 생성 실패)"


async def run(client, label: str, persona: dict) -> dict:
    promptlib.DOC = PROMPTS[label]
    promptlib.load.cache_clear()
    six = label == "육하원칙"
    shared.INFO_KEYS = ("event", "when", "who", "place", "how", "why", "emotion") if six \
        else ("event", "when", "who", "place", "emotion")
    state = shared.initial()
    if six:
        state["information_status"].update(how="missing", why="missing")

    ctl = SimpleNamespace(
        fragments=[{"idx": 0, "question": None, "answer": persona["topic"]}],
        state=state, machine=SimpleNamespace(turn=0),
        theme=persona["theme"], topic=persona["topic"],
        closing_hint=None, last_decision=None)
    turns = []
    for t in range(MAX_TURN + 1):
        ctl.machine.turn = t
        t0 = time.perf_counter()
        q = await question.gemini_question(ctl)
        ms = round((time.perf_counter() - t0) * 1000)
        d = ctl.last_decision or {}
        info = dict(ctl.state.get("information_status") or {})
        row = {"turn": t, "ms": ms, "question": q, "type": d.get("question_type"),
               "status": d.get("topic_status"), "end": d.get("end_reason"),
               "info": info, "facts": d.get("facts_found")}
        if q is None:
            turns.append(row)
            break
        hist = [{"question": f["question"], "answer": f["answer"]} for f in ctl.fragments[1:]]
        a = await elder(client, persona["memory"], hist, q)
        row["answer"] = a
        turns.append(row)
        ctl.fragments.append({"idx": len(ctl.fragments), "question": q, "answer": a})
        ctl.last_decision = None
    return {"prompt": label, "persona": persona["name"], "turns": turns}


def filled(info: dict, keys) -> str:
    return "".join("■" if info.get(k) not in (None, "missing") else "□" for k in keys)


async def main():
    question._fallback = fallback
    client = question._client()
    runs = []
    for p in PERSONAS:
        for label in PROMPTS:
            r = await run(client, label, p)
            runs.append(r)
            print(f"\n===== {p['name']} · {label}", flush=True)
            for row in r["turns"]:
                keys = SIX if label == "육하원칙" else ("event", "who", "when", "place")
                print(f"[{row['turn']:>2}] {row['ms']:>5}ms {filled(row['info'], keys)} "
                      f"{row['type'] or '-'}/{row['status']}{'/' + row['end'] if row['end'] else ''}")
                print(f"     Q: {row['question']}")
                if row.get("answer"):
                    print(f"     A: {row['answer']}")
    print("\n===== 요약")
    for r in runs:
        qs = [t["question"] for t in r["turns"] if t["question"]]
        last = r["turns"][-1]
        dup = len(qs) - len(set(qs))
        more = sum(1 for q in qs if any(w in q for w in ("더 들려", "더 전해", "더 남", "다른 이야기")))
        print(f"{r['persona']:<5} {r['prompt']:<5} 질문 {len(qs):>2} · "
              f"끝 {last.get('status')}/{last.get('end') or '-'} · 똑같은 질문 {dup} · 마무리성 질문 {more}")
    OUT.write_text(json.dumps(runs, ensure_ascii=False, indent=1), encoding="utf-8")


asyncio.run(main())
