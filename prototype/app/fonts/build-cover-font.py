"""Create the locally hosted, 600-weight cover font from a supplied Noto Serif KR TTF.

Dependencies (install in a task-specific directory, never as an OS font):
    fonttools[woff]==4.68.0
The source TTF is deliberately not copied into the product: it is about 24 MB.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from fontTools import subset
from fontTools.ttLib import TTFont
from fontTools.varLib.instancer import instantiateVariableFont


RANGES = (
    (0x0020, 0x024F),  # ASCII and Latin letters
    (0x1100, 0x11FF),  # Hangul Jamo
    (0x1E00, 0x1EFF),  # Latin Extended Additional
    (0x2000, 0x206F),  # General punctuation
    (0x20A0, 0x20CF),  # Currency symbols
    (0x2100, 0x218F),  # Letterlike symbols and number forms
    (0x2E00, 0x2E7F),  # Supplemental punctuation
    (0x3000, 0x303F),  # CJK punctuation; ideographs use the CSS fallback
    (0x3130, 0x318F),  # Hangul compatibility Jamo
    (0xA960, 0xA97F),  # Hangul Jamo Extended-A
    (0xAC00, 0xD7A3),  # Every modern Korean syllable
    (0xD7B0, 0xD7FF),  # Hangul Jamo Extended-B
    (0xFF00, 0xFFEF),  # Fullwidth and halfwidth punctuation / Jamo
)


def name_values(font: TTFont, name_id: int) -> list[str]:
    return sorted({n.toUnicode() for n in font["name"].names if n.nameID == name_id})


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, default=Path(__file__).resolve().parent)
    args = parser.parse_args()
    output_dir = args.output_dir.resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    source = args.source.resolve()
    font = TTFont(source, recalcTimestamp=False)
    source_names = {str(i): name_values(font, i) for i in (1, 2, 6, 13, 14, 16, 17)}
    source_axes = [
        {"tag": axis.axisTag, "min": axis.minValue, "default": axis.defaultValue, "max": axis.maxValue}
        for axis in font["fvar"].axes
    ]
    instantiateVariableFont(font, {"wght": 600}, inplace=True, static=True)
    options = subset.Options()
    options.flavor = "woff2"
    options.recalc_timestamp = False
    options.name_IDs = ["*"]
    options.name_legacy = True
    options.name_languages = ["*"]
    subsetter = subset.Subsetter(options=options)
    subsetter.populate(unicodes=[cp for start, end in RANGES for cp in range(start, end + 1)])
    subsetter.subset(font)

    # Name the derived, subsetted font clearly while retaining the original
    # copyright, license, and license-URL records.
    derived_names = {
        1: "Memoir Cover Serif",
        2: "SemiBold",
        3: "MemoirCoverSerif-SemiBold-600-NotoSerifKR",
        4: "Memoir Cover Serif SemiBold",
        6: "MemoirCoverSerif-SemiBold",
        16: "Memoir Cover Serif",
        17: "SemiBold",
    }
    for record in list(font["name"].names):
        if record.nameID in derived_names:
            font["name"].setName(
                derived_names[record.nameID], record.nameID,
                record.platformID, record.platEncID, record.langID,
            )
    font["OS/2"].usWeightClass = 600
    font.flavor = "woff2"
    output = output_dir / "memoir-cover-serif-600-ko.woff2"
    font.save(output)

    result = TTFont(output)
    cmap = result.getBestCmap()
    missing_hangul = [cp for cp in range(0xAC00, 0xD7A4) if cp not in cmap]
    assert not missing_hangul, f"Missing {len(missing_hangul)} modern Hangul syllables"
    assert "fvar" not in result, "Output must be a static weight"
    assert result["OS/2"].usWeightClass == 600
    assert result["OS/2"].fsType == 0
    assert all(i in cmap for i in range(0x20, 0x7F)), "Printable ASCII must be complete"
    report = {
        "source_file": source.name,
        "source_bytes": source.stat().st_size,
        "source_sha256": hashlib.sha256(source.read_bytes()).hexdigest(),
        "source_name_metadata": source_names,
        "source_variable_axes": source_axes,
        "derived_file": output.name,
        "derived_bytes": output.stat().st_size,
        "derived_sha256": hashlib.sha256(output.read_bytes()).hexdigest(),
        "derived_family": name_values(result, 16),
        "derived_subfamily": name_values(result, 17),
        "derived_weight": result["OS/2"].usWeightClass,
        "derived_is_variable": "fvar" in result,
        "embedding_fsType": result["OS/2"].fsType,
        "unicode_ranges_requested": [f"U+{start:04X}-{end:04X}" for start, end in RANGES],
        "mapped_codepoints": len(cmap),
        "modern_hangul_syllables": 11172,
        "missing_modern_hangul": 0,
        "printable_ascii_complete": True,
        "license": "SIL Open Font License 1.1; see OFL-NotoSerifKR.txt",
    }
    (output_dir / "cover-font-metadata.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8",
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
