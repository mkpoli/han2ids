"""Bounded, self-contained IDS parsing and image-reference evaluation.

An input is one Unicode IDS tree (a single component is a tree). Supported
leaves are CJK ideographs, radicals, strokes and U+3007, optionally followed by
one variation selector. Out-of-scope Unicode letters and symbols, extended
notation, and unknown placeholders are unscorable. No component expansion or
implicit equivalence is performed.

Unicode 17, Chapter 18: https://www.unicode.org/versions/Unicode17.0.0/core-spec/chapter-18/
Unicode 17 CJK assignments: https://www.unicode.org/irg/docs/n2856-CJKUIv17.pdf
Unicode 17 UCD: https://www.unicode.org/Public/17.0.0/ucd/UnicodeData.txt
"""
from __future__ import annotations

from bisect import bisect_right
from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Optional, Sequence, Union

ARITY = {
    "⿰": 2, "⿱": 2, "⿲": 3, "⿳": 3,
    "⿴": 2, "⿵": 2, "⿶": 2, "⿷": 2, "⿸": 2, "⿹": 2,
    "⿺": 2, "⿻": 2, "⿼": 2, "⿽": 2, "⿾": 1, "⿿": 1, "㇯": 2,
    "〾": 1,  # Unicode ideographic variation indicator

}
# Extensions, entity references, and stroke-program notation.
_EXTENDED = frozenset("{}[]&;$#()")
_UNKNOWN = frozenset("?？")

# Assigned, non-private Unicode 17 characters in the supported component
# blocks, derived from UnicodeData.txt (SHA-256:
# 2e1efc1dcb59c575eedf5ccae60f95229f706ee6d031835247d843c11d96470c).
# UnicodeData First/Last records are expanded before intersecting the blocks.
_COMPONENT_RANGES = (
    (0x2E80, 0x2E99), (0x2E9B, 0x2EF3), (0x2F00, 0x2FD5),
    (0x3007, 0x3007), (0x31C0, 0x31E5), (0x3400, 0x4DBF),
    (0x4E00, 0x9FFF), (0xF900, 0xFA6D), (0xFA70, 0xFAD9),
    (0x20000, 0x2A6DF), (0x2A700, 0x2B81D), (0x2B820, 0x2CEAD),
    (0x2CEB0, 0x2EBE0), (0x2EBF0, 0x2EE5D), (0x2F800, 0x2FA1D),
    (0x30000, 0x3134A), (0x31350, 0x33479),
)
# Unicode 17 non-ASCII assigned letter and symbol ranges (L* or S*).
# The source is UnicodeData.txt and its SHA-256 is recorded above. These
# ranges only identify unsupported leaves; they never make a tree scorable.
_OTHER_SCALAR_RANGES = tuple(tuple(int(x, 16) for x in item.split("-")) for item in (
    "A2-A6 A8-AA AC-AC AE-B1 B4-B5 B8-B8 BA-BA C0-2FF 370-377 37A-37D 37F-37F 384-386 388-38A 38C-38C 38E-3A1 "
    "3A3-482 48A-52F 531-556 559-559 560-588 58D-58F 5D0-5EA 5EF-5F2 606-608 60B-60B 60E-60F 620-64A 66E-66F "
    "671-6D3 6D5-6D5 6DE-6DE 6E5-6E6 6E9-6E9 6EE-6EF 6FA-6FF 710-710 712-72F 74D-7A5 7B1-7B1 7CA-7EA 7F4-7F6 "
    "7FA-7FA 7FE-815 81A-81A 824-824 828-828 840-858 860-86A 870-88F 8A0-8C9 904-939 93D-93D 950-950 958-961 "
    "971-980 985-98C 98F-990 993-9A8 9AA-9B0 9B2-9B2 9B6-9B9 9BD-9BD 9CE-9CE 9DC-9DD 9DF-9E1 9F0-9F3 9FA-9FC "
    "A05-A0A A0F-A10 A13-A28 A2A-A30 A32-A33 A35-A36 A38-A39 A59-A5C A5E-A5E A72-A74 A85-A8D A8F-A91 A93-AA8 "
    "AAA-AB0 AB2-AB3 AB5-AB9 ABD-ABD AD0-AD0 AE0-AE1 AF1-AF1 AF9-AF9 B05-B0C B0F-B10 B13-B28 B2A-B30 B32-B33 "
    "B35-B39 B3D-B3D B5C-B5D B5F-B61 B70-B71 B83-B83 B85-B8A B8E-B90 B92-B95 B99-B9A B9C-B9C B9E-B9F BA3-BA4 "
    "BA8-BAA BAE-BB9 BD0-BD0 BF3-BFA C05-C0C C0E-C10 C12-C28 C2A-C39 C3D-C3D C58-C5A C5C-C5D C60-C61 C7F-C80 "
    "C85-C8C C8E-C90 C92-CA8 CAA-CB3 CB5-CB9 CBD-CBD CDC-CDE CE0-CE1 CF1-CF2 D04-D0C D0E-D10 D12-D3A D3D-D3D "
    "D4E-D4F D54-D56 D5F-D61 D79-D7F D85-D96 D9A-DB1 DB3-DBB DBD-DBD DC0-DC6 E01-E30 E32-E33 E3F-E46 E81-E82 "
    "E84-E84 E86-E8A E8C-EA3 EA5-EA5 EA7-EB0 EB2-EB3 EBD-EBD EC0-EC4 EC6-EC6 EDC-EDF F00-F03 F13-F13 F15-F17 "
    "F1A-F1F F34-F34 F36-F36 F38-F38 F40-F47 F49-F6C F88-F8C FBE-FC5 FC7-FCC FCE-FCF FD5-FD8 1000-102A 103F-103F "
    "1050-1055 105A-105D 1061-1061 1065-1066 106E-1070 1075-1081 108E-108E 109E-10C5 10C7-10C7 10CD-10CD 10D0-10FA "
    "10FC-1248 124A-124D 1250-1256 1258-1258 125A-125D 1260-1288 128A-128D 1290-12B0 12B2-12B5 12B8-12BE 12C0-12C0 "
    "12C2-12C5 12C8-12D6 12D8-1310 1312-1315 1318-135A 1380-1399 13A0-13F5 13F8-13FD 1401-166D 166F-167F 1681-169A "
    "16A0-16EA 16F1-16F8 1700-1711 171F-1731 1740-1751 1760-176C 176E-1770 1780-17B3 17D7-17D7 17DB-17DC 1820-1878 "
    "1880-1884 1887-18A8 18AA-18AA 18B0-18F5 1900-191E 1940-1940 1950-196D 1970-1974 1980-19AB 19B0-19C9 19DE-1A16 "
    "1A20-1A54 1AA7-1AA7 1B05-1B33 1B45-1B4C 1B61-1B6A 1B74-1B7C 1B83-1BA0 1BAE-1BAF 1BBA-1BE5 1C00-1C23 1C4D-1C4F "
    "1C5A-1C7D 1C80-1C8A 1C90-1CBA 1CBD-1CBF 1CE9-1CEC 1CEE-1CF3 1CF5-1CF6 1CFA-1CFA 1D00-1DBF 1E00-1F15 1F18-1F1D "
    "1F20-1F45 1F48-1F4D 1F50-1F57 1F59-1F59 1F5B-1F5B 1F5D-1F5D 1F5F-1F7D 1F80-1FB4 1FB6-1FC4 1FC6-1FD3 1FD6-1FDB "
    "1FDD-1FEF 1FF2-1FF4 1FF6-1FFE 2044-2044 2052-2052 2071-2071 207A-207C 207F-207F 208A-208C 2090-209C 20A0-20C1 "
    "2100-214F 2183-2184 218A-218B 2190-2307 230C-2328 232B-2429 2440-244A 249C-24E9 2500-2767 2794-27C4 27C7-27E5 "
    "27F0-2982 2999-29D7 29DC-29FB 29FE-2B73 2B76-2CEE 2CF2-2CF3 2D00-2D25 2D27-2D27 2D2D-2D2D 2D30-2D67 2D6F-2D6F "
    "2D80-2D96 2DA0-2DA6 2DA8-2DAE 2DB0-2DB6 2DB8-2DBE 2DC0-2DC6 2DC8-2DCE 2DD0-2DD6 2DD8-2DDE 2E2F-2E2F 2E50-2E51 "
    "2E80-2E99 2E9B-2EF3 2F00-2FD5 2FF0-2FFF 3004-3006 3012-3013 3020-3020 3031-3037 303B-303C 303E-303F 3041-3096 "
    "309B-309F 30A1-30FA 30FC-30FF 3105-312F 3131-318E 3190-3191 3196-31E5 31EF-321E 322A-3247 3250-3250 3260-327F "
    "328A-32B0 32C0-A48C A490-A4C6 A4D0-A4FD A500-A60C A610-A61F A62A-A62B A640-A66E A67F-A69D A6A0-A6E5 A700-A7DC "
    "A7F1-A801 A803-A805 A807-A80A A80C-A822 A828-A82B A836-A839 A840-A873 A882-A8B3 A8F2-A8F7 A8FB-A8FB A8FD-A8FE "
    "A90A-A925 A930-A946 A960-A97C A984-A9B2 A9CF-A9CF A9E0-A9E4 A9E6-A9EF A9FA-A9FE AA00-AA28 AA40-AA42 AA44-AA4B "
    "AA60-AA7A AA7E-AAAF AAB1-AAB1 AAB5-AAB6 AAB9-AABD AAC0-AAC0 AAC2-AAC2 AADB-AADD AAE0-AAEA AAF2-AAF4 AB01-AB06 "
    "AB09-AB0E AB11-AB16 AB20-AB26 AB28-AB2E AB30-AB6B AB70-ABE2 AC00-D7A3 D7B0-D7C6 D7CB-D7FB F900-FA6D FA70-FAD9 "
    "FB00-FB06 FB13-FB17 FB1D-FB1D FB1F-FB36 FB38-FB3C FB3E-FB3E FB40-FB41 FB43-FB44 FB46-FD3D FD40-FDCF FDF0-FDFF "
    "FE62-FE62 FE64-FE66 FE69-FE69 FE70-FE74 FE76-FEFC FF04-FF04 FF0B-FF0B FF1C-FF1E FF21-FF3A FF3E-FF3E FF40-FF5A "
    "FF5C-FF5C FF5E-FF5E FF66-FFBE FFC2-FFC7 FFCA-FFCF FFD2-FFD7 FFDA-FFDC FFE0-FFE6 FFE8-FFEE FFFC-FFFD "
    "10000-1000B 1000D-10026 10028-1003A 1003C-1003D 1003F-1004D 10050-1005D 10080-100FA 10137-1013F 10179-10189 "
    "1018C-1018E 10190-1019C 101A0-101A0 101D0-101FC 10280-1029C 102A0-102D0 10300-1031F 1032D-10340 10342-10349 "
    "10350-10375 10380-1039D 103A0-103C3 103C8-103CF 10400-1049D 104B0-104D3 104D8-104FB 10500-10527 10530-10563 "
    "10570-1057A 1057C-1058A 1058C-10592 10594-10595 10597-105A1 105A3-105B1 105B3-105B9 105BB-105BC 105C0-105F3 "
    "10600-10736 10740-10755 10760-10767 10780-10785 10787-107B0 107B2-107BA 10800-10805 10808-10808 1080A-10835 "
    "10837-10838 1083C-1083C 1083F-10855 10860-10878 10880-1089E 108E0-108F2 108F4-108F5 10900-10915 10920-10939 "
    "10940-10959 10980-109B7 109BE-109BF 10A00-10A00 10A10-10A13 10A15-10A17 10A19-10A35 10A60-10A7C 10A80-10A9C "
    "10AC0-10AE4 10B00-10B35 10B40-10B55 10B60-10B72 10B80-10B91 10C00-10C48 10C80-10CB2 10CC0-10CF2 10D00-10D23 "
    "10D4A-10D65 10D6F-10D85 10D8E-10D8F 10E80-10EA9 10EB0-10EB1 10EC2-10EC7 10ED1-10ED8 10F00-10F1C 10F27-10F27 "
    "10F30-10F45 10F70-10F81 10FB0-10FC4 10FE0-10FF6 11003-11037 11071-11072 11075-11075 11083-110AF 110D0-110E8 "
    "11103-11126 11144-11144 11147-11147 11150-11172 11176-11176 11183-111B2 111C1-111C4 111DA-111DA 111DC-111DC "
    "11200-11211 11213-1122B 1123F-11240 11280-11286 11288-11288 1128A-1128D 1128F-1129D 1129F-112A8 112B0-112DE "
    "11305-1130C 1130F-11310 11313-11328 1132A-11330 11332-11333 11335-11339 1133D-1133D 11350-11350 1135D-11361 "
    "11380-11389 1138B-1138B 1138E-1138E 11390-113B5 113B7-113B7 113D1-113D1 113D3-113D3 11400-11434 11447-1144A "
    "1145F-11461 11480-114AF 114C4-114C5 114C7-114C7 11580-115AE 115D8-115DB 11600-1162F 11644-11644 11680-116AA "
    "116B8-116B8 11700-1171A 1173F-11746 11800-1182B 118A0-118DF 118FF-11906 11909-11909 1190C-11913 11915-11916 "
    "11918-1192F 1193F-1193F 11941-11941 119A0-119A7 119AA-119D0 119E1-119E1 119E3-119E3 11A00-11A00 11A0B-11A32 "
    "11A3A-11A3A 11A50-11A50 11A5C-11A89 11A9D-11A9D 11AB0-11AF8 11BC0-11BE0 11C00-11C08 11C0A-11C2E 11C40-11C40 "
    "11C72-11C8F 11D00-11D06 11D08-11D09 11D0B-11D30 11D46-11D46 11D60-11D65 11D67-11D68 11D6A-11D89 11D98-11D98 "
    "11DB0-11DDB 11EE0-11EF2 11F02-11F02 11F04-11F10 11F12-11F33 11FB0-11FB0 11FD5-11FF1 12000-12399 12480-12543 "
    "12F90-12FF0 13000-1342F 13441-13446 13460-143FA 14400-14646 16100-1611D 16800-16A38 16A40-16A5E 16A70-16ABE "
    "16AD0-16AED 16B00-16B2F 16B3C-16B43 16B45-16B45 16B63-16B77 16B7D-16B8F 16D40-16D6C 16E40-16E7F 16EA0-16EB8 "
    "16EBB-16ED3 16F00-16F4A 16F50-16F50 16F93-16F9F 16FE0-16FE1 16FE3-16FE3 16FF2-16FF3 17000-18CD5 18CFF-18D1E "
    "18D80-18DF2 1AFF0-1AFF3 1AFF5-1AFFB 1AFFD-1AFFE 1B000-1B122 1B132-1B132 1B150-1B152 1B155-1B155 1B164-1B167 "
    "1B170-1B2FB 1BC00-1BC6A 1BC70-1BC7C 1BC80-1BC88 1BC90-1BC99 1BC9C-1BC9C 1CC00-1CCEF 1CCFA-1CCFC 1CD00-1CEB3 "
    "1CEBA-1CED0 1CEE0-1CEF0 1CF50-1CFC3 1D000-1D0F5 1D100-1D126 1D129-1D164 1D16A-1D16C 1D183-1D184 1D18C-1D1A9 "
    "1D1AE-1D1EA 1D200-1D241 1D245-1D245 1D300-1D356 1D400-1D454 1D456-1D49C 1D49E-1D49F 1D4A2-1D4A2 1D4A5-1D4A6 "
    "1D4A9-1D4AC 1D4AE-1D4B9 1D4BB-1D4BB 1D4BD-1D4C3 1D4C5-1D505 1D507-1D50A 1D50D-1D514 1D516-1D51C 1D51E-1D539 "
    "1D53B-1D53E 1D540-1D544 1D546-1D546 1D54A-1D550 1D552-1D6A5 1D6A8-1D7CB 1D800-1D9FF 1DA37-1DA3A 1DA6D-1DA74 "
    "1DA76-1DA83 1DA85-1DA86 1DF00-1DF1E 1DF25-1DF2A 1E030-1E06D 1E100-1E12C 1E137-1E13D 1E14E-1E14F 1E290-1E2AD "
    "1E2C0-1E2EB 1E2FF-1E2FF 1E4D0-1E4EB 1E5D0-1E5ED 1E5F0-1E5F0 1E6C0-1E6DE 1E6E0-1E6E2 1E6E4-1E6E5 1E6E7-1E6ED "
    "1E6F0-1E6F4 1E6FE-1E6FF 1E7E0-1E7E6 1E7E8-1E7EB 1E7ED-1E7EE 1E7F0-1E7FE 1E800-1E8C4 1E900-1E943 1E94B-1E94B "
    "1ECAC-1ECAC 1ECB0-1ECB0 1ED2E-1ED2E 1EE00-1EE03 1EE05-1EE1F 1EE21-1EE22 1EE24-1EE24 1EE27-1EE27 1EE29-1EE32 "
    "1EE34-1EE37 1EE39-1EE39 1EE3B-1EE3B 1EE42-1EE42 1EE47-1EE47 1EE49-1EE49 1EE4B-1EE4B 1EE4D-1EE4F 1EE51-1EE52 "
    "1EE54-1EE54 1EE57-1EE57 1EE59-1EE59 1EE5B-1EE5B 1EE5D-1EE5D 1EE5F-1EE5F 1EE61-1EE62 1EE64-1EE64 1EE67-1EE6A "
    "1EE6C-1EE72 1EE74-1EE77 1EE79-1EE7C 1EE7E-1EE7E 1EE80-1EE89 1EE8B-1EE9B 1EEA1-1EEA3 1EEA5-1EEA9 1EEAB-1EEBB "
    "1EEF0-1EEF1 1F000-1F02B 1F030-1F093 1F0A0-1F0AE 1F0B1-1F0BF 1F0C1-1F0CF 1F0D1-1F0F5 1F10D-1F1AD 1F1E6-1F202 "
    "1F210-1F23B 1F240-1F248 1F250-1F251 1F260-1F265 1F300-1F6D8 1F6DC-1F6EC 1F6F0-1F6FC 1F700-1F7D9 1F7E0-1F7EB "
    "1F7F0-1F7F0 1F800-1F80B 1F810-1F847 1F850-1F859 1F860-1F887 1F890-1F8AD 1F8B0-1F8BB 1F8C0-1F8C1 1F8D0-1F8D8 "
    "1F900-1FA57 1FA60-1FA6D 1FA70-1FA7C 1FA80-1FA8A 1FA8E-1FAC6 1FAC8-1FAC8 1FACD-1FADC 1FADF-1FAEA 1FAEF-1FAF8 "
    "1FB00-1FB92 1FB94-1FBEF 1FBFA-1FBFA 20000-2A6DF 2A700-2B81D 2B820-2CEAD 2CEB0-2EBE0 2EBF0-2EE5D 2F800-2FA1D "
    "30000-3134A 31350-33479 "
).split())
_OTHER_SCALAR_STARTS = tuple(lo for lo, _ in _OTHER_SCALAR_RANGES)

_MAX_LENGTH = 512
_MAX_DEPTH = 64


@dataclass(frozen=True)
class Leaf:
    component: str


@dataclass(frozen=True)
class Node:
    operator: str
    children: tuple[Tree, ...]


Tree = Union[Leaf, Node]
# Positions are paths of (normalized parent operator, zero-based child index).
Position = tuple[tuple[str, int], ...]


@dataclass(frozen=True)
class FamilyRule:
    """Allow direct substitutions at exact paths or terminal parent/child contexts."""
    components: frozenset[str]
    positions: frozenset[Position] = frozenset()
    contexts: frozenset[tuple[str, int]] = frozenset()


@dataclass(frozen=True)
class ParseResult:
    status: str  # valid, invalid, unsupported
    tree: Optional[Tree] = None
    reason: str = ""


def _selector(char: str) -> bool:
    n = ord(char)
    return 0xFE00 <= n <= 0xFE0F or 0xE0100 <= n <= 0xE01EF


def _component(char: str) -> bool:
    n = ord(char)
    return any(lo <= n <= hi for lo, hi in _COMPONENT_RANGES)


def _other_scalar(char: str) -> bool:
    """Identify an assigned non-ASCII Unicode letter or symbol."""
    n = ord(char)
    index = bisect_right(_OTHER_SCALAR_STARTS, n) - 1
    return index >= 0 and n <= _OTHER_SCALAR_RANGES[index][1]


def parse_ids(text: str) -> ParseResult:
    """Parse a bounded IDS, distinguishing malformed from unsupported input."""
    if not isinstance(text, str):
        return ParseResult("invalid", reason="input must be text")
    if len(text) > _MAX_LENGTH:
        return ParseResult("invalid", reason="input length limit exceeded")
    # Extended programs can encode multiple operands, so their grammar is opaque.
    if any(c in _EXTENDED for c in text):
        return ParseResult("unsupported", reason="extended syntax")
    if not text:
        return ParseResult("invalid", reason="empty input")
    at = 0
    unsupported_reasons = set()

    def parse(depth: int) -> Tree:
        nonlocal at
        if depth > _MAX_DEPTH:
            raise ValueError("depth limit exceeded")
        if at >= len(text):
            raise ValueError("missing operand")
        char = text[at]
        at += 1
        if char in ARITY:
            return Node(char, tuple(parse(depth + 1) for _ in range(ARITY[char])))
        if char in _UNKNOWN:
            unsupported_reasons.add("unknown component placeholder")
        elif (0xE000 <= ord(char) <= 0xF8FF or 0xF0000 <= ord(char) <= 0xFFFFD
              or 0x100000 <= ord(char) <= 0x10FFFD):
            unsupported_reasons.add("private-use component")
        elif not _component(char):
            if not _other_scalar(char):
                raise ValueError("invalid component")
            unsupported_reasons.add("out-of-scope letter or symbol component")
        if at < len(text) and _selector(text[at]):
            char += text[at]
            at += 1
        return Leaf(char)

    try:
        tree = parse(0)
        if at != len(text):
            raise ValueError("trailing input")
        if unsupported_reasons:
            return ParseResult("unsupported", reason="; ".join(sorted(unsupported_reasons)))
        return ParseResult("valid", tree)
    except ValueError as exc:
        return ParseResult("invalid", reason=str(exc))


def normalize(tree: Tree) -> Tree:
    """Flatten consecutive horizontal or vertical nodes, retaining all children."""
    if isinstance(tree, Leaf):
        return tree
    axis = "H" if tree.operator in "⿰⿲" else "V" if tree.operator in "⿱⿳" else None
    children = tuple(normalize(child) for child in tree.children)
    if axis:
        flat = []
        for child in children:
            if isinstance(child, Node) and child.operator == axis:
                flat.extend(child.children)
            else:
                flat.append(child)
        return Node(axis, tuple(flat))
    return Node(tree.operator, children)


def _skeleton(tree: Tree):
    if isinstance(tree, Leaf):
        return None
    return tree.operator, tuple(_skeleton(child) for child in tree.children)


def _components(tree: Tree) -> Counter[str]:
    if isinstance(tree, Leaf):
        return Counter((tree.component,))
    result: Counter[str] = Counter()
    for child in tree.children:
        result.update(_components(child))
    return result


def _family_match(a: Tree, b: Tree, rules: Sequence[FamilyRule], path: Position = ()) -> bool:
    if isinstance(a, Leaf) and isinstance(b, Leaf):
        return a == b or bool(path) and any(
            (path in rule.positions or path[-1] in rule.contexts)
            and a.component in rule.components and b.component in rule.components
            for rule in rules)
    if not isinstance(a, Node) or not isinstance(b, Node):
        return False
    return (a.operator == b.operator and len(a.children) == len(b.children)
            and all(_family_match(x, y, rules, path + ((a.operator, i),))
                    for i, (x, y) in enumerate(zip(a.children, b.children))))


@dataclass(frozen=True)
class Evaluation:
    prediction_status: str
    reference_statuses: tuple[str, ...]
    raw_exact: Optional[bool]
    structural_match: Optional[bool]
    family_match: Optional[bool]
    skeleton_accuracy: Optional[bool]
    component_precision: Optional[float]
    component_recall: Optional[float]
    component_f1: Optional[float]
    tree_edit_similarity: Optional[float] = None
    tree_edit_status: str = "disabled"


def _postorder(tree: Tree):
    """Return labels, leftmost-descendant indices and keyroots, one-indexed."""
    labels = [None]
    leftmost = [0]

    def visit(node: Tree) -> int:
        first = None
        if isinstance(node, Node):
            for child in node.children:
                index = visit(child)
                if first is None:
                    first = leftmost[index]
            label = "H" if node.operator in "⿰⿲" else "V" if node.operator in "⿱⿳" else node.operator
            label = ("operator", label)
        else:
            label = ("leaf", node.component)
        labels.append(label)
        leftmost.append(first if first is not None else len(labels) - 1)
        return len(labels) - 1

    visit(tree)
    roots = {}
    for i in range(1, len(labels)):
        roots[leftmost[i]] = i
    return labels, leftmost, sorted(roots.values())


def _tree_distance(a: Tree, b: Tree) -> tuple[int, int]:
    """Ordered tree edit distance with child promotion, bounded by the caller."""
    al, ax, ak = _postorder(a)
    bl, bx, bk = _postorder(b)
    dist = [[0] * len(bl) for _ in al]
    for i in ak:
        for j in bk:
            start_i, start_j = ax[i], bx[j]
            forest = [[0] * (j - start_j + 2) for _ in range(i - start_i + 2)]
            for x in range(start_i, i + 1):
                forest[x - start_i + 1][0] = x - start_i + 1
            for y in range(start_j, j + 1):
                forest[0][y - start_j + 1] = y - start_j + 1
            for x in range(start_i, i + 1):
                for y in range(start_j, j + 1):
                    row, col = x - start_i + 1, y - start_j + 1
                    delete = forest[row - 1][col] + 1
                    insert = forest[row][col - 1] + 1
                    if ax[x] == start_i and bx[y] == start_j:
                        replace = forest[row - 1][col - 1] + (0 if al[x] == bl[y] else 2)
                        forest[row][col] = min(delete, insert, replace)
                        dist[x][y] = forest[row][col]
                    else:
                        replace = forest[ax[x] - start_i][bx[y] - start_j] + dist[x][y]
                        forest[row][col] = min(delete, insert, replace)
    return dist[-1][-1], len(al) + len(bl) - 2


def evaluate(prediction: str, references: Iterable[str], *,
             family_rules: Optional[Sequence[FamilyRule]] = None,
             tree_edit: bool = False) -> Evaluation:
    """Score one prediction against references belonging to the same image.

    Each boolean accepts any valid reference. Component metrics use the single
    reference with highest F1 (first on ties). Invalid references are reported
    and excluded. Missing valid inputs yield None for every score. Tree-edit
    similarity uses normalized trees, unit insert/delete, substitution cost two,
    and total node count as denominator; it is capped at 64 nodes per tree.
    """
    refs = tuple(references)
    pred = parse_ids(prediction)
    parsed_refs = tuple(parse_ids(ref) for ref in refs)
    statuses = tuple(ref.status for ref in parsed_refs)
    valid = [(text, result.tree) for text, result in zip(refs, parsed_refs)
             if result.status == "valid"]
    if pred.status != "valid" or not valid:
        return Evaluation(pred.status, statuses, None, None, None, None, None, None, None,
                          None, "unscorable" if tree_edit else "disabled")
    assert pred.tree is not None
    p = normalize(pred.tree)
    trees = [(text, normalize(tree)) for text, tree in valid if tree is not None]
    pc = _components(p)
    best = (-1.0, 0.0, 0.0)
    for _, tree in trees:
        rc = _components(tree)
        overlap = sum((pc & rc).values())
        precision = overlap / sum(pc.values())
        recall = overlap / sum(rc.values())
        f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
        if f1 > best[0]:
            best = (f1, precision, recall)
    edit_status, edit_score = "disabled", None
    if tree_edit:
        # A cap applies to every candidate so an omitted candidate cannot bias the maximum.
        if len(_postorder(p)[0]) - 1 > 64 or any(
                len(_postorder(tree)[0]) - 1 > 64 for _, tree in trees):
            edit_status = "unsupported"
        else:
            similarities = []
            for _, tree in trees:
                distance, total = _tree_distance(p, tree)
                similarities.append(1 - distance / total)
            edit_score, edit_status = max(similarities), "valid"
    return Evaluation(
        pred.status, statuses,
        any(prediction == text for text, _ in trees),
        any(p == tree for _, tree in trees),
        None if family_rules is None else any(_family_match(p, tree, family_rules) for _, tree in trees),
        any(_skeleton(p) == _skeleton(tree) for _, tree in trees),
        best[1], best[2], best[0], edit_score, edit_status,
    )
