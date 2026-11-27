"""
자서전 삽화 — 장면 선정과 그림 지시문 (로컬 실험 · 서비스 경로와 따로 돈다)

    입력 검사   check_input        자서전(장 · 문단 · 문장) + 합친 원문(utterances) + 사진 목록
    후보        select_message     모델에 줄 자료 — **이 파일은 모델을 부르지 않는다** (call 을 받아 쓴다)
                check_candidates   모델(또는 모의 응답)이 낸 후보의 모양
    원문 대조   _element           요소마다 인용이 그 턴의 어르신 말씀에 글자 그대로 있는가
    판정        _judge             SCENE · SYMBOLIC · SKIP / verified · partial · unverified / 사진 겹침
    고르기      _pick              책 한 권에 최대 MAX_SCENES 장면 · 장마다 고르게
    그림 지시문 build_prompt       확인된 요소 + 고정 양식(삽화/2_그림양식_v1.md)만으로 코드가 조립
                check_prompt       조립한 지시문에 확인되지 않은 것이 섞였는지

**다른 자서전 모듈을 import 하지 않는다.** 입력은 서비스 응답(7-C1 §3 — 장 no · 문단 sentences)과
파이프라인 결과(chapter_key · 문단이 문장 목록) 두 모양을 다 받는다. DB · 서버 · 저장소를 쓰지 않는다.

**모델이 고르고 코드가 확인한다.** 모델의 판단(중요도 · 추천 이유)은 참고로만 남기고, 방식(visual_mode) ·
검증 상태 · 자동 생성 여부는 코드가 정한다. 모델이 낸 것을 고쳐 주지 않는다 — 모양이 어긋나면 실패,
내용이 원문과 맞지 않으면 그 요소를 버린다.

**인용 일치는 사실 검증이 아니다.** 코드가 보는 것은 ① 인용이 그 턴 원문에 있는가 ② 요소 이름이 인용
안의 말인가 ③ 인용이 든 문장에 부정 · 전언 · 불확실 표지가 있는가 ④ 그 턴을 자서전의 그 장이 근거로
쓰는가 — 여기까지다. 누가 무엇을 했는지(주어 · 관계), 여러 턴을 한 장면으로 묶어도 되는지, 그림이
덧붙일 시각 요소는 보지 못한다. 결과의 verification_scope 에 본 것 · 못 본 것을 그대로 적는다.

**verified 는 「원문 근거를 따라갈 수 있다」 는 뜻이지 사실이 검증됐다는 뜻이 아니다.** 장면마다 checks 에
항목별로 적는다 — 인용 일치 · 부정 · 불확실 · 전언 · 뒤의 정정 표지 · 본문 연결 · 민감 · 사진. 인물과 행동의
관계처럼 코드가 볼 수 없는 것은 늘 not_checked 다. 표지를 찾지 못한 것은 marker_not_found 이지 「없다」 가 아니다.

**이 모듈은 이미지를 만들지 않고, 만들라고 정하지도 않는다.** decision 이 eligible 이어도 그것은 「후보로
적합하다」 까지다. generation 의 user_selected · image_status · user_approved 는 여기서 늘 false · not_requested ·
false 다 — 사용자가 고르고, 만들고, 승인하는 일은 이 모듈 밖에서 일어난다.

partial · unverified · 전언 · 사진 확인 필요는 review(검토), 민감한 말씀은 held(자동 보류 — 사람이 풀 수 있다)다.
그림 지시문은 eligible 에만 generation_prompt 로, review 에는 검토용 draft_prompt 로 둔다.

**삽화 위치(placement)** 는 장 · 문단 번호와 그 문단의 해시다. 본문이 고쳐지면 번호가 밀리므로 locate 가
해시로 다시 찾는다 — 못 찾으면 장까지만 알려 주고 사람이 다시 정한다. 끼워 넣는 일은 하지 않는다.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any, Callable

PROMPTS = Path(__file__).resolve().parents[2] / "첨부프롬프트_md" / "삽화"
SELECT_FILE = "1_장면선정_v3.md"     # v1 · v2 는 실제 호출(e01 · 2026-11-12) 두 번의 기록으로 남긴다
PERSON_ROLES = ("actor", "co_actor", "recipient", "bystander")
OBJECT_ROLES = ("acted_on", "used")
RELATION_SCOPE = ("코드는 관계 칸이 있는가 · 근거 인용이 그 턴 원문에 글자 그대로 있는가 · 중심 행동에 이어졌는가만 본다. "
                  "그 사람이 정말 그 행동을 했는지(뜻)는 보지 못한다 — 사람이 확인하기 전에는 생성용 지시문에 쓰지 않는다")
STYLE_FILE = "2_그림양식_v1.md"
STYLE_ID = "watercolor-recall-v1"
INPUT_SCHEMA = "illust-input-v1"
RESULT_SCHEMA = "illust-result-v1"

MAX_SCENES = 3               # 초기 실험 기준 — 서비스의 영구 제한이 아니다
KINDS = ("place", "time", "person", "action", "object", "emotion")
MODES = ("SCENE", "SYMBOLIC", "SKIP")
QUOTE_MIN = 4                # 인용의 최소 글자(공백 제외) — 한두 글자는 어디에나 있다
LABEL_MAX, TITLE_MAX, SUMMARY_MAX = 40, 40, 200
PARAPHRASE_COVER = 0.5       # 행동 · 감정 이름의 두 글자 조각이 인용에 이만큼은 있어야 「인용 안의 말」
DUP_OVERLAP = 0.6            # 작은 쪽 장면의 행동 · 사물 · 장소 중 이만큼이 겹치면 같은 장면
ANCHOR_CHARS = 30            # 위치를 사람이 알아볼 수 있게 싣는 문단 첫머리 글자 수
VERIFICATION_MEANING = ("verified · partial · unverified 는 원문 근거를 따라갈 수 있는 정도다. "
                        "사실 검증이 아니다 — 항목별 상태는 scenes[].checks 를 본다")
PROMPT_MAX = 1800

# 원문 표지 — memoir_scene 의 것과 같은 뜻으로 넉넉하게 잡는다 (놓치는 것보다 잘못 켜는 쪽이 낫다)
_NEG = re.compile(r"(?<![가-힣])(안|못)(?=\s|하|했|해|한)|않|없|아니|아닌|아냐|모르|말았")
_HEARD = re.compile(r"대요|래요|다고\s?하더|라고\s?하더|다더라|라더라|다고\s?들었|라고\s?들었|했대|들었는데|들은")
_CORRECT = re.compile(r"아니다|아니고|아니,|아니라|아니에요|잘못 말|잘못 얘기|정정|다시 생각|헷갈|착각|틀렸")
_HEDGE = re.compile(r"것\s?같|나\s?봐|였나|었나|일\s?거|던가|쯤|무렵|남짓|모르겠")
SENSITIVE = re.compile(
    r"죽었|죽은|죽고|죽음|숨지|숨을 거|돌아가셨|돌아가시|세상을 떠|별세|장례|상여|빈소|임종|묘소|산소에|제사"
    r"|사고|다쳤|다치|부상|병원|병환|병이 |병으로|병에 |투병|앓|수술|입원|암이|암으로|암에|암 진단|치매|중풍"
    r"|전쟁|피난|난리|폭격|6\.25|육이오|맞았|때렸|폭력|자살|유산")
_BANNED_LABEL = re.compile(r"사진|실사|초상|닮은|똑같")       # 그림 지시문의 요소 이름에 들어오면 안 되는 말
SELF_WORDS = ("나", "내", "저", "제")     # 원문이 자기를 부른 말 — 그림 지시문에는 SELF_LABEL 로 적는다
SELF_LABEL = "이야기하는 본인(나이 · 생김새를 정하지 않는다)"
# 「저희 집」 처럼 우리를 뜻하는 말은 본인이 그 자리에 있었다는 근거가 아니다 — 넣지 않는다
_SELF_FORMS = "나는|내가|나도|나를|나한테|나에게|내게|나랑|저는|제가|저도|저를|저한테|저에게|제게|저랑"
_SELF_IN_QUOTE = re.compile(rf"(?<![가-힣])({_SELF_FORMS})")
# 인물 요소의 이름이 화자 한 사람을 가리키는 말인가 — 「나 · 저 · 제가 · 내가 · 저는 · 나는 …」.
# 「저희 · 우리 · 우리 어머니 · 저희 집」 은 여럿이거나 다른 대상이다 — 화자 한 사람으로 바꾸지 않는다.
_SELF_NAME = re.compile(rf"^(?:나|내|저|제|{_SELF_FORMS})$")
# 「형이랑 둘이」 · 「아버지랑 저랑 둘이서」 — 함께 했다는 말. 가운데 한 사람(「저랑」)은 앞을 내다보기만 하고 지우지 않는다 —
# 「아버지랑 오빠랑 셋이」 에서 오빠도 따로 찾을 수 있게
_WITH = r"(?:이?랑|와|과|하고)(?=\s?(?:[가-힣]{1,3}(?:이?랑|와|과|하고)\s?)?(?:둘이|셋이|같이|함께))"
OMISSION_SCOPE = ("코드는 이 장면이 쓴 턴의 원문에서 「호칭(KIN 목록) + 랑 · 와 · 과 · 하고 (+ 한 사람 더 + 랑 · 와 …) + 둘이 · 셋이 · 같이 · 함께」 꼴만 찾아, "
                  "그 호칭이 인물 요소에 없으면 알려 준다. 그 밖의 꼴(이름 · 다른 문장으로 이어진 주어 · 「우리가」)은 찾지 못한다 — "
                  "알림이 없다고 빠진 사람이 없는 것이 아니다. 사람이 원문 문맥을 읽고 정한다")




def _age_hedges(text: str) -> list[str] | None:
    """
    글 안의 추정 표지가 **모두 나이 · 연도 표현에 바로 붙어 있으면** 그 나이들을, 하나라도 아니면 None.

        「제가 여섯 살쯤 되던 해였는데」  → ["여섯살"]      「쯤」 이 나이에 붙었다
        「열 살쯤이었나」                 → ["열살"]        「쯤」 · 「이었나」 둘 다 나이에 붙었다
        「형이었나」 · 「날랐던 것 같다」  → None           사람 · 행동이 불확실하다 — 좁은 규칙으로 풀지 않는다
        「여섯 살쯤 형이랑 간 것 같아요」  → None           나이 말고 다른 것에도 표지가 있다
    """
    ages = []
    for m in _HEDGE.finditer(text):
        before = text[:m.start()].rstrip()
        if m.group(0) in ("였나", "었나"):                 # 「여섯 살쯤이었나」 · 「여섯 살이었나」
            before = re.sub(r"\s?(?:쯤|무렵|남짓)?\s?이?$", "", before)
        elif m.group(0) not in ("쯤", "무렵", "남짓"):
            return None
        am = _AGE_END.search(before)
        if not am:
            return None
        ages.append(_compact(am.group(1)))
    return ages or None


def is_self(text: str) -> bool:
    """인물 요소의 이름이 화자 자신을 가리키는가. 요소의 원래 이름과 인용은 바꾸지 않는다 — 그림 지시문에 적을 때만 SELF_LABEL 로 쓴다."""
    return bool(_SELF_NAME.match(text.strip()))
_CLAUSE = re.compile(r"(?:서|고|며|면서|다가|는데|지만|니까|도)[,\s]+|,\s*")      # 인용을 마디로 나누는 이음 말끝
_HEDGE_TAIL = re.compile(r"쯤|무렵|경|께|남짓|이?었나|였나")                          # 때 바로 뒤에 붙는 불확실 말
_PARTICLE = re.compile(r"[가-힣](을|를|에|로|으로|까지|에서|에게|한테)(?=\s|$)")     # 행동 이름에 목적어 · 방향이 있는가
ACTION_MIN = 6               # 행동 이름의 최소 글자(공백 제외) — 「날랐어」 한 낱말은 그림 지시가 못 된다
_NUM = "한|두|세|네|다섯|여섯|일곱|여덟|아홉|열|스무|서른|마흔|쉰|예순|일흔|여든|아흔"
_SUM_TIME = re.compile(rf"((?:\d+|(?:{_NUM})(?:\s?(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉))?)\s?살|\d{{4}}년)(\s?(?:쯤|무렵|경|께|남짓))?")
_AGE_END = re.compile(rf"((?:\d+|(?:{_NUM})(?:\s?(?:한|두|세|네|다섯|여섯|일곱|여덟|아홉))?)\s?살|\d{{4}}년)$")
# 요약에서 찾는 사람 호칭 — 긴 것부터. 이 목록에 없는 사람(이름 · 이웃 · 직함)은 코드가 보지 못한다
KIN = sorted(["작은누나", "큰누나", "누나", "작은형", "큰형", "형", "작은언니", "큰언니", "언니", "오빠", "동생",
              "어머니", "아버지", "엄마", "아빠", "할머니", "할아버지", "아내", "남편", "아들", "딸", "삼촌", "이모",
              "고모", "친구", "선생님"], key=len, reverse=True)
_KIN_TAIL = r"(?=[이가은는을를와과랑의도께에한들,.\s]|$)"
_AT = r"(?:앞|위|안|옆|가|한가운데)?(?:에서|서)"           # 배경 이름 뒤에 붙어 「거기서 했다」 로 만드는 말
SUMMARY_SCOPE = ("제목 · 요약에 나온 가족 · 친지 호칭(KIN), 나이 · 연도 표현, 「배경 이름 + 에서」 만 요소와 견준다. "
                 "그 밖의 사람 · 행동 · 장소 낱말은 보지 못한다 — 사람이 본다. 빠진 것을 원문에서 채우지 않는다")
_SENT_END = re.compile(r"[.!?…\n]+")

Call = Callable[[str, str], str]     # (system, user) → 모델 응답 글. 이 파일에는 실제 구현이 없다


class IllustError(RuntimeError):
    """kind: input(입력 모양) · model_output(후보 모양) · prompt_file(지시문 파일) · not_approved(모델 호출)."""

    def __init__(self, kind: str, message: str):
        super().__init__(f"{kind}: {message}")
        self.kind, self.message = kind, message


# ---------------------------------------------------------------- 작은 함수

def _compact(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def _bigrams(s: str) -> set[str]:
    c = _compact(s)
    return {c[i:i + 2] for i in range(len(c) - 1)}


def _is_int(v) -> bool:
    return isinstance(v, int) and not isinstance(v, bool)


def _int_list(v) -> bool:
    return isinstance(v, list) and all(_is_int(x) for x in v)


def input_ref(data: dict) -> str:
    raw = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------- 지시문 파일

def _blocks(path: Path) -> dict[str, str]:
    """`## N. 제목` 아래 첫 ``` 블록 → {N: 글}."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        raise IllustError("prompt_file", f"{path.name} 을 읽지 못했다 ({type(e).__name__})") from e
    out: dict[str, str] = {}
    section, buf = None, None
    for line in text.splitlines():
        head = re.match(r"^##\s*(\d+)\.", line)
        if head and buf is None:
            section = head.group(1)
            continue
        if line.startswith("```"):
            if buf is None:
                buf = []
            else:
                if section and section not in out:
                    out[section] = "\n".join(buf).strip()
                buf = None
            continue
        if buf is not None:
            buf.append(line)
    return out


def style_blocks() -> dict[str, str]:
    b = _blocks(PROMPTS / STYLE_FILE)
    missing = [n for n in ("1", "2", "3") if not b.get(n)]
    if missing:
        raise IllustError("prompt_file", f"{STYLE_FILE} 에 §{' · §'.join(missing)} 블록이 없다")
    return {"style": b["1"], "people": b["2"], "negative": b["3"]}


def select_prompt() -> str:
    b = _blocks(PROMPTS / SELECT_FILE)
    if not b.get("1"):
        raise IllustError("prompt_file", f"{SELECT_FILE} 에 §1 블록이 없다")
    return b["1"]


def prompt_hashes() -> dict[str, str]:
    out = {}
    for name in (SELECT_FILE, STYLE_FILE):
        try:
            out[name] = hashlib.sha256((PROMPTS / name).read_bytes()).hexdigest()[:16]
        except OSError:
            out[name] = "missing"
    return out


# ---------------------------------------------------------------- 입력

def _chapters(memoir) -> list[dict]:
    """
    두 모양의 장을 {no, key, title, sentences[{text, turns, para}], paragraphs[글], turns, chapter_turns} 로.
    없는 값을 만들지 않는다 (key 는 있으면만). source_turns 는 문장마다 출처가 없는 원고(수필 한 편 = 이야기 몇 개)가
    장 단위로 아는 출처다 — 있으면만 쓴다.
    """
    def bad(why: str):
        return IllustError("input", why)

    if not isinstance(memoir, dict) or not isinstance(memoir.get("chapters"), list) or not memoir["chapters"]:
        raise bad("memoir.chapters 가 비었거나 목록이 아니다")
    out = []
    for i, ch in enumerate(memoir["chapters"], start=1):
        if not isinstance(ch, dict) or not isinstance(ch.get("paragraphs"), list):
            raise bad(f"{i}번째 장 모양이 다르다")
        title = ch.get("title")
        title = title.get("text") if isinstance(title, dict) else title
        no = ch.get("no", i)
        if not _is_int(no) or not isinstance(title, str):
            raise bad(f"{i}번째 장의 no · title 모양이 다르다")
        sents, paras = [], []
        for pi, para in enumerate(ch["paragraphs"]):
            items = para.get("sentences") if isinstance(para, dict) else para
            if not isinstance(items, list) or not items:
                raise bad(f"{no}장 문단 모양이 다르다")
            for x in items:
                if not isinstance(x, dict) or not isinstance(x.get("text"), str) or not _int_list(x.get("turns", [])):
                    raise bad(f"{no}장 문장 모양이 다르다")
                sents.append({"text": x["text"], "turns": list(x.get("turns", [])), "para": pi})
            paras.append(" ".join(x["text"].strip() for x in items))
        if not sents:
            raise bad(f"{no}장에 문장이 없다")
        if not _int_list(ch.get("source_turns", [])):
            raise bad(f"{no}장 source_turns 모양이 다르다")
        key = ch.get("chapter_key")
        out.append({"no": no, "key": key if isinstance(key, str) else None, "title": title.strip(),
                    "sentences": sents, "paragraphs": paras,
                    "turns": sorted({t for s in sents for t in s["turns"]}),
                    "chapter_turns": sorted(set(ch.get("source_turns", [])))})
    if len({c["no"] for c in out}) != len(out):
        raise bad("장 번호가 겹친다")
    return out


def check_input(data) -> dict:
    """
    입력 모양을 보고 쓰기 좋게 세운다. 고치지 않는다 — 어긋나면 IllustError("input").

    source 가 없으면(null) 실패가 아니다 — 모든 장면이 unverified 가 된다. photos 가 없으면(null) 사진 겹침을
    볼 수 없다는 뜻이고(빈 목록 [] 은 「사진이 없다」), 그 장면들은 review 로 남는다.
    """
    def bad(why: str):
        return IllustError("input", why)

    if not isinstance(data, dict):
        raise bad("입력이 객체가 아니다")
    if data.get("schema_version") != INPUT_SCHEMA:
        raise bad(f"schema_version 이 {INPUT_SCHEMA} 가 아니다")
    chapters = _chapters(data.get("memoir"))

    source = data.get("source")
    utts: dict[int, dict] = {}
    refs: dict[int, dict] = {}
    if source is not None:
        if not isinstance(source, dict) or not isinstance(source.get("utterances"), list) or not source["utterances"]:
            raise bad("source.utterances 가 비었거나 목록이 아니다")
        for u in source["utterances"]:
            if (not isinstance(u, dict) or not _is_int(u.get("turn")) or not isinstance(u.get("elder"), str)
                    or not isinstance(u.get("session_id"), str)):
                raise bad("source.utterances 항목 모양이 다르다")
            utts[u["turn"]] = u
        if sorted(utts) != list(range(1, len(source["utterances"]) + 1)):
            raise bad("source.utterances.turn 이 1부터 차례가 아니다")
        tm = source.get("turn_map")
        if tm is not None:
            if not isinstance(tm, list) or [m.get("global_turn") for m in tm if isinstance(m, dict)] != sorted(utts):
                raise bad("source.turn_map 이 utterances 와 맞지 않는다")
            for m in tm:
                if m.get("session_id") != utts[m["global_turn"]]["session_id"] or not _is_int(m.get("turn")):
                    raise bad("source.turn_map 의 회차 · 턴이 utterances 와 다르다")
                refs[m["global_turn"]] = {"session_id": m["session_id"], "session_turn": m["turn"]}
        cited = {t for c in chapters for t in c["turns"] + c["chapter_turns"]}
        if not cited <= set(utts):
            raise bad(f"자서전 문장이 원문에 없는 턴을 근거로 든다 {sorted(cited - set(utts))[:5]}")

    photos = data.get("photos")
    if photos is not None:
        if not isinstance(photos, list):
            raise bad("photos 가 목록이 아니다")
        for p in photos:
            if (not isinstance(p, dict) or not isinstance(p.get("photo_id"), str)
                    or not (p.get("session_id") is None or isinstance(p["session_id"], str))
                    or not (p.get("clues") is None or isinstance(p["clues"], dict))
                    or not _int_list(p.get("turns", []))):
                raise bad("photos 항목 모양이 다르다")
            if utts and not set(p.get("turns", [])) <= set(utts):
                raise bad(f"사진 {p['photo_id']} 의 turns 가 원문에 없다")
    return {"chapters": {c["no"]: c for c in chapters}, "utts": utts, "refs": refs, "photos": photos,
            "has_source": source is not None}


# ---------------------------------------------------------------- 모델 자료 · 후보 모양

def scope(data: dict, only: list | None = None) -> dict:
    """
    모델에 보낼 범위. only 는 장 번호(int) 또는 장 식별자(str) 목록 — 없으면 책 전체다.
    보내는 원문은 그 장들이 근거로 쓰는 턴(문장의 turns + 장의 source_turns)뿐이다. 없는 장을 고르면 실패다.
    출처 턴이 하나도 없는 장을 범위로 고르면 원문을 보낼 수 없다 — 그것도 실패다 (통째로 보내지 않는다).
    """
    ctx = check_input(data)
    chapters = list(ctx["chapters"].values())
    if only is not None:
        picked = [c for c in chapters if c["no"] in only or (c["key"] is not None and c["key"] in only)]
        if len(picked) != len(only):
            raise IllustError("input", f"범위로 고른 장을 찾지 못했다 {only}")
        chapters = picked
        turns = sorted({t for c in chapters for t in c["turns"] + c["chapter_turns"]})
        if ctx["has_source"] and not turns:
            raise IllustError("input", "고른 장에 출처 턴이 없어 보낼 원문을 정할 수 없다")
    else:
        turns = sorted(ctx["utts"])
    return {"chapters": chapters, "turns": turns, "ctx": ctx, "whole_book": only is None}


def select_message(data: dict, only: list | None = None) -> str:
    """모델에 줄 자료 메시지. 원문은 시스템 지시에 박지 않고 여기에만 싣는다. 사진은 단서(관찰)만 준다."""
    sc = scope(data, only)
    ctx, turns = sc["ctx"], set(sc["turns"])
    payload = {
        "max_scenes": MAX_SCENES,
        "chapters": [{"chapter_no": c["no"], "title": c["title"], "source_turns": c["chapter_turns"],
                      "sentences": [{"text": x["text"], "turns": x["turns"]} for x in c["sentences"]]}
                     for c in sc["chapters"]],
        "utterances": [{"turn": t, "asked": u.get("asked", ""), "elder": u["elder"]}
                       for t, u in sorted(ctx["utts"].items()) if t in turns],
        "photo_clues": [{"turns": p.get("turns", []), "clues": p.get("clues")} for p in ctx["photos"] or []
                        if sc["whole_book"] or set(p.get("turns", [])) & turns],
    }
    return "[자료]\n" + json.dumps(payload, ensure_ascii=False, indent=1)


def call_model(system: str, user: str) -> str:
    """실제 모델 호출 자리. 1차 구현에는 없다 — 유료 호출은 따로 승인받는다."""
    raise IllustError("not_approved", "실제 모델 호출은 아직 승인되지 않았다 — 모의 응답(call)을 넘겨 쓴다")


def check_candidates(out) -> list[dict]:
    """모델(모의) 응답의 모양. 어긋나면 IllustError("model_output") — 맞춰 주지 않는다."""
    def bad(why: str):
        return IllustError("model_output", why)

    if isinstance(out, str):
        try:
            out = json.loads(out)
        except json.JSONDecodeError as e:
            raise bad(f"JSON 이 아니다 ({e.msg})") from e
    if not isinstance(out, dict) or not isinstance(out.get("candidates"), list):
        raise bad("candidates 목록이 없다")
    for i, c in enumerate(out["candidates"]):
        w = f"candidates[{i}]"
        if not isinstance(c, dict):
            raise bad(f"{w} 가 객체가 아니다")
        if not _is_int(c.get("chapter_no")):
            raise bad(f"{w}.chapter_no 가 정수가 아니다")
        for k, mx in (("scene_title", TITLE_MAX), ("scene_summary", SUMMARY_MAX)):
            if not isinstance(c.get(k), str) or not c[k].strip() or len(c[k]) > mx:
                raise bad(f"{w}.{k} 가 비었거나 {mx}자를 넘는다")
        if c.get("importance") not in ("main", "minor") or not isinstance(c.get("reason"), str):
            raise bad(f"{w}.importance · reason 모양이 다르다")
        if not isinstance(c.get("elements"), list) or not c["elements"]:
            raise bad(f"{w}.elements 가 비었다")
        for j, e in enumerate(c["elements"]):
            if (not isinstance(e, dict) or e.get("kind") not in KINDS or not _is_int(e.get("turn"))
                    or not isinstance(e.get("text"), str) or not e["text"].strip() or len(e["text"]) > LABEL_MAX
                    or not isinstance(e.get("quote"), str)):
                raise bad(f"{w}.elements[{j}] 모양이 다르다")
            if "role" in e and e["role"] is not None and (e["kind"] != "place" or e["role"] not in ("setting", "spot")):
                raise bad(f"{w}.elements[{j}].role 은 place 에만, setting 또는 spot 이다")
            if e.get("key") is not None and (not isinstance(e["key"], str) or not 0 < len(e["key"]) <= 12):
                raise bad(f"{w}.elements[{j}].key 모양이 다르다")
            rel = e.get("relation")
            if rel is not None:
                roles = PERSON_ROLES if e["kind"] == "person" else OBJECT_ROLES if e["kind"] == "object" else ()
                if (not isinstance(rel, dict) or not isinstance(rel.get("action"), str) or rel.get("role") not in roles
                        or not isinstance(rel.get("evidence"), list)
                        or not all(isinstance(v, dict) and _is_int(v.get("turn")) and isinstance(v.get("quote"), str)
                                   for v in rel["evidence"])):
                    raise bad(f"{w}.elements[{j}].relation 모양이 다르다 (person · object 에만 · action · role · evidence)")
        keys = [e["key"] for e in c["elements"] if e.get("key") is not None]
        if len(set(keys)) != len(keys):
            raise bad(f"{w}.elements 의 key 가 겹친다")
        if c.get("central_action") is not None and not isinstance(c["central_action"], str):
            raise bad(f"{w}.central_action 이 글이 아니다")
    return out["candidates"]


# ---------------------------------------------------------------- 원문 대조

def _quote_sentences(elder: str, quote: str) -> tuple[str, list[int]] | None:
    """인용이 원문에 글자 그대로(공백 무시) 있으면 (그 인용이 걸친 문장들, 그 턴 안의 문장 번호들)을, 없으면 None."""
    ce, cq = _compact(elder), _compact(quote)
    at = ce.find(cq)
    if len(cq) < QUOTE_MIN or at < 0:
        return None
    hit, idx, pos = [], [], 0
    for i, sent in enumerate(s for s in _SENT_END.split(elder) if s.strip()):
        n = len(_compact(sent))
        start = ce.find(_compact(sent), pos)
        start = pos if start < 0 else start
        if start < at + len(cq) and at < start + n:
            hit.append(sent.strip())
            idx.append(i)
        pos = start + n
    return (" ".join(hit) or elder), idx


def _negation_scope(label: str, quote: str) -> str | None:
    """
    인용 안의 부정이 어디에 걸리는가 — 낱말과 마디로만 본다.

        None     인용에 부정이 없다
        final    마지막 마디(문장의 서술)가 부정이다 — 「장화는 없었어요」 「형들 몫은 안 남기셨어요」 → 그 요소는 일어나지 않았다
        partial  앞 마디에 부정이 있고 마지막 마디는 긍정이다 — 「얼마 못 가서 / 길가에 내려놓고 / 쉬어야 했어요」.
                 하지 못한 것(멀리 가기)과 실제로 한 것(내려놓고 쉬기)이 함께 있다. 어느 쪽을 그리는지는 코드가 모른다 → 쓰되 사람이 본다
    요소 이름이 부정된 마디의 말로만 되어 있으면(이름에 부정이 없는데 부정 마디와 더 많이 겹치면) final 로 본다.
    """
    if not _NEG.search(quote):
        return None
    cuts = [m.end() for m in _CLAUSE.finditer(quote)]
    clauses = [quote[a:b] for a, b in zip([0] + cuts, cuts + [len(quote)]) if quote[a:b].strip()]
    if not clauses or _NEG.search(clauses[-1]):
        return "final"
    if _NEG.search(label):
        return "partial"
    neg = "".join(c for c in clauses if _NEG.search(c))
    rest = "".join(c for c in clauses if not _NEG.search(c))
    lb = _bigrams(label)
    return "final" if len(lb & _bigrams(neg)) >= len(lb & _bigrams(rest)) else "partial"


def _element(e: dict, n: int, ctx: dict) -> dict:
    """
    요소 하나의 상태.

        quoted       인용이 원문에 있고 요소 이름도 인용 안의 말이다
        paraphrased  인용은 있으나 이름이 인용의 말이 아니다 (바꿔 말함 — 뜻이 달라졌을 수 있다)
        blocked      인용의 서술이 부정이다 (「장화는 없었어요」 의 장화) · 때의 불확실 말을 지웠다(certainty_raised)
        rejected     턴이 없거나 인용이 그 턴 원문에 없다
        unchecked    원문이 주어지지 않아 대조하지 못했다
    flags: hearsay(전언 — 버리지 않고 표시한다 · 장면은 검토로 간다) · uncertain(불확실 — 때에는 그대로 쓴다) ·
           negation_partial_scope(인용 앞 마디에 부정, 마지막 마디는 긍정 — 쓰되 검토) ·
           negation_nearby · hearsay_nearby · uncertain_nearby(인용 밖, 같은 문장에 표지가 있다 — 쓰되 검토로 간다) ·
           possible_later_correction(같은 회차의 뒤 말씀에 정정하는 말과 이 요소의 이름이 함께 있다)
    """
    out = {"id": f"e{n}", "kind": e["kind"], "text": e["text"].strip(), "turn": e["turn"],
           "quote": e["quote"].strip(), "status": "unchecked", "flags": [], "source_sentences": [],
           "key": e.get("key")}
    if e["kind"] == "place":
        out["role"] = e.get("role") or "setting"      # 적지 않았으면 배경으로 본다 — 행동의 자리로 단정하지 않는다
    if not ctx["has_source"]:
        return out
    u = ctx["utts"].get(e["turn"])
    found = _quote_sentences(u["elder"], e["quote"]) if u else None
    sents = found[0] if found else None
    if sents is None:
        out["status"] = "rejected"
        out["flags"].append("turn_missing" if not u else "quote_not_in_source")
        return out
    out["source_sentences"] = found[1]
    label, quote = _compact(out["text"]), _compact(out["quote"])
    inside = label in quote
    if e["kind"] == "person":
        out["is_self"] = is_self(out["text"])
        if out["is_self"]:
            # 이름이 「나」 인데 원문은 「제가」 일 수 있다 — 인용에 화자 한 사람을 가리키는 말이 있어야 본인이다.
            # 「저희 집」 처럼 여럿을 뜻하는 말만 있으면 본인이 그 자리에 있었다는 근거가 아니다
            inside = bool(_SELF_IN_QUOTE.search(out["quote"]))
    if not inside and e["kind"] in ("action", "emotion"):          # 말끝이 바뀌는 낱말은 조각으로 본다
        lb = _bigrams(label)
        inside = bool(lb) and len(lb & _bigrams(quote)) / len(lb) >= PARAPHRASE_COVER
    out["status"] = "quoted" if inside else "paraphrased"
    # 표지가 인용 안에 있으면 그 요소의 것이다. 같은 문장의 다른 곳에만 있으면 어느 말에 걸리는지 코드가
    # 모른다(「둘이 메고도 얼마 못 가서」 의 「못」 은 메는 일이 아니라 가는 일에 걸린다) — 막지 않고 표시만 한다.
    neg = _negation_scope(out["text"], out["quote"])
    if neg == "final":
        out["status"] = "blocked"
        out["flags"].append("negation_in_source")
    elif neg == "partial":
        out["flags"].append("negation_partial_scope")
    elif _NEG.search(sents):
        out["flags"].append("negation_nearby")
    for rx, flag in ((_HEARD, "hearsay"), (_HEDGE, "uncertain")):
        if rx.search(out["quote"]):
            out["flags"].append(flag)
        elif rx.search(sents):
            out["flags"].append(flag + "_nearby")
    if "uncertain" in out["flags"] or "uncertain_nearby" in out["flags"]:
        # 표지는 지우지 않는다. 그 추정이 나이에만 붙은 것인지 적어 둘 뿐이다 — 풀지 말지는 _judge 가 장면 전체를 보고 정한다
        ages = _age_hedges(out["quote"] if "uncertain" in out["flags"] else sents)
        out["hedge_scope"] = {"kind": "age_expression", "ages": ages} if ages else {"kind": "other", "ages": []}
    if e["kind"] == "time" and out["status"] == "quoted":
        # 원문이 「여섯 살쯤」 인데 이름이 「여섯 살」 이면 확실하지 않은 것을 확실하게 만든 것이다 — 쓰지 않는다
        ce = _compact(u["elder"])
        at = ce.find(quote)
        hedged = _HEDGE.search(out["quote"]) or _HEDGE_TAIL.match(ce[at + len(quote): at + len(quote) + 3])
        if hedged and not (_HEDGE.search(out["text"]) or _HEDGE_TAIL.search(out["text"])):
            out["status"] = "blocked"
            out["flags"].append("certainty_raised")
    if _BANNED_LABEL.search(out["text"]):
        out["status"] = "blocked"
        out["flags"].append("banned_label")
    if len(label) >= 2 and any(t > e["turn"] and v["session_id"] == u["session_id"] and _CORRECT.search(v["elder"])
                               and label in _compact(v["elder"]) for t, v in ctx["utts"].items()):
        out["flags"].append("possible_later_correction")
    return out


def _usable(e: dict) -> bool:
    """
    그림 지시문(초안 포함)에 쓸 수 있는가. 전언 · 불확실 · 정정 표지가 있어도 쓰되, 그 장면은 검토로 간다 (_judge).
    불확실하다고 요소를 버리면 안 된다 — 「제가 여섯 살쯤」 의 「쯤」 때문에 본인이 그림에서 빠지면 그것이 왜곡이다.
    """
    return e["status"] == "quoted"


def _para_hash(text: str) -> str:
    return hashlib.sha256(_compact(text).encode("utf-8")).hexdigest()[:16]


def _placement(ch: dict | None, turns: list[int], els: list[dict]) -> dict | None:
    """
    삽화를 둘 자리 — 장 + 문단. 끼워 넣지 않는다, 자리만 가리킨다.

        basis turns        그 문단의 문장들이 이 장면의 턴을 근거로 쓴다 (가장 많이 쓰는 첫 문단)
              label_match  문장에 출처 턴이 없어, 요소 이름이 가장 많이 나오는 문단을 골랐다 — 어림이다
              chapter_only 문단을 고를 근거가 없다 — paragraph_index 는 null
    anchor 는 그 문단의 첫머리와 해시(공백 무시)다. 본문이 바뀌면 locate 가 해시로 다시 찾는다.
    """
    if ch is None:
        return None
    n = len(ch["paragraphs"])
    score = [sum(1 for s in ch["sentences"] if s["para"] == i and set(s["turns"]) & set(turns)) for i in range(n)]
    basis = "turns"
    if not any(score):
        names = [_compact(e["text"]) for e in els
                 if e["kind"] in ("object", "place", "person") and len(_compact(e["text"])) >= 2]
        score = [sum(1 for w in names if w in _compact(p)) for p in ch["paragraphs"]]
        basis = "label_match"
    base = {"chapter_no": ch["no"], "chapter_key": ch["key"], "chapter_title": ch["title"], "paragraph_count": n,
            "chapter_hash": _para_hash("".join(ch["paragraphs"]))}
    if not any(score):
        return {**base, "paragraph_index": None, "basis": "chapter_only", "anchor": None,
                "sentence_index": None, "sentence_count": None, "sentence_anchor": None}
    # 같은 점수의 문단이 여럿이면(한 턴을 여러 문단이 근거로 쓴다) 요소 이름이 더 많이 나오는 문단을 고른다
    tie = [_compact(e["text"]) for e in els if e["kind"] in ("object", "place", "person", "action") and len(_compact(e["text"])) >= 2]
    lab = [sum(1 for w in tie if w in _compact(p)) + sum(len(_bigrams(w) & _bigrams(p)) / max(len(_bigrams(w)), 1) for w in tie)
           for p in ch["paragraphs"]]
    i = max(range(n), key=lambda k: (score[k], lab[k], -k))
    # 문단 안의 문장 — 요소 이름이 가장 많이 나오는 문장. 어림이다 (원고의 「문장」 이 여러 문장 묶음일 때 쓴다).
    names = [_compact(e["text"]) for e in els
             if e["kind"] in ("object", "place", "person") and len(_compact(e["text"])) >= 2]
    sents = [x for x in ch["sentences"] if x["para"] == i]
    hit = [sum(1 for w in names if w in _compact(x["text"])) for x in sents]
    j = hit.index(max(hit)) if any(hit) else None
    return {**base, "paragraph_index": i, "basis": basis,
            "anchor": {"text": ch["paragraphs"][i][:ANCHOR_CHARS], "hash": _para_hash(ch["paragraphs"][i])},
            "sentence_index": j, "sentence_count": len(sents),
            "sentence_anchor": None if j is None else {"text": sents[j]["text"][:ANCHOR_CHARS],
                                                       "hash": _para_hash(sents[j]["text"])}}


def locate(memoir: dict, placement: dict | None) -> dict:
    """
    (고쳐졌을 수도 있는) 자서전에서 placement 의 문단을 다시 찾는다. 끼워 넣지는 않는다.

        exact         같은 장 · 같은 번호 · 같은 글이다
        moved         번호가 밀렸거나 장이 바뀌었지만 같은 글의 문단이 하나 있다 → 새 자리를 돌려준다
        chapter_only  그 문단의 글이 바뀌었다(또는 처음부터 문단을 못 골랐다) → 장만 안다. 사람이 다시 정한다
        lost          그 장도 찾지 못했다
    """
    chapters = _chapters(memoir)
    if not placement:
        return {"state": "lost", "chapter_no": None, "paragraph_index": None}
    same = [c for c in chapters if (placement.get("chapter_key") and c["key"] == placement["chapter_key"])
            or (not placement.get("chapter_key") and c["no"] == placement["chapter_no"]
                and c["title"] == placement.get("chapter_title"))]
    home = same[0] if same else None
    anchor = placement.get("anchor")
    if anchor:
        i = placement["paragraph_index"]
        if home and i < len(home["paragraphs"]) and _para_hash(home["paragraphs"][i]) == anchor["hash"]:
            return {"state": "exact", "chapter_no": home["no"], "paragraph_index": i}
        hits = [(c["no"], j) for c in chapters for j, p in enumerate(c["paragraphs"]) if _para_hash(p) == anchor["hash"]]
        in_home = [h for h in hits if home and h[0] == home["no"]]
        pick = in_home if len(in_home) == 1 else hits if len(hits) == 1 else []
        if pick:
            return {"state": "moved", "chapter_no": pick[0][0], "paragraph_index": pick[0][1]}
    if home:
        return {"state": "chapter_only", "chapter_no": home["no"], "paragraph_index": None}
    return {"state": "lost", "chapter_no": None, "paragraph_index": None}


def _summary_check(summary: str, ok: list[dict], els: list[dict], mode: str, ctx: dict, title: str = "") -> dict:
    """
    요약(모델이 쓴 글)에 있는 사람 · 때가 그림 지시문에 들어갈 요소에 있는가. 범위는 SUMMARY_SCOPE.
    요약은 지시문에 쓰이지 않는다 — 여기서 찾는 것은 「모델이 알고도 요소로 내지 않은 것」 의 흔적이다.
    """
    if not ctx["has_source"]:
        return {"state": "not_checked", "persons_not_in_elements": [], "time_not_in_elements": [],
                "certainty_raised": [], "title_certainty_raised": [], "setting_as_spot": [], "scope": SUMMARY_SCOPE}
    people = [_compact(e["text"]) for e in ok if e["kind"] == "person"]
    rest, missing = summary, []
    if mode == "SCENE":                               # 상징 그림에는 사람을 그리지 않는다
        for term in KIN:
            if re.search(term + _KIN_TAIL, rest):
                rest = re.sub(term + _KIN_TAIL, " ", rest)
                if not any(term in p for p in people):
                    missing.append(term)
    times = [_compact(e["text"]) for e in ok if e["kind"] == "time"]
    said = [_compact(ctx["utts"][t]["elder"]) for t in sorted({e["turn"] for e in els}) if t in ctx["utts"]]
    no_time, raised = [], []
    for m in _SUM_TIME.finditer(summary):
        core = _compact(m.group(1))
        if not any(core in t for t in times):
            no_time.append(m.group(0).strip())
        hedged_src = any(_HEDGE_TAIL.match(ce[at + len(core): at + len(core) + 3])
                         for ce in said for at in [ce.find(core)] if at >= 0)
        if hedged_src and not m.group(2):
            raised.append(m.group(0).strip())
    t_raised = []
    for m in _SUM_TIME.finditer(title):               # 제목의 「여섯 살에」 — 원문은 「여섯 살쯤」
        core = _compact(m.group(1))
        if not m.group(2) and any(_HEDGE_TAIL.match(ce[at + len(core): at + len(core) + 3])
                                  for ce in said for at in [ce.find(core)] if at >= 0):
            t_raised.append(m.group(0).strip())
    # 배경을 행동의 자리로 바꿔 쓴 말 — 「읍내 장터 앞에서 날랐다」. 배경(setting) 이름 바로 뒤에 「에서」 가 붙고,
    # 그 말이 원문에 그대로 있지 않을 때만 잡는다. 원문에 같은 말이 있으면(다른 행동의 자리일 수 있다) 코드는 모른다.
    as_spot = []
    for e in ok:
        if e["kind"] == "place" and e.get("role", "setting") == "setting":
            name = r"\s?".join(re.escape(w) for w in e["text"].split())
            for where, text in (("title", title), ("summary", summary)):
                for m in re.finditer(name + r"\s?" + _AT, text):
                    if not any(_compact(m.group(0)) in ce for ce in said):
                        as_spot.append({"where": where, "text": m.group(0)})
    found = missing or no_time or raised or t_raised or as_spot
    return {"state": "found" if found else "marker_not_found",
            "persons_not_in_elements": missing, "time_not_in_elements": no_time, "certainty_raised": raised,
            "title_certainty_raised": t_raised, "setting_as_spot": as_spot, "scope": SUMMARY_SCOPE}


def relation_id(chapter: tuple, person: str, proposed: dict | None, central: dict | None,
                evidence: list[dict], source: dict[int, str], *,
                element_quote: dict | None = None, provenance: dict | None = None) -> str:
    """
    사람이 확인한 관계를 다음 실행에서 다시 알아보는 값. **사람이 본 것 가운데 하나라도 달라지면 값이 달라진다** —
    오래된 확인이 새 관계에 붙지 않게.

        장(번호 · 식별자) · 사람 이름 · 모델이 연결한 행동과 역할 · 인물 요소의 인용 ·
        그릴 행동(이름 · 턴 · 인용) · 근거 인용들(턴 · 글) · 원문 전체 · 회차와 원래 턴 번호
    식별 규격 2부터 이 항목들을 함께 묶는다. 이전 식별값의 확인 기록은 unused 로 남는다.
    """
    turns = sorted({v["turn"] for v in evidence} | ({central["turn"]} if central else set()))
    if element_quote is not None:
        turns = sorted(set(turns) | {element_quote["turn"]})
    raw = json.dumps([
        "relation-v2", list(chapter), _compact(person),
        None if proposed is None else [proposed.get("action"), proposed.get("role")],
        None if element_quote is None else [element_quote["turn"], _compact(element_quote["quote"])],
        None if central is None else [_compact(central["text"]), central["turn"], _compact(central["quote"])],
        sorted((v["turn"], _compact(v["quote"])) for v in evidence),
        [hashlib.sha256(source.get(t, "").encode("utf-8")).hexdigest() for t in turns],
        [(t, (provenance or {}).get(t)) for t in turns],
    ], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def scene_review_id(chapter: tuple, central: dict | None, people: list[dict], turns: list[int],
                    source: dict[int, str], provenance: dict | None = None) -> str:
    """
    「이 장면의 참여자가 빠짐없이 들었다」 는 사람의 판단을 다음 실행에서 다시 알아보는 값.
    **사람이 본 후보의 내용에 묶인다** — 그릴 행동 · 제안된 사람들(이름 · 역할 · 인용 · 근거) · 그 턴의 원문 가운데
    하나라도 달라지면 값이 달라진다. 사람을 넣거나 빼면 앞의 「누락 없음」 은 따라오지 않는다.
    """
    raw = json.dumps([
        "scene-v1", list(chapter),
        None if central is None else [_compact(central["text"]), central["turn"], _compact(central["quote"])],
        sorted([_compact(r["text"]), (r["proposed"] or {}).get("action"), (r["proposed"] or {}).get("role"),
                r["element_quote"]["turn"], _compact(r["element_quote"]["quote"]),
                sorted((v["turn"], _compact(v["quote"])) for v in ((r["proposed"] or {}).get("evidence") or []))]
               for r in people),
        [(t, hashlib.sha256(source.get(t, "").encode("utf-8")).hexdigest(), (provenance or {}).get(t)) for t in turns],
    ], ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]


def _omission_hints(people: list[dict], turns: list[int], ctx: dict) -> list[dict]:
    """원문에 「○○랑 둘이」 꼴로 나오는데 인물 요소에 없는 호칭. 알림일 뿐이다 — 범위는 OMISSION_SCOPE."""
    have = [_compact(r["text"]) for r in people]
    hints = []
    for t in turns:
        elder = ctx["utts"][t]["elder"] if t in ctx["utts"] else ""
        for sent in (x.strip() for x in _SENT_END.split(elder) if x.strip()):
            rest = sent
            for term in KIN:
                if re.search(term + _WITH, rest):
                    rest = re.sub(term + _WITH, " ", rest)
                    if not any(term in h for h in have):
                        hints.append({"turn": t, "name": term, "quote": sent})
    return hints


def _relations(c: dict, els: list[dict], ok: list[dict], ctx: dict, confirmed: dict) -> dict:
    """
    그릴 행동 하나(central)와, 사람 · 사물이 그 행동에 어떻게 걸리는지. 범위는 RELATION_SCOPE.

    세 가지를 섞지 않는다.
        proposed  모델이 낸 관계 그대로 (없으면 null — v1 · v2 응답)
        code      missing(관계 칸 없음) · evidence_missing(근거 인용 없음) · evidence_not_found(인용이 원문에 없음) ·
                  other_action(중심 행동이 아닌 행동에 이음) · structure_ok(칸이 있고 인용이 원문에 있고 중심 행동에 이어짐)
        human     not_reviewed · confirmed · rejected — confirmed 는 사람이 확인해 넘겨준 것에서만 온다
    structure_ok 는 뜻이 맞다는 말이 아니다. 인용이 원문과 글자까지 같아도 관계는 틀릴 수 있다.
    """
    raw = {e["id"]: src for e, src in zip(els, c["elements"])}
    acts = [e for e in ok if e["kind"] == "action"]
    want = c.get("central_action")
    central, state = None, "none"
    if want is not None:
        central = next((e for e in acts if e["key"] == want), None)
        state = "declared" if central else "invalid"
    elif len(acts) == 1:
        central, state = acts[0], "implicit_single"
    elif acts:
        state = "missing"
    rows = []
    for e in ok:
        if e["kind"] not in ("person", "object"):
            continue
        rel = raw[e["id"]].get("relation")
        evidence = (rel or {}).get("evidence") or []
        matched = [bool(ctx["has_source"] and v["turn"] in ctx["utts"]
                        and _quote_sentences(ctx["utts"][v["turn"]]["elder"], v["quote"])) for v in evidence]
        if rel is None:
            code = "missing"
        elif not evidence:
            code = "evidence_missing"
        elif not all(matched):
            code = "evidence_not_found"
        elif central is None or rel["action"] != central["key"]:
            code = "other_action"
        else:
            code = "structure_ok"
        ch = ctx["chapters"].get(c["chapter_no"])
        rid = relation_id((c["chapter_no"], ch["key"] if ch else None), e["text"], rel, central,
                          evidence or [{"turn": e["turn"], "quote": e["quote"]}],
                          {t: u["elder"] for t, u in ctx["utts"].items()},
                          element_quote={"turn": e["turn"], "quote": e["quote"]},
                          provenance={t: {"session_id": u["session_id"], "source_ref": ctx["refs"].get(t)}
                                      for t, u in ctx["utts"].items()})
        human = confirmed.get(rid, "not_reviewed") if e["kind"] == "person" else "not_required"
        rows.append({"element": e["id"], "kind": e["kind"], "text": e["text"], "relation_id": rid,
                     "proposed": rel, "element_quote": {"turn": e["turn"], "quote": e["quote"]},
                     "code": {"state": code, "evidence_matched": sum(matched), "evidence_total": len(evidence)},
                     "human": human})
    return {"central": central, "state": state, "rows": rows,
            "others": [e["id"] for e in acts if central is not None and e is not central]}


def _photo_check(els: list[dict], turns: list[int], ctx: dict) -> dict:
    """
    사진 겹침 — 보수적으로.

        confirmed          사람이 그 턴에 이은 사진(photos[].turns)이 있다 → 실제 사진으로 표현할 수 있다
        possible_overlap   같은 회차 사진의 단서에 이 장면의 사물 · 장소 말이 있다 → 확인 필요
        same_session       같은 회차에 어느 턴에도 이어지지 않은 사진이 있을 뿐이다 → 확인 필요 (SKIP 이 아니다)
        none               이 장면의 회차에 사진이 없다
        not_provided       사진 목록을 받지 못했다 → 확인 필요
    """
    if ctx["photos"] is None:
        return {"state": "not_provided", "photos": []}
    sessions = {ctx["utts"][t]["session_id"] for t in turns if t in ctx["utts"]}
    labels = [_compact(e["text"]) for e in els if e["kind"] in ("object", "place") and len(_compact(e["text"])) >= 2]
    found, state = [], "none"
    rank = {"none": 0, "same_session": 1, "possible_overlap": 2, "confirmed": 3}
    for p in ctx["photos"]:
        if set(p.get("turns", [])) & set(turns):
            s, why = "confirmed", "linked_turns"
        elif p.get("turns"):
            continue                                  # 사람이 다른 턴에 이은 사진이다 — 이 장면의 것이 아니다
        elif p.get("session_id") in sessions and p.get("session_id") is not None:
            clues = p.get("clues") or {}
            seen = [_compact(str(x)) for x in [clues.get("scene", ""), *(clues.get("objects") or [])] if x]
            match = sorted({e["text"] for e in els if e["kind"] in ("object", "place")
                            for c in seen if _compact(e["text"]) in labels
                            and (_compact(e["text"]) in c or (len(c) >= 2 and c in _compact(e["text"])))})
            s, why = ("possible_overlap", "clue_words:" + ",".join(match)) if match else ("same_session", "same_session")
        else:
            continue
        found.append({"photo_id": p["photo_id"], "relation": s, "why": why})
        state = s if rank[s] > rank[state] else state
    return {"state": state, "photos": found}


# ---------------------------------------------------------------- 그림 지시문

PEOPLE_OPEN = "- 인물(행동과의 관계를 사람이 확인하기 전 — 생성에 쓰지 않는다): "
PEOPLE_INCOMPLETE = "- 인물(빠진 참여자가 없는지 사람이 확인하기 전 — 생성에 쓰지 않는다): "


_AGE_NUM = {"한": 1, "두": 2, "세": 3, "네": 4, "다섯": 5, "여섯": 6, "일곱": 7, "여덟": 8, "아홉": 9, "열": 10,
            "스무": 20, "서른": 30, "마흔": 40, "쉰": 50, "예순": 60, "일흔": 70, "여든": 80, "아흔": 90}
CHILD_MAX_AGE = 12           # 이 나이까지는 지시문에 「어린아이」 라고 적는다 — 나이에서 따라 나오는 말이다


def self_age(els: list[dict]) -> dict | None:
    """
    화자의 그때 나이 — 「제가 여섯 살쯤 되던 해였는데」 처럼 **화자를 가리키는 인용 안에** 나이가 있고, 그 나이가 때 요소로도
    들어 있을 때만. 돌려주는 글은 때 요소의 이름 그대로다(「여섯 살쯤」 — 추정 표현을 지운 적이 없다).
    그렇지 않으면 None 이고 화자 표시는 「나이 · 생김새를 정하지 않는다」 그대로다.
    """
    for person in els:
        if person["kind"] != "person" or not is_self(person["text"]):
            continue
        for t in els:
            m = _SUM_TIME.search(t["text"]) if t["kind"] == "time" else None
            if not m or "살" not in m.group(1) or _compact(m.group(1)) not in _compact(person["quote"]):
                continue
            head = re.match(rf"(\d+|{_NUM})", m.group(1).strip())
            num = None if not head else int(head.group(1)) if head.group(1).isdigit() else _AGE_NUM.get(head.group(1))
            tail = re.match(rf"(?:{_NUM})\s?(한|두|세|네|다섯|여섯|일곱|여덟|아홉)", m.group(1).strip())
            if num is not None and tail:
                num += _AGE_NUM[tail.group(1)]
            return {"text": t["text"].strip(), "time_element": t["id"], "person_element": person["id"],
                    "child": num is not None and num <= CHILD_MAX_AGE}
    return None


FOCUS_OTHER_THINGS = "위에 적은 것 말고 탈것 · 도구 · 시설 · 건물 같은 사물을 새로 넣거나 주요 소재로 키우지 않는다"


def build_prompt(mode: str, els: list[dict], unconfirmed: bool = False, incomplete: bool = False,
                 together: bool = False, focus: dict | None = None) -> dict:
    """
    확인된 요소(els)와 고정 양식만으로 조립한다. 모델이 쓴 문장(scene_summary · reason)은 넣지 않는다.

    focus — (선택) 그 그림의 중심 소재와 배경. {"center": [이름], "background": [이름], "landscape": bool}
    주면 중심 소재를 화면의 주제로 적고, 배경은 보조로만 두라고 적는다(구도의 선택이다 — 원문 사실이 아니다).
    없으면 앞선 판과 같은 글이 나온다.
    """
    blocks = style_blocks()
    focus = focus if focus and focus.get("center") else None
    center = [c for c in (focus or {}).get("center", [])]
    age = self_age(els) if mode == "SCENE" else None
    # 화자의 나이가 원문에 있으면 「나이를 정하지 않는다」 고 적지 않는다 — 「때: 여섯 살쯤」 과 어긋난다
    me = SELF_LABEL if not age else (f"이야기하는 본인({age['text']}의 어린아이 · 생김새를 정하지 않는다)" if age["child"]
                                     else f"이야기하는 본인({age['text']} 때 · 생김새를 정하지 않는다)")

    def of(kind: str) -> str:
        names = [me if kind == "person" and is_self(e["text"]) else e["text"]
                 for e in els if e["kind"] == kind]
        return ", ".join(dict.fromkeys(names))

    def places(role: str | None) -> str:
        return ", ".join(dict.fromkeys(e["text"] for e in els
                                       if e["kind"] == "place" and (role is None or e.get("role", "setting") == role)))

    time, people = of("time"), of("person")
    setting = places("setting") if mode == "SCENE" else places(None)
    lines = [f"- 방식: {'구체적인 한 장면' if mode == 'SCENE' else '사물 · 풍경으로 나타내는 상징 그림'}"]
    if focus:
        lines.append(f"- 중심 소재: {', '.join(center)} — "
                     + ("풍경 자체가 이 그림의 주제다" if focus.get("landscape") else "화면의 중심에 크고 또렷하게 둔다"))
        bg = [p for p in setting.split(", ") if p and p not in center] if setting else []
        if bg:
            lines.append(f"- 배경: {', '.join(bg)} — 중심 소재 뒤에 옅게, 보조로만 둔다. 넓은 풍경이 그림의 주제가 되지 않게 한다")
        elif not focus.get("landscape"):
            lines.append("- 배경: 특정하지 않는다 — 지명 · 간판 · 알아볼 수 있는 건물을 그리지 않는다")
    else:
        lines.append(f"- 배경: {setting or '특정하지 않는다 — 지명 · 간판 · 알아볼 수 있는 건물을 그리지 않는다'}")
    if mode == "SCENE":                               # 배경과 행동이 벌어진 자리는 다르다 (냇가가 집 앞에 있었다 ≠ 냇가에서 빨래했다)
        lines.append(f"- 행동이 벌어진 자리: "
                     f"{places('spot') or '원문에서 확인되지 않았다 — 배경 안의 어느 지점인지 단정하는 요소를 넣지 않는다'}")
    lines.append(f"- 때: {time or '특정하지 않는다 — 연도 · 계절을 단정하는 요소를 넣지 않는다'}")
    if mode == "SCENE":
        who = PEOPLE_OPEN if unconfirmed and people else PEOPLE_INCOMPLETE if incomplete else "- 인물: "
        lines.append(who + (people or "사람을 특정하지 않는다 — 멀리 보이는 작은 모습으로만"))
        others = list(dict.fromkeys(e["text"] for e in els if e["kind"] == "person" and not is_self(e["text"])))
        if others:                                    # 함께 한 사람의 나이 · 모습은 원문에 없다 — 정하지 않는다고 적어 둔다
            lines.append(f"- 그 밖의 인물({', '.join(others)}): 나이 · 생김새 · 옷차림을 정하지 않는다")
        # 제안된 사람들이 모두 그 행동을 한 사람 · 함께 한 사람(actor · co_actor)일 때만 「함께」 를 적는다 — 관계에서 온 말이다
        lines.append(f"- 행동: {of('action')}" + (" (인물 칸의 사람들이 함께 한다)" if together else ""))
    else:
        lines.append("- 인물: 그리지 않는다")
    if focus:
        rest = [o for o in of("object").split(", ") if o and o not in center] if of("object") else []
        if rest:
            lines.append(f"- 함께 둘 수 있는 사물: {', '.join(rest)}")
        lines.append(f"- 그 밖의 사물: {FOCUS_OTHER_THINGS}")
    elif of("object"):
        lines.append(f"- 사물: {of('object')}")
    lines.append(f"- 분위기: {of('emotion') or '차분하게 — 감정을 과장하지 않는다'}")
    scene = "[그릴 장면]\n" + "\n".join(lines)
    text = "\n\n".join([blocks["style"], scene, blocks["people"], blocks["negative"]])
    out = {"style_id": STYLE_ID, "language": "ko", "text": text, "scene_block": scene,
           "elements_used": [e["id"] for e in els],
           # 화자의 나이를 어디서 가져왔는가 — 때 요소의 이름 그대로다. 「어린아이」 는 그 나이에서 따라 나온 말이다
           "self_age": age}
    if focus:
        # 원문 사실(요소와 인용)과 구도 · 표현의 선택을 따로 적는다
        out["composition"] = {
            "center": center, "landscape": bool(focus.get("landscape")),
            "background": [p for p in setting.split(", ") if p and p not in center] if setting else [],
            "choices": (["풍경 자체를 그림의 주제로 둔다"] if focus.get("landscape")
                        else ["중심 소재를 화면 중심에 크고 또렷하게 둔다", "배경은 중심 소재 뒤에 보조로만 둔다"])
                       + ["적힌 것 말고 다른 사물을 주요 소재로 넣지 않는다"],
            "facts": [{"kind": e["kind"], "text": e["text"], "turn": e["turn"], "quote": e["quote"]} for e in els]}
    return out


def check_prompt(prompt: dict, mode: str, els: list[dict]) -> list[str]:
    """조립한 지시문에 확인되지 않은 것이 섞였는지 — 숫자 · 금지어 · 방식과 인물 · 길이."""
    bad = []
    blocks = style_blocks()
    if not all(blocks[k] in prompt["text"] for k in blocks):
        bad.append("style_block_missing")
    known = "".join(e["quote"] + e["text"] for e in els)
    if [d for d in re.findall(r"\d+", prompt["scene_block"]) if d not in known]:
        bad.append("number_not_in_source")
    if any(e["status"] != "quoted" for e in els):
        bad.append("unverified_element_used")
    if any(_BANNED_LABEL.search(e["text"]) for e in els):
        bad.append("banned_label")
    if mode == "SYMBOLIC" and "- 인물: 그리지 않는다" not in prompt["scene_block"]:
        bad.append("person_in_symbolic")
    if mode == "SCENE" and not any(e["kind"] == "action" for e in els):
        bad.append("scene_without_action")
    if len(prompt["text"]) > PROMPT_MAX:
        bad.append("too_long")
    return bad


# ---------------------------------------------------------------- 판정

SCOPE_CHECKED = ["인용이 그 턴의 어르신 말씀에 글자 그대로 있는가 (공백 무시)",
                 "요소 이름이 인용 안의 말인가 (행동 · 감정은 두 글자 조각 절반 이상)",
                 "인용이 든 문장의 부정 · 전언 · 불확실 표지 (낱말로만 본다)",
                 "같은 회차의 뒤 말씀에 정정하는 말과 요소 이름이 함께 있는가 (낱말로만 본다)",
                 "그 턴을 자서전의 그 장(문장 또는 장 단위 출처)이 근거로 쓰는가",
                 "민감한 낱말(죽음 · 사고 · 질병 · 전쟁 · 폭력)",
                 "사진 — 사람이 이은 턴 · 같은 회차 · 단서 낱말 겹침"]
SCOPE_NOT_CHECKED = ["누가 그 행동을 했는가 (주어 · 인물 관계)",
                     "여러 턴의 요소를 한 장면으로 묶어도 되는가 (같은 날 · 같은 곳인가)",
                     "뒤의 말씀에서 실제로 정정 · 취소됐는가 (표지 낱말이 없으면 찾지 못한다 · 다른 회차는 보지 않는다)",
                     "표지 낱말 없이 뜻으로만 드러나는 부정 · 전언 · 민감함",
                     "사진이 실제로 이 장면을 담았는가 (단서 낱말은 관찰일 뿐이다)",
                     "이미지 모델이 지시문 밖의 것을 그려 넣는가 (생성 뒤 사람이 본다)"]


def _judge(c: dict, n: int, ctx: dict) -> dict:
    ch = ctx["chapters"].get(c["chapter_no"])
    els = [_element(e, i, ctx) for i, e in enumerate(c["elements"], start=1)]
    ok = [e for e in els if _usable(e)]
    matched = [e for e in els if e["status"] in ("quoted", "paraphrased", "blocked")]      # 인용이 원문에 있었다
    pool = ok if ctx["has_source"] else els          # 원문이 없으면 방식은 어림일 뿐이다
    kinds = {e["kind"] for e in pool}
    turns = sorted({e["turn"] for e in (ok if ctx["has_source"] else els)})
    reasons, notes = [], []

    if "action" in kinds and kinds & {"place", "object"}:
        mode = "SCENE"
    elif kinds & {"place", "object"}:
        mode = "SYMBOLIC"
    else:
        mode = "SKIP"
        reasons.append("no_visual_basis" if ok else "no_usable_element" if matched else "no_evidence")
    if ch is None:
        mode = "SKIP"
        reasons.append("unknown_chapter")

    # 검증 상태 — 인용 일치만으로 verified 가 되지 않는다
    if not ctx["has_source"]:
        link, verification = "no_source", "unverified"
        notes.append("원문이 주어지지 않아 어느 요소도 대조하지 못했다")
    else:
        if ch is None or not turns:
            link = "none"
        elif not ch["turns"] and not ch["chapter_turns"]:
            link = "chapter_has_no_turns"
            notes.append("이 장에 출처 턴이 없다 (소설체 등) — 본문과 원문의 연결을 코드로 확인하지 못했다")
        elif ch["turns"] and set(turns) <= set(ch["turns"]):
            link = "turns"
        elif set(turns) <= set(ch["turns"]) | set(ch["chapter_turns"]):
            link = "chapter_turns"                    # 문장이 아니라 장 단위로만 출처를 안다
        else:
            link = "outside_chapter"
            out_of = sorted(set(turns) - set(ch["turns"]) - set(ch["chapter_turns"]))
            notes.append(f"이 장이 근거로 쓰지 않는 턴 {out_of} 을 썼다")
        clean = all(e["status"] == "quoted" and not (set(e["flags"]) - ({"uncertain"} if e["kind"] == "time" else set()))
                    for e in els)
        verification = ("unverified" if not matched
                        else "verified" if clean and link in ("turns", "chapter_turns") else "partial")
    for e in els:
        if e["status"] in ("rejected", "blocked", "paraphrased") or (
                e["flags"] and not (e["kind"] == "time" and e["flags"] == ["uncertain"])):
            notes.append(f"{e['id']}({e['kind']} · {e['text']}) — {e['status']}" + (f" [{', '.join(e['flags'])}]" if e["flags"] else ""))

    said = " ".join(ctx["utts"][t]["elder"] for t in {e["turn"] for e in els} if t in ctx["utts"])
    words = sorted({m.group(0).strip() for m in SENSITIVE.finditer(" ".join([said, c["scene_title"], c["scene_summary"]]))})
    held_mode = None
    if mode != "SKIP" and words:
        held_mode, mode = mode, "SKIP"                # 자동으로는 그리지 않는다 — 버리지 않고 보류로 남긴다
        reasons.append("sensitive")
        notes.append(f"민감한 낱말({', '.join(words)})이 있는 말씀이다 — 자동으로 그리지 않고 보류한다. "
                     "그릴지, 상징으로 바꿀지는 사람이 정한다. 풀어도 원문에 없는 것을 그리지는 않는다")
    heard = [e["id"] for e in ok if "hearsay" in e["flags"]]
    fixed = [e["id"] for e in els if "possible_later_correction" in e["flags"]]
    if heard:
        notes.append("남에게 들은 이야기가 섞였다 — 직접 겪은 장면처럼 그리면 안 된다. 그릴지는 사람이 정한다")
    if fixed:
        notes.append("같은 회차의 뒤 말씀에 정정하는 말이 있다 — 이 요소가 고쳐졌는지 사람이 본다")

    photo = _photo_check(ok, turns, ctx)
    has_photo = {"confirmed": True, "none": False}.get(photo["state"])
    if mode != "SKIP" and photo["state"] == "confirmed":
        mode = "SKIP"
        reasons.append("real_photo")
    elif mode != "SKIP" and has_photo is None:
        notes.append({"possible_overlap": "같은 회차 사진의 단서에 이 장면의 말이 있다 — 겹치는지 사람이 본다",
                      "same_session": "같은 회차에 사진이 있다 — 이 장면의 사진인지 사람이 본다",
                      "not_provided": "사진 목록을 받지 못해 겹침을 보지 못했다"}[photo["state"]])

    # 규칙으로 잡는 의미 쪽 검토 사유 — 잡히면 검토로 보낼 뿐이고, 잡히지 않았다고 맞다는 뜻이 아니다
    soft: list[str] = []
    summary = _summary_check(c["scene_summary"], ok, els, mode, ctx, c["scene_title"])
    summary_person_at = None
    rel = _relations(c, els, ok, ctx, ctx.get("confirmed") or {})
    acts = [e for e in ok if e["kind"] == "action"]
    # 짧다 = 글자 수가 모자라거나, 낱말 하나뿐이고 목적어 · 방향 조사가 없다 (「날랐어」)
    short = [e["id"] for e in acts if len(_compact(e["text"])) < ACTION_MIN
             or (" " not in e["text"].strip() and not _PARTICLE.search(e["text"] + " "))]
    act_at = {(e["turn"], i) for e in acts for i in e["source_sentences"]}
    apart = [e["id"] for e in ok if e["kind"] in ("person", "object") and act_at
             and not ({(e["turn"], i) for i in e["source_sentences"]} & act_at)] if ctx["has_source"] else []
    by_el = {r["element"]: r for r in rel["rows"]}
    # 문장이 다르다는 것만으로는 검토 사유가 아니다 — 관계와 근거 인용이 있으면 그것을 함께 보여 준다
    apart_reason = [i for i in apart if by_el[i]["code"]["state"] != "structure_ok"
                    and next(e for e in ok if e["id"] == i)["kind"] == "object"]
    spots = [e["id"] for e in ok if e["kind"] == "place" and e.get("role") == "spot"]
    scoped = [e["id"] for e in ok if "negation_partial_scope" in e["flags"]]
    raised = [e["id"] for e in els if "certainty_raised" in e["flags"]]
    if mode == "SCENE":
        summary_person_at = len(soft)               # 이 경고는 장면 검토(사람)를 본 뒤에 정한다 — 사유의 자리만 잡아 둔다
        if short:
            soft.append("action_too_short")
            notes.append("행동 이름이 짧거나 목적어 · 방향이 없다 — 무엇을 어디로 했는지 원문에서 사람이 본다")
        if apart_reason:
            soft.append("elements_from_other_sentences")
            notes.append("행동과 다른 문장에서 온 사람 · 사물이 있다 — 같은 순간의 것인지 사람이 본다")
        if spots:
            soft.append("place_spot_not_checked")
            notes.append("행동이 벌어진 자리(spot)라고 적은 장소가 있다 — 원문이 그렇게 말했는지 사람이 본다")
    if mode != "SKIP":
        if summary["time_not_in_elements"]:
            soft.append("summary_time_not_in_elements")
            notes.append(f"요약에는 때({', '.join(summary['time_not_in_elements'])})가 있는데 때 요소에 없다")
        if summary["setting_as_spot"]:
            soft.append("summary_setting_as_spot")
            notes.append("제목 · 요약이 배경을 행동이 벌어진 자리처럼 썼다(" + ", ".join(
                x["text"] for x in summary["setting_as_spot"]) + ") — 지시문에는 배경으로만 넣었다")
        if summary["certainty_raised"] or summary["title_certainty_raised"] or raised:
            soft.append("certainty_raised")
            notes.append("원문의 불확실한 말(쯤 · 무렵)을 지우고 때를 확정했다"
                         + (" (제목: " + ", ".join(summary["title_certainty_raised"]) + ")" if summary["title_certainty_raised"] else "")
                         + " — 확정한 때는 지시문에 쓰지 않는다")
        if scoped:
            soft.append("negation_scope_unclear")
            notes.append("인용 앞 마디에 부정이 있다 — 하지 못한 것과 실제로 한 것 중 무엇을 그리는지 사람이 본다")

    # 그릴 행동 하나와 참여 관계 — 사람이 관계를 확인하기 전에는 그 사람이 든 지시문을 생성용으로 확정하지 않는다
    draw, people_open = ok, []
    people_rows = [r for r in rel["rows"] if r["kind"] == "person"]
    scene_turns = sorted({e["turn"] for e in ok if e["kind"] in ("action", "person")} & set(ctx["utts"]))
    part = {
        "applies": mode == "SCENE",
        "scene_review_id": scene_review_id(
            (c["chapter_no"], ch["key"] if ch else None), rel["central"], people_rows, scene_turns,
            {t: u["elder"] for t, u in ctx["utts"].items()},
            {t: {"session_id": u["session_id"], "source_ref": ctx["refs"].get(t)} for t, u in ctx["utts"].items()}),
        "human": "not_required" if mode != "SCENE" else "not_reviewed",
        "question": "원문에서 이 행동을 함께 한 사람이 이 후보에서 빠지지 않았는가 (complete · incomplete)",
        "proposed_people": [r["text"] for r in people_rows],
        "possible_omitted": _omission_hints(people_rows, scene_turns, ctx) if mode == "SCENE" else [],
        # 검토자가 인물 목록 옆에서 읽을 원문 문맥 — 그릴 행동과 제안된 사람들의 턴 전체. central_sentences 는 그 행동의 인용이 든 문장 번호
        "context": [{"turn": t, "text": ctx["utts"][t]["elder"],
                     "central_sentences": rel["central"]["source_sentences"]
                     if rel["central"] and rel["central"]["turn"] == t else []} for t in scene_turns],
        "scope": OMISSION_SCOPE,
    }
    if mode == "SCENE":
        if rel["state"] == "missing":
            soft.append("central_action_missing")
            notes.append("행동이 둘 이상인데 그릴 행동 하나를 정하지 않았다 — 무엇을 그릴지 사람이 정한다")
        elif rel["state"] == "invalid":
            soft.append("central_action_invalid")
            notes.append("central_action 이 가리키는 행동 요소가 없거나 쓸 수 없다")
        if rel["others"]:
            notes.append("중심 행동 말고 다른 행동도 냈다 — 그 행동은 지시문에 넣지 않았다")
        if not any(e["kind"] == "object" for e in ok):
            soft.append("object_not_listed")
            notes.append("사물 요소가 없다 — 그림에 꼭 필요한 사물이 빠졌는지 사람이 본다")
        drop = set(rel["others"])
        for r in rel["rows"]:
            if r["code"]["state"] == "other_action" or r["human"] == "rejected":
                drop.add(r["element"])                # 모델 스스로 다른 행동의 것이라 했거나 사람이 아니라고 했다
                notes.append(f"{r['element']}({r['text']}) — 중심 행동의 것이 아니어서 지시문에서 뺐다"
                             if r["human"] != "rejected" else f"{r['element']}({r['text']}) — 사람이 참여자가 아니라고 확인해 뺐다")
        draw = [e for e in ok if e["id"] not in drop]
        people_open = [r for r in rel["rows"] if r["kind"] == "person" and r["element"] not in drop and r["human"] != "confirmed"]
        # 장면 단위 — 제안된 사람 하나하나를 확인한 것과, 이 장면에 빠진 사람이 없는 것은 다른 판단이다
        part["human"] = (ctx.get("confirmed_scenes") or {}).get(part["scene_review_id"], "not_reviewed")
        if part["human"] != "complete":
            if part["possible_omitted"]:
                soft.append("possible_participant_omitted")
                notes.append("원문에 함께 했다고 나오는데 인물 요소에 없는 사람이 있다: " + ", ".join(
                    f"{h['name']}(「{h['quote']}」)" for h in part["possible_omitted"]) + " — 코드가 채우지 않는다. 사람이 본다")
            soft.append("participants_marked_incomplete" if part["human"] == "incomplete"
                        else "participants_completeness_not_human_confirmed")
            notes.append("이 장면에 빠진 참여자가 없는지 사람이 확인하지 않았다 — 인물 하나하나의 확인과는 따로다. "
                         "확인 전에는 생성용 지시문을 만들지 않는다" if part["human"] != "incomplete"
                         else "사람이 이 장면에 빠진 참여자가 있다고 했다 — 후보를 고쳐 다시 검토한다")
        # 요약에만 있는 사람(「어머니가 캐 오신 자루」 의 어머니) — 장면 검토가 complete 라는 것만으로 풀지 않는다.
        # ① 사람이 이 후보(같은 행동 · 같은 사람들 · 같은 원문)에 빠진 참여자가 없다고 했고 ② 그때 본 제목 · 요약이 지금과 같고
        # ③ 그 사람이 그림 지시문에 들어가는 어느 요소에도 없을 때만 푼다. 원래 검사 결과는 그대로 남긴다.
        seen = (ctx.get("confirmed_scene_texts") or {}).get(part["scene_review_id"]) or {}
        same_text = bool(seen) and all(_compact(str(seen.get(k, ""))) == _compact(c[k]) for k in ("scene_title", "scene_summary"))
        drawn = [_compact(e["text"]) for e in draw]
        conditions = {"scene_review_complete": part["human"] == "complete", "same_title_and_summary_as_reviewed": same_text}
        done, left = [], []
        for name in summary["persons_not_in_elements"]:
            absent = not any(name in t for t in drawn)
            if conditions["scene_review_complete"] and same_text and absent:
                done.append({"name": name, "resolved_by": "human_scene_review", "reviewer": ctx.get("reviewer"),
                             "scene_review_id": part["scene_review_id"],
                             "basis": "사람이 이 후보에 빠진 참여자가 없다고 확인했고, 그때의 제목 · 요약이 지금과 같고, "
                                      "이 사람은 그림 지시문의 어느 요소에도 없다 — 그리지 않는 사람이다"})
            else:
                left.append({"name": name, "not_in_prompt": absent})
        summary["persons_resolution"] = {"original": list(summary["persons_not_in_elements"]), "resolved": done,
                                         "unresolved": [x["name"] for x in left], "conditions": conditions}
        if left:
            soft.insert(summary_person_at if summary_person_at is not None else len(soft), "summary_person_not_in_elements")
            notes.append(f"요약에는 {', '.join(x['name'] for x in left)} 이(가) 있는데 인물 요소에 없다 — "
                         "함께 한 사람이 빠졌는지, 그 순간에 없던 사람인지 사람이 본다. 코드가 채우지 않는다")
        elif done:
            notes.append(f"요약의 {', '.join(x['name'] for x in done)} — 인물 요소에 없다는 경고는 사람의 장면 검토로 풀었다 "
                         "(원래 검사 결과는 checks.summary_consistency 에 남아 있다)")
        codes = {r["code"]["state"] for r in people_open}
        soft += [f"person_relation_{x}" for x in ("missing", "evidence_missing", "evidence_not_found") if x in codes]
        if people_open:
            soft.append("person_relation_not_human_confirmed")
            notes.append("인물 " + ", ".join(r["text"] for r in people_open) + " — 이 행동에 참여했는지 사람이 확인하지 않았다. "
                         "확인 전에는 생성용 지시문을 만들지 않는다 (people_review 의 인용을 본다)")

    prompt, checks = None, []
    if mode != "SKIP" and draw and ctx["has_source"]:
        drawn_people = [r for r in rel["rows"] if r["kind"] == "person" and any(e["id"] == r["element"] for e in draw)]
        prompt = build_prompt(mode, draw, unconfirmed=bool(people_open),
                              incomplete=part["applies"] and part["human"] != "complete",
                              together=len(drawn_people) >= 2 and all(
                                  (r["proposed"] or {}).get("role") in ("actor", "co_actor") for r in drawn_people))
        checks = check_prompt(prompt, mode, draw)
    # verified 가 못 된 까닭을 하나씩 적고, 좁은 규칙이나 사람의 확인으로 풀린 것을 표시한다. 표지는 지우지 않는다.
    age_kept = sorted({a for e in ok if e["kind"] == "time" and e["status"] == "quoted"
                       and (_HEDGE.search(e["text"]) or _HEDGE_TAIL.search(e["text"]))
                       for a in (_age_hedges(e["text"]) or [])})
    hedge_intact = not (raised or summary["certainty_raised"] or summary["title_certainty_raised"])
    rel_of = {r["element"]: r for r in rel["rows"]}
    causes = []
    if ctx["has_source"] and matched:
        for e in els:
            if e["status"] != "quoted":
                causes.append({"element": e["id"], "text": e["text"], "cause": f"status_{e['status']}",
                               "resolved_by": None, "basis": None})
                continue
            for f in e["flags"]:
                if e["kind"] == "time" and f == "uncertain":
                    continue                              # 때의 추정은 말씀 그대로 쓴다 (처음부터 까닭이 아니다)
                row = {"element": e["id"], "text": e["text"], "cause": f, "resolved_by": None, "basis": None}
                scope_ = e.get("hedge_scope") or {}
                if (f in ("uncertain", "uncertain_nearby") and scope_.get("kind") == "age_expression" and hedge_intact
                        and set(scope_["ages"]) <= set(age_kept)):
                    row.update(resolved_by="rule_age_hedge_preserved",
                               basis="추정 표지가 나이 표현(" + ", ".join(scope_["ages"]) + ")에만 붙어 있고, 때 요소 · 제목 · 요약 · "
                                     "그림 지시문이 그 추정을 그대로 지켰다 — 이 요소 자체가 불확실하다는 말이 아니다")
                elif f == "negation_nearby" and e["kind"] == "person" and rel_of.get(e["id"], {}).get("human") == "confirmed":
                    row.update(resolved_by="human_relation_confirmed", reviewer=ctx.get("reviewer"),
                               relation_id=rel_of[e["id"]]["relation_id"],
                               basis="사람이 이 사람의 중심 행동 참여를 확인했다(같은 인용 · 근거 · 원문). 같은 문장의 부정은 "
                                     "그 참여를 부정하는 말이 아니라고 본 것이다 — 다른 주장(쉬지 않았다 · 끝까지 날랐다)을 "
                                     "확인한 것은 아니다")
                causes.append(row)
        if link not in ("turns", "chapter_turns"):
            causes.append({"element": None, "text": None, "cause": f"memoir_link_{link}", "resolved_by": None, "basis": None})
    open_causes = [x for x in causes if x["resolved_by"] is None]
    trace_ok = verification == "verified" or (verification == "partial" and not open_causes)
    if held_mode:
        decision = "held"
    elif mode == "SKIP":
        decision = "skip"
    elif trace_ok and has_photo is False and not checks and not soft:
        decision = "eligible"
    else:
        decision = "review"
        reasons += ([f"verification_{verification}"] if not trace_ok else []) \
            + (["hearsay"] if heard else []) + (["possible_later_correction"] if fixed else []) + soft \
            + ([f"photo_{photo['state']}"] if has_photo is not False else []) + [f"prompt_{x}" for x in checks]

    def mark(flag: str, near: str | None = None) -> dict:
        if not ctx["has_source"] or not matched:
            return {"state": "not_checked", "elements": [], "nearby": []}
        ids = [e["id"] for e in els if flag in e["flags"]]
        by = [e["id"] for e in els if near and near in e["flags"]]
        return {"state": "found" if ids else "nearby" if by else "marker_not_found", "elements": ids, "nearby": by}

    def share(n: int) -> str:
        return "not_checked" if not ctx["has_source"] else "all" if n == len(els) else "some" if n else "none"

    item_checks = {
        "quote_match": {"state": share(len(matched)), "matched": len(matched) if ctx["has_source"] else None,
                        "total": len(els)},
        "label_in_quote": {"state": share(sum(1 for e in els if e["status"] == "quoted"))},
        "negation": {**mark("negation_in_source", "negation_nearby"), "partial_scope": scoped},
        "uncertainty": mark("uncertain", "uncertain_nearby"),
        "hearsay": mark("hearsay", "hearsay_nearby"),
        "later_correction": {**mark("possible_later_correction"), "scope": "같은 회차의 뒤 말씀 · 정정 낱말만"},
        "people_and_action": {
            "state": "human_confirmed" if mode == "SCENE" and not people_open and any(
                r["kind"] == "person" and r["human"] == "confirmed" for r in rel["rows"]) else "not_checked",
            "proposed": sum(1 for r in rel["rows"] if r["kind"] == "person" and r["proposed"] is not None),
            "code": {k: sum(1 for r in rel["rows"] if r["kind"] == "person" and r["code"]["state"] == k)
                     for k in ("structure_ok", "missing", "evidence_missing", "evidence_not_found", "other_action")},
            "human": {k: sum(1 for r in rel["rows"] if r["kind"] == "person" and r["human"] == k)
                      for k in ("not_reviewed", "confirmed", "rejected")},
            "note": "누가 무엇을 했는지는 코드가 확인하지 못한다 — 사람이 본다", "scope": RELATION_SCOPE},
        "central_action": {"state": rel["state"], "element": rel["central"]["id"] if rel["central"] else None,
                           "other_actions": rel["others"]},
        # 인물별 확인(people_and_action)과 따로다 — 제안된 사람을 다 확인해도 빠진 사람이 없다는 뜻이 아니다
        "participants_complete": {
            "state": {"complete": "human_complete", "incomplete": "human_incomplete"}.get(part["human"], "not_checked")
            if part["applies"] else "not_applicable",
            "possible_omitted": [h["name"] for h in part["possible_omitted"]], "scope": OMISSION_SCOPE},
        "memoir_link": {"state": link},
        "sensitive": {"state": "found" if words else "marker_not_found", "words": words},
        "photo": {"state": photo["state"]},
        "summary_consistency": summary,
        "action_detail": {"state": "no_action" if not acts else "short" if short else "has_object", "elements": short},
        "same_moment": {"state": "not_checked", "elements_from_other_sentences": apart,
                        "note": "요소들이 같은 순간의 것인지는 코드가 확인하지 못한다 — 다른 문장에서 온 것만 알려 준다"},
        "place_role": {"state": "no_place" if not any(e["kind"] == "place" for e in ok)
                       else "spot_claimed" if spots else "setting_only", "spots": spots},
    }
    basis = {("hearsay" if "hearsay" in e["flags"] else "direct") for e in ok}

    return {
        "scene_id": None, "_order": n,
        "chapter_no": c["chapter_no"], "chapter_key": ch["key"] if ch else None,
        "chapter_title": ch["title"] if ch else None,
        "scene_title": c["scene_title"].strip(), "scene_summary": c["scene_summary"].strip(),
        "source_turns": turns,
        "source_refs": [{"turn": t, **ctx["refs"][t]} for t in turns if t in ctx["refs"]],
        "source_excerpt": [{"turn": e["turn"], "quote": e["quote"]} for e in ok],
        "elements": els,
        "visual_mode": mode, "mode_if_released": held_mode,
        "verification": verification, "memoir_link": link, "checks": item_checks,
        # verification 은 자동 검사의 원래 결과다 — 바꾸지 않는다. 여기에 까닭마다 풀렸는지와, 무엇으로 풀렸는지를 적는다
        "verification_review": {
            "auto": verification, "causes": causes, "open": [f"{x['element']}:{x['cause']}" for x in open_causes],
            "effective": ("not_traceable" if verification == "unverified" else "no_open_cause" if trace_ok else "open_causes"),
            "note": "resolved_by 가 rule_… 이면 좁은 규칙으로, human_… 이면 사람의 확인으로 풀린 것이다. null 은 아직 열려 있다. "
                    "전언 · 정정 · 서술의 부정 · 바꿔 쓴 이름은 여기서 풀지 않는다"},
        "verification_scope": {"checked": SCOPE_CHECKED, "not_checked": SCOPE_NOT_CHECKED},
        "experience_basis": None if not ok else "mixed" if len(basis) > 1 else next(iter(basis)),
        "has_real_photo": has_photo, "photo_check": photo,
        "placement": _placement(ch, turns, ok),
        "decision": decision, "generation": None,
        "decision_reasons": reasons,
        "importance": c["importance"], "recommendation_reason": c["reason"].strip(),
        "risk_notes": notes,
        "central_action": None if rel["central"] is None else {
            "element": rel["central"]["id"], "text": rel["central"]["text"], "state": rel["state"],
            "turn": rel["central"]["turn"], "quote": rel["central"]["quote"]},
        "people_review": [r for r in rel["rows"] if r["kind"] == "person"],
        "participants_review": part,
        "object_relations": [r for r in rel["rows"] if r["kind"] == "object"],
        "generation_prompt": prompt if decision == "eligible" else None,
        "draft_prompt": prompt if decision == "review" else None,
        "prompt_checks": checks,
    }


def _core(s: dict) -> set[tuple]:
    """장면의 알맹이 — 쓸 수 있는 행동 · 사물 · 장소 요소 (턴과 이름)."""
    return {(e["turn"], _compact(e["text"])) for e in s["elements"]
            if e["kind"] in ("action", "object", "place") and (_usable(e) or e["status"] == "unchecked")}


def _same_scene(a: dict, b: dict) -> bool:
    """
    같은 장면인가. 턴이 같다는 것만으로는 아니다 — 긴 이야기 하나(한 턴)에 장면이 여럿 있다.
    작은 쪽 알맹이의 DUP_OVERLAP 이상이 큰 쪽에 들어 있으면 같은 장면으로 본다.
    """
    x, y = _core(a), _core(b)
    return bool(x and y) and len(x & y) / min(len(x), len(y)) >= DUP_OVERLAP


def _pick(scenes: list[dict]) -> None:
    """겹치는 장면을 덜고, 남은 것에서 최대 MAX_SCENES 를 고른다 — 자동 생성 대상 · 주요 장면 · 장마다 고르게."""
    kept: list[dict] = []
    for s in scenes:
        if s["decision"] in ("skip", "held"):
            continue
        twin = next((k for k in kept if _same_scene(s, k)), None)
        if twin:
            s.update(visual_mode="SKIP", decision="skip", generation_prompt=None, draft_prompt=None)
            s["decision_reasons"] = ["duplicate"]
            s["risk_notes"].append(f"앞의 후보 「{twin['scene_title']}」 와 행동 · 사물 · 장소가 겹친다")
        else:
            kept.append(s)
    order = sorted(kept, key=lambda s: (s["decision"] != "eligible", s["importance"] != "main",
                                        s["visual_mode"] != "SCENE", s["_order"]))
    chosen: list[dict] = []
    for first_pass in (True, False):
        for s in order:
            if len(chosen) < MAX_SCENES and s not in chosen and not (
                    first_pass and any(x["chapter_no"] == s["chapter_no"] for x in chosen)):
                chosen.append(s)
    for s in kept:
        if s not in chosen:
            s.update(decision="not_selected", generation_prompt=None, draft_prompt=None)
            s["decision_reasons"] = ["over_limit"]


CANDIDATE = {"eligible": "eligible", "review": "needs_review", "held": "held",
             "not_selected": "not_selected", "skip": "excluded"}


def _generation(decision: str) -> dict:
    """
    생성 단계 다섯 가지. 이 모듈이 정하는 것은 앞의 둘뿐이고, 뒤의 셋은 늘 「아직」 이다.

        candidate        ① 후보로 적합한가 — eligible · needs_review · held · not_selected · excluded
        review_required  ② 사람이 더 봐야 하는가
        user_selected    ③ 사용자가 만들기로 골랐는가      (이 모듈 밖 — 늘 false)
        image_status     ④ 이미지가 만들어졌는가           (이 모듈 밖 — 늘 not_requested)
        user_approved    ⑤ 사용자가 그 이미지를 승인했는가 (이 모듈 밖 — 늘 false)
    이미지 생성 API 는 user_selected 가 true 가 된 장면에만 불러야 한다. eligible 은 그 허가가 아니다.
    """
    return {"candidate": CANDIDATE[decision], "review_required": decision in ("review", "held"),
            "user_selected": False, "image_status": "not_requested", "user_approved": False}


def load_confirmations(doc) -> dict[str, str]:
    """
    사람이 확인한 것 — 두 가지를 따로 받는다. 검토한 사람(reviewer)이 비어 있으면 받지 않는다.
    이 모듈은 이 파일을 만들지 않는다 — 사람이 쓴다.

        relations  {relation_id: "confirmed" | "rejected"}       제안된 그 사람이 그 행동에 참여했는가 (사람 하나씩)
        scenes     {scene_review_id: "complete" | "incomplete"}  그 장면에 빠진 참여자가 없는가 (장면 하나씩 · 없어도 된다)
    돌려주는 것은 relations 다. scenes 는 load_scene_confirmations 가 읽는다.
    """
    if doc is None:
        return {}
    rel = doc.get("relations") if isinstance(doc, dict) else None
    if (not isinstance(doc.get("reviewer") if isinstance(doc, dict) else None, str) or not doc["reviewer"].strip()
            or not isinstance(rel, dict) or not all(v in ("confirmed", "rejected") for v in rel.values())):
        raise IllustError("input", "확인 기록 모양이 다르다 — reviewer(검토한 사람)와 relations 가 있어야 한다")
    load_scene_confirmations(doc)
    return dict(rel)


def load_scene_confirmations(doc) -> dict[str, str]:
    scenes = (doc or {}).get("scenes") or {}
    if not isinstance(scenes, dict) or not all(v in ("complete", "incomplete") for v in scenes.values()):
        raise IllustError("input", "확인 기록의 scenes 모양이 다르다 — {scene_review_id: complete | incomplete}")
    return dict(scenes)


def load_scene_texts(doc) -> dict[str, dict]:
    """
    확인 기록의 scene_texts — {scene_review_id: {"scene_title", "scene_summary"}}. 사람이 그 장면을 검토할 때 본 제목 · 요약이다.
    이것이 지금 후보의 글과 같을 때만, 장면 검토(complete)를 요약에만 있는 사람의 경고에 쓴다. 없으면 그 경고는 풀리지 않는다.
    """
    texts = (doc or {}).get("scene_texts") or {}
    if not isinstance(texts, dict) or not all(
            isinstance(v, dict) and isinstance(v.get("scene_title"), str) and isinstance(v.get("scene_summary"), str)
            for v in texts.values()):
        raise IllustError("input", "확인 기록의 scene_texts 모양이 다르다 — {scene_review_id: {scene_title, scene_summary}}")
    return dict(texts)


def diff_candidates(original: list[dict], amended: list[dict]) -> list[dict]:
    """
    원본 후보와 고친 후보의 차이 — 검토자가 무엇이 더해지고 빠지고 바뀌었는지 보게 한다.
    후보는 차례로, 요소는 key(없으면 kind 와 이름)로 맞춘다. 판정하지 않는다 — 차이만 적는다.
    """
    def ident(e: dict):
        return e.get("key") or (e["kind"], e["text"])

    out = []
    for i in range(max(len(original), len(amended))):
        a = original[i] if i < len(original) else None
        b = amended[i] if i < len(amended) else None
        if a is None or b is None:
            out.append({"candidate": i, "change": "candidate_added" if a is None else "candidate_removed",
                        "scene_title": (b or a)["scene_title"]})
            continue
        ea, eb = {ident(e): e for e in a["elements"]}, {ident(e): e for e in b["elements"]}
        row = {"candidate": i, "change": "candidate_kept",
               "fields_changed": {k: {"from": a.get(k), "to": b.get(k)}
                                  for k in ("scene_title", "scene_summary", "central_action", "importance", "reason")
                                  if a.get(k) != b.get(k)},
               "elements_added": [e for k, e in eb.items() if k not in ea],
               "elements_removed": [e for k, e in ea.items() if k not in eb],
               "elements_changed": [{"from": ea[k], "to": eb[k]} for k in ea if k in eb and ea[k] != eb[k]]}
        out.append(row)
    return out


def run(data: dict, call: Call | None = None, *, model_source: str = "mock", only: list | None = None,
        confirmations: dict | None = None, pick: bool = True, system: str | None = None) -> dict:
    """
    입력 → 결과(illust-result-v1). call 은 (system, user) → 모델 응답 글이다 — 넘기지 않으면 call_model 이고
    그것은 승인 전이라 늘 실패한다. 모델은 한 번만 부른다. 이미지는 만들지 않는다.
    """
    sc = scope(data, only)
    ctx = sc["ctx"]
    ctx["confirmed"] = load_confirmations(confirmations)
    ctx["confirmed_scenes"] = load_scene_confirmations(confirmations)
    ctx["confirmed_scene_texts"] = load_scene_texts(confirmations)
    ctx["reviewer"] = (confirmations or {}).get("reviewer")
    # system — 다른 지시문으로 같은 검사를 돌릴 때(목차별 대표 그림 · memoir_illust_book). 없으면 SELECT_FILE 의 것이다
    reply = (call or call_model)(system if system is not None else select_prompt(), select_message(data, only))
    cands = check_candidates(reply)
    scenes = [_judge(c, i, ctx) for i, c in enumerate(cands)]
    sent_nos, sent_turns = {c["no"] for c in sc["chapters"]}, set(sc["turns"])
    for s in scenes:                                  # 보내지 않은 장 · 턴을 후보가 쓰면 받아 주지 않는다
        outside = s["chapter_no"] not in sent_nos or any(e["turn"] not in sent_turns for e in s["elements"])
        if ctx["has_source"] and outside and s["decision"] != "skip":
            s.update(visual_mode="SKIP", decision="skip", generation_prompt=None, draft_prompt=None)
            s["decision_reasons"] = ["outside_scope"]
            s["risk_notes"].append("모델에 보내지 않은 장 또는 턴을 썼다")
    # pick=False — 책 전체에서 MAX_SCENES 개를 고르는 일(겹침 덜기 · 한도)을 하지 않는다. 목차마다 하나씩 정하는 흐름이 쓴다
    if pick:
        _pick(scenes)
    seen: dict[int, int] = {}
    for s in scenes:                                  # 이 실행 안에서만 뜻이 있는 번호다 — DB 의 ID 가 아니다
        seen[s["chapter_no"]] = seen.get(s["chapter_no"], 0) + 1
        s["scene_id"] = f"il-{s['chapter_no']}-{seen[s['chapter_no']]}"
        s["generation"] = _generation(s["decision"])
        s.pop("_order")
    used = {r["relation_id"] for s in scenes for r in s["people_review"] if r["relation_id"] in ctx["confirmed"]}
    used_scenes = {s["participants_review"]["scene_review_id"] for s in scenes} & set(ctx["confirmed_scenes"])
    memoir = data["memoir"]
    title = memoir.get("title")
    count = lambda k, v: sum(1 for s in scenes if s[k] == v)       # noqa: E731
    return {
        "schema_version": RESULT_SCHEMA, "input_ref": input_ref(data),
        "memoir": {"memoir_id": memoir.get("memoir_id"), "style": memoir.get("style"),
                   "title": title.get("text") if isinstance(title, dict) else title},
        "source_state": "provided" if ctx["has_source"] else "missing",
        "photos_state": "not_provided" if ctx["photos"] is None else "provided",
        "limits": {"max_scenes": MAX_SCENES if pick else None}, "style_id": STYLE_ID, "prompt_hashes": prompt_hashes(),
        "model": {"source": model_source, "calls": 1}, "images_generated": False,
        "scope": {"whole_book": sc["whole_book"], "chapter_nos": sorted(sent_nos),
                  "chapter_keys": [c["key"] for c in sc["chapters"]], "turns": sc["turns"]},
        "image_api_called": False, "verification_meaning": VERIFICATION_MEANING,
        "human_confirmations": {
            "reviewer": (confirmations or {}).get("reviewer"), "relations": len(ctx["confirmed"]),
            # 넘겨받은 확인 가운데 이번 결과의 관계에 맞아 쓰인 것 · 맞는 관계가 없어 쓰이지 않은 것(오래된 확인)
            "applied": len(used), "unused": len(set(ctx["confirmed"]) - used),
            # 장면 단위(빠진 참여자가 없는가) — 인물별 확인과 따로 센다
            "scenes": len(ctx["confirmed_scenes"]), "scenes_applied": len(used_scenes),
            "scenes_unused": len(set(ctx["confirmed_scenes"]) - used_scenes)},
        "scenes": scenes,
        "summary": {"candidates": len(scenes),
                    "decision": {d: count("decision", d) for d in ("eligible", "review", "held", "not_selected", "skip")},
                    "visual_mode": {m: count("visual_mode", m) for m in MODES},
                    "verification": {v: count("verification", v) for v in ("verified", "partial", "unverified")}},
    }


def report(result: dict) -> str:
    """사람이 볼 요약. 원문 인용이 들어 있다 — eval/runs 밖으로 내보내지 않는다."""
    s = result["summary"]
    out = [f"# 삽화 장면 선정 — {result['memoir']['title'] or '(제목 없음)'}", "",
           f"- 입력 {result['input_ref']} · 원문 {result['source_state']} · 사진 {result['photos_state']} · 모델 {result['model']['source']}",
           f"- 후보 {s['candidates']} → 후보 적합 {s['decision']['eligible']} · 검토 {s['decision']['review']} · "
           f"보류 {s['decision']['held']} · 한도 밖 {s['decision']['not_selected']} · 제외 {s['decision']['skip']}",
           "- 이미지는 만들지 않았다. 사용자가 고른 장면도, 승인한 그림도 아직 없다. 그림의 품질은 이 보고서로 알 수 없다.",
           f"- {result['verification_meaning']}", ""]
    for x in result["scenes"]:
        out += [f"## {x['scene_id']} · {x['chapter_no']}장 「{x['chapter_title']}」 — {x['scene_title']}",
                f"- 판정 **{x['decision']}** · 방식 {x['visual_mode']} · 검증 {x['verification']} · 본문 연결 {x['memoir_link']} · "
                f"사진 {x['photo_check']['state']}",
                f"- 판정 이유(코드): {', '.join(x['decision_reasons']) or '-'}",
                "- 항목별: " + " · ".join(f"{k} {v['state']}" for k, v in x["checks"].items()),
                f"- 경험: {x['experience_basis'] or '-'} · 자리: " + (
                    "-" if not x["placement"] else f"{x['placement']['basis']} 문단 {x['placement']['paragraph_index']}"),
                f"- 추천 이유(모델 · 참고): {x['recommendation_reason']}"]
        out += [f"- 요소 {e['id']} {e['kind']} 「{e['text']}」 턴 {e['turn']} — {e['status']}"
                + (f" [{', '.join(e['flags'])}]" if e["flags"] else "") + f" · “{e['quote']}”" for e in x["elements"]]
        out += [f"- 주의: {n}" for n in x["risk_notes"]]
        p = x["generation_prompt"] or x["draft_prompt"]
        if p:
            out += ["", "```text", p["scene_block"], "```"]
        out.append("")
    return "\n".join(out)
