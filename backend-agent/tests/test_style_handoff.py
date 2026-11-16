"""문체 3종(수필체 · 문학체 · 소설체) 전달 자료 — 무료 점검. 모델 호출 없음 · 네트워크 없음 · 표준 라이브러리 + pytest.

    python -m pytest tests/test_style_handoff.py -q

이 테스트가 보는 것은 **프롬프트 파일이 바뀌지 않았는가 · 문체 매핑이 겹치지 않는가 · 입출력 형식 계약이 맞는가**뿐이다.
실제 모델로 집필이 되는지, 서비스 경로에 연결됐는지는 보지 않는다(문체 프롬프트는 아직 어느 운영 코드에서도 읽지 않는다).
"""
import hashlib
import importlib.util
import json
import re
from pathlib import Path

import pytest

STYLE = Path(__file__).resolve().parents[1] / "첨부프롬프트_md" / "문체"
MAN = json.loads((STYLE / "style_manifest.json").read_text(encoding="utf-8"))
STYLES = {s["internal_id_proposed"]: s for s in MAN["styles"]}
# 검증한 원고를 만든 파일의 SHA-256 — 이 값과 다르면 프롬프트가 바뀐 것이다(줄바꿈 변환 포함)
PINNED = {"essay": "4a9c43e3b163e70da1638f91b97ca0c3a1238568bed64bcd048adc6a17cd8bc0",
          "literary": "fd70d60bb8ad4e14e63fe5889ae09b18c6c9b3d1d928a3ca9320bbdca2276049",
          "novel": "4b05811de3436f4b6e090c77c29b8370ef6d83b6ec062d8ec29998c21bda4993"}
NOVEL_ORIGINAL_SHA = "d7c86e53c68fe4bb04c44768dcd02191c9aebe366011495e63291ac853c16372"      # 구운몽ST 원본 — 정식 소설체가 아니다(파생의 출처로만 적는다)
DREAM_TERMS = ("꿈", "기시감", "구운몽", "예언", "데자뷔", "읽었던", "먼저 떠올", "진위")


def raw(sid: str) -> bytes:
    return (STYLE / STYLES[sid]["prompt"]["path"]).read_bytes()


def load_reference():
    spec = importlib.util.spec_from_file_location("bundle_reference", STYLE / "reference" / "bundle_reference.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def sample(name: str):
    return json.loads((STYLE / "examples" / name).read_text(encoding="utf-8"))


def test_three_styles_and_unique_mapping():
    assert [s["display_name"] for s in MAN["styles"]] == ["수필체", "문학체", "소설체"]
    assert len(STYLES) == 3 and set(STYLES) == {"essay", "literary", "novel"}
    assert len({s["prompt"]["sha256"] for s in MAN["styles"]}) == 3 and len({s["prompt"]["path"] for s in MAN["styles"]}) == 3
    for sid in STYLES:                                                       # 문체 폴더마다 프롬프트는 하나뿐이다 — 구버전이 섞이지 않는다
        assert [p.name for p in (STYLE / sid).iterdir()] == [Path(STYLES[sid]["prompt"]["path"]).name]


@pytest.mark.parametrize("sid", ["essay", "literary", "novel"])
def test_prompt_bytes_match_manifest_and_pinned_hash(sid):
    b, p = raw(sid), STYLES[sid]["prompt"]
    assert hashlib.sha256(b).hexdigest() == p["sha256"] == PINNED[sid] and len(b) == p["bytes"]
    assert b[:3] != b"\xef\xbb\xbf" and b"\r\n" not in b and b.endswith(b"\n")          # BOM 없음 · LF · 끝 줄바꿈 — 검증한 바이트 그대로
    b.decode("utf-8")


def test_gitattributes_keeps_prompt_bytes():
    """Windows(core.autocrlf=true)에서 받으면 줄바꿈이 CRLF 로 바뀌어 해시가 달라진다 — 이 폴더는 변환을 끈다."""
    t = (STYLE / ".gitattributes").read_text(encoding="utf-8")
    assert "*.md -text" in t and "*.txt -text" in t and "*.json -text" in t


def test_novel_is_the_minimal_revision_not_the_original():
    nov, t = STYLES["novel"], raw("novel").decode("utf-8")
    assert nov["internal_version"] == "구운몽ST 최소 수정 v1" and nov["prompt"]["path"] == "novel/prompt_소설체_최소수정v1.md"
    assert nov["prompt"]["sha256"] != NOVEL_ORIGINAL_SHA and nov["derived_from"]["original_sha256"] == NOVEL_ORIGINAL_SHA
    assert nov["derived_from"]["original_is_registered_style"] is False and nov["derived_from"]["edits"]["new_prohibitions"] == 0
    assert [w for w in DREAM_TERMS if w in t] == []                           # 꿈 · 기시감 · 미래 예지를 요구하던 구절이 없다
    assert "사건은 실제 경험을 바탕으로 현실적인 장면과 일반적인 회상 구조로 전개한다." in t
    assert not any(hashlib.sha256(p.read_bytes()).hexdigest() == NOVEL_ORIGINAL_SHA for p in STYLE.rglob("*") if p.is_file())
    assert nov["approval"] == "다애님 승인 완료 — 소설체 최소 수정 v1" and not [c for c in nov["known_constraints"] if "승인" in c]
    run = nov["verified_runs"][0]
    assert run["matches_package_prompt"] and run["prompt_sha256_logged"] == nov["prompt"]["sha256"] and run["model"] == "claude-sonnet-5-5"


def test_literary_prompt_matches_logged_call():
    run = STYLES["literary"]["verified_runs"][0]
    assert run["matches_package_prompt"] and run["prompt_sha256_logged"] == STYLES["literary"]["prompt"]["sha256"] and run["model"] == "claude-sonnet-5-5"


def test_prompt_roles_differ_by_style():
    essay, lit, nov = (raw(s).decode("utf-8") for s in ("essay", "literary", "novel"))
    assert "{{SOURCE_TEXT}}" not in essay and "{{SOURCE_TEXT}}" not in lit and nov.count("{{SOURCE_TEXT}}") == 1      # 소설체만 템플릿
    assert '"essay_id": "e48"' in essay                    # 알려진 제약 — 예시 id 가 값으로 적혀 있다(모델이 베끼는 일이 있었다)
    assert "새로 짓습니다" in essay and "직접 짓지" not in essay     # 수필체 지시문은 제목을 새로 지으라고 한다 — 확정 제목은 호출 쪽에서 지킨다
    assert '"essay_id": "자료의 essay_id 를 그대로"' in lit and "임시값을 글자 그대로" in lit
    assert "소설 본문만 출력한다" in nov and "```json" not in nov           # 소설체는 JSON 을 내지 않는다


def test_loading_must_not_transform_prompt():
    """기존 파이프라인의 지시문 로더는 코드 울타리 줄을 지우고 공통 지침을 앞에 붙인다 — 문체 프롬프트에 쓰면 검증한 글과 달라진다."""
    fence = re.compile(r"^(?:```|~~~)[^\n]*\n?", re.M)
    for sid in ("essay", "literary"):
        t = raw(sid).decode("utf-8")
        assert fence.sub("", t) != t and hashlib.sha256(fence.sub("", t).encode()).hexdigest() != STYLES[sid]["prompt"]["sha256"]
    t = raw("novel").decode("utf-8")
    assert t.split("{{SOURCE_TEXT}}")[1] == "\n[현재 장 원문 끝]\n"


def check(schema: dict, v, path="$") -> list[str]:
    """아주 작은 스키마 검사기 — type · required · additionalProperties · enum · items."""
    errs, t = [], schema.get("type")
    ok = {"object": dict, "array": list, "string": str, "boolean": bool, "integer": int}.get(t)
    if ok and (not isinstance(v, ok) or (t == "integer" and isinstance(v, bool))):
        return [f"{path}: {t} 아님"]
    if "enum" in schema and v not in schema["enum"]:
        errs.append(f"{path}: 허용값 아님 {v!r}")
    if t == "object":
        errs += [f"{path}: 필수 키 없음 {k}" for k in schema.get("required", []) if k not in v]
        if schema.get("additionalProperties") is False:
            errs += [f"{path}: 모르는 키 {k}" for k in v if k not in schema.get("properties", {})]
        for k, sub in schema.get("properties", {}).items():
            if k in v:
                errs += check(sub, v[k], f"{path}.{k}")
    if t == "array":
        for i, x in enumerate(v):
            errs += check(schema.get("items", {}), x, f"{path}[{i}]")
    return errs


@pytest.mark.parametrize("sid", ["essay", "literary"])
def test_output_samples_follow_schema_and_keep_anchors(sid):
    schema = json.loads((STYLE / "schemas" / f"{sid}_output.schema.json").read_text(encoding="utf-8"))
    e = sample(f"{sid}_output.sample.json")
    assert check(schema, e) == []
    body = "\n".join(e["paragraphs"])
    assert all(f["where"] in body for f in e["facts"]) and all(x["text"] in body for x in e["fiction"])       # 사실의 자리 · 각색 구절은 본문에 글자 그대로
    assert check(schema, {**e, "extra": 1}) and check(schema, {k: v for k, v in e.items() if k != "facts"})    # 모르는 키 · 빠진 키는 걸린다


def test_schemas_differ_only_in_fiction_record():
    a = json.loads((STYLE / "schemas" / "essay_output.schema.json").read_text(encoding="utf-8"))
    b = json.loads((STYLE / "schemas" / "literary_output.schema.json").read_text(encoding="utf-8"))
    assert a["required"] == b["required"] and set(a["properties"]) == set(b["properties"])
    fa, fb = a["properties"]["fiction"]["items"], b["properties"]["fiction"]["items"]
    assert set(fb["required"]) - set(fa["required"]) == {"conflict", "note"} and "enum" in fb["properties"]["type"] and "enum" not in fa["properties"]["type"]


def test_analysis_sample_follows_schema_and_feeds_the_bundles():
    """수필체 · 문학체는 프롬프트만으로 돌지 않는다 — 분석 결과에서 만든 장 자료 묶음이 사용자 메시지다."""
    schema = json.loads((STYLE / "schemas" / "analysis_output.schema.json").read_text(encoding="utf-8"))
    an = sample("analysis.sample.json")
    assert check(schema, an) == []
    assert check(schema, {**an, "stories": [{k: v for k, v in an["stories"][0].items() if k != "must_keep"}]})   # 묶음이 쓰는 필드가 빠지면 걸린다
    stories = {int(k): v for k, v in sample("stories.sample.json").items()}
    br = load_reference()
    lit = br.literary_user_message(an, stories, "c1", False, (800, 1200))
    assert lit == (STYLE / "examples" / "literary_user_message.sample.md").read_bytes().decode("utf-8")
    assert lit.endswith(br.LITERARY_SUFFIX) and "제목 미확정" in lit and all(f["id"] in lit for s in an["stories"] for f in s["facts"])
    with pytest.raises(KeyError):                                              # 수필체는 확정 제목 없이는 묶음을 만들 수 없다 — 분석 결과에는 제목 후보만 있다
        br.essay_user_message(an, stories, "c1", False)
    titled = json.loads(json.dumps(an))
    titled["chapters"][0]["title"] = "못 상자와 내의 한 벌"
    essay = br.essay_user_message(titled, stories, "c1", False)
    assert essay == (STYLE / "examples" / "essay_user_message.sample.md").read_bytes().decode("utf-8")
    assert essay.endswith(br.ESSAY_SUFFIX) and all(x in essay for s in an["stories"] for x in s["must_keep"])
    assert "(가정)" not in essay and stories[1] in essay and stories[2] in lit                                  # 원문 전문이 그대로 들어간다


def test_novel_input_is_the_template_with_source_inserted():
    br, tpl = load_reference(), raw("novel").decode("utf-8")
    src = "\n".join(sample("stories.sample.json").values())
    msg = br.novel_user_message(tpl, src)
    assert "{{SOURCE_TEXT}}" not in msg and src in msg and len(msg) == len(tpl) - len("{{SOURCE_TEXT}}") + len(src)
    assert msg.startswith(tpl.split("{{SOURCE_TEXT}}")[0]) and msg.endswith("\n[현재 장 원문 끝]\n")
    with pytest.raises(ValueError):
        br.novel_user_message(raw("essay").decode("utf-8"), src)               # 자리표시가 없는 프롬프트(수필체 · 문학체)에는 쓸 수 없다


def test_paragraph_line_breaks_survive_json_round_trip():
    e = sample("literary_output.sample.json")
    assert any("\n" in p for p in e["paragraphs"])
    again = json.loads(json.dumps(e, ensure_ascii=False))
    assert again["paragraphs"] == e["paragraphs"]
    flat = "\n".join(s for p in e["paragraphs"] for s in re.split(r"(?<=[.!?])\s+", p))      # 문장마다 줄을 바꿔 합치는 방식(현재 응답의 body 가 이 모양)
    assert flat.count("\n") > sum(p.count("\n") for p in e["paragraphs"]) + len(e["paragraphs"]) - 1          # → 문단 경계가 사라진다. 문학체에 쓰면 안 된다


def test_novel_sample_is_plain_text_with_scene_and_dialogue_breaks():
    t = (STYLE / "examples" / "novel_output.sample.txt").read_text(encoding="utf-8")
    assert not t.lstrip().startswith("{") and len(re.split(r"\n\s*\n", t.strip())) >= 5 and sum(1 for ln in t.split("\n") if ln.startswith("“")) >= 3
    assert [w for w in DREAM_TERMS if w in t] == []


def test_no_secrets_or_local_paths_in_style_files():
    pats = [r"sk-[A-Za-z0-9_\-]{16,}", r"AIza[0-9A-Za-z_\-]{20,}", r"AKIA[0-9A-Z]{12,}", r"gh[pousr]_[A-Za-z0-9]{20,}", r"(?i)c:[\\/]+users[\\/]", "/c/" + "users/"]
    for p in STYLE.rglob("*"):
        if p.is_file() and p.suffix in (".md", ".json", ".txt", ".py"):
            t = p.read_text(encoding="utf-8")
            assert not [x for x in pats if re.search(x, t)], p.name


# ---------------------------------------------------------------- 분석 지시문(안전 사본)

ANALYSIS_SHA = "6c2f1afea07e982e7401ed2ef09d357d8e3a202eb7aaab93eda9d9852306d828"      # 안전 사본의 SHA-256 — 실험에 쓴 원본의 해시는 저장소에 싣지 않는다
ANALYSIS = MAN["analysis_dependency"]["included"]["analysis_prompt"]


def analysis_prompt() -> bytes:
    return (STYLE / ANALYSIS["path"]).read_bytes()


def test_analysis_prompt_is_the_safe_copy_and_unchanged():
    b = analysis_prompt()
    assert ANALYSIS["path"] == "analysis/0_원문분석_목차통합_안전사본.md" and [p.name for p in (STYLE / "analysis").iterdir()] == ["0_원문분석_목차통합_안전사본.md"]
    assert hashlib.sha256(b).hexdigest() == ANALYSIS["sha256"] == ANALYSIS_SHA and len(b) == ANALYSIS["bytes"]
    assert b[:3] != b"\xef\xbb\xbf" and b"\r\n" not in b and b.endswith(b"\n")          # 문체 프롬프트와 같은 조건 — 줄바꿈 변환이 걸리면 해시가 달라진다
    t = b.decode("utf-8")
    assert t.count("가상인물_A") == 1 and '"딸 가상인물_A"' in t                          # 예시의 인물 이름 자리 하나만 가상 식별자다
    ch = ANALYSIS["changes"]
    assert (ch["changed_items"], ch["changed_lines"], ch["rules_changed"], ch["fields_changed"], ch["sentences_rewritten"]) == (1, 1, 0, 0, 0)
    assert ANALYSIS["original_hash_published"] is False and "held_back" not in MAN["analysis_dependency"]
    assert "{{" not in t and "```" not in t                                          # 자리표시도 코드 울타리도 없다 — 파일 그대로 시스템 프롬프트로 쓴다


def test_analysis_prompt_names_every_schema_field():
    """분석 지시문과 분석 출력 스키마가 같은 필드를 말하는가 — 묶음 조립(reference/bundle_reference.py)이 그 필드를 읽는다."""
    schema = json.loads((STYLE / "schemas" / "analysis_output.schema.json").read_text(encoding="utf-8"))
    t = analysis_prompt().decode("utf-8")
    st, ch = schema["properties"]["stories"]["items"]["properties"], schema["properties"]["chapters"]["items"]["properties"]
    tb = ch["title_basis"]["properties"]
    names = (set(schema["properties"]) | set(st) | set(st["facts"]["items"]["properties"]) | set(st["emotion_notes"]["items"]["properties"])
             | set(ch) | set(tb) | set(tb["candidates"]["items"]["properties"]))
    assert len(names) == 40
    assert [n for n in sorted(names) if not any(x in t for x in (f"`{n}`", f'"{n}"', f".{n}`"))] == []
    assert st["facts"]["items"]["properties"]["source"]["enum"] == ["self", "heard", "view"] and all(f"`{v}`" in t for v in ("self", "heard", "view", "stated", "approx", "uncertain"))
    assert "`title`" in t and "이 단계에서 정하지 않습니다" in t and "title" not in ch      # 확정 제목은 분석 결과에 없다 — 수필체 묶음에는 따로 넣어야 한다


def test_analysis_example_feeds_bundles_without_real_names():
    an = sample("analysis.sample.json")
    assert all(s["people"] for s in an["stories"]) and "가상" in an["book_title"]
    assert MAN["styles"][2]["approval"] == "다애님 승인 완료 — 소설체 최소 수정 v1"
