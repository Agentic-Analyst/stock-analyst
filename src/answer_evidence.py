"""The deterministic checks on the analysis section a guarded answer carries.

When the publication guard cannot accept a draft it answers with a fixed
template: the rating or refusal, and the Street's numbers. On its own that
discarded everything the run had established -- the price and its trend, the
technicals, the news with its catalysts and risks, the bull and bear case. A
user who asked "should I buy or hold XOM?" watched six findings arrive and then
read two sentences.

The chat agent now asks the model for the analysis alone and publishes it with
the template only if it passes two checks (GeneralistAgent._add_analysis). This
module is the first: deterministic, and deliberately precise. It

- strips what merely repeats the template: the rating status ("NOT RATED") and
  the Street's targets and ratings, and news sentiment the run cannot support;
- finds EXPLICIT claims only a published rating may make: a rating word used as
  a rating, a price target, a fair value with a number, over- or undervalued, a
  value per share for a scenario, a withheld run's point figures. Any one of
  them and the section is not published at all.

Softer calls ("the risk/reward looks favorable", "worth owning", "stay on the
sidelines") and paraphrases ("could climb to $250") are the second check's job,
a yes/no model verdict. Two reviews showed why: a pattern list for them either
misses most phrasings or deletes real evidence ("agreed to buy Pioneer", "the
Fed's 2% target", "cheap Chinese EVs"). Nothing here edits a claim out of a
section: a section that makes one is the model not doing as asked, and the
template alone is always the fallback.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from typing import Iterable, List, Pattern, Sequence

_DASHES = dict.fromkeys(map(ord, "‐‑‒–—―−﹣－"), "-")
_APOSTROPHES = dict.fromkeys(map(ord, "‘’ʼ＇`´"), "'")
_INVISIBLE = dict.fromkeys(
    map(ord, "​‌‍⁠⁡⁢⁣⁤﻿­"), None
)


def _normalize(text: str) -> str:
    """One spelling for matching: NFKC, ASCII hyphens and apostrophes, no invisibles or emphasis."""
    text = unicodedata.normalize("NFKC", str(text or ""))
    text = text.translate(_DASHES).translate(_APOSTROPHES).translate(_INVISIBLE)
    return re.sub(r"[*_`]", "", text)


_RATING_WORDS = r"(?:strong\s+)?(?:buy|hold|sell|accumulate|outperform|underperform|overweight|underweight)"
# A rating word used as a rating: labelled, attributed, or standing alone as the
# verdict. Not its other senses: "adults with obesity or overweight", "the
# equal-weight S&P 500", "investors are net underweight Chinese equities",
# "rates hold near current levels", "Earnings call: positive".
_RATING_CLAIM = re.compile(
    r"(?<![-\w])(?:strong[-\s]+(?:buy|sell)|top\s+pick|(?:market|sector)\s+perform)(?![-\w])"
    r"|(?<![-\w])(?<!obesity or )(?<!obese or )(?<!net )(?:overweight|underweight)(?![-\w])"
    r"(?!\s+(?:or\s+obes|and\s+obes|adults|patients|people|individuals|children|with\b))"
    r"|(?<![-\w])equal[-\s]weight(?![-\w])(?!(?:ed)?\s+(?:s&p|index|indices|etf|benchmark|version|portfolio))"
    rf"|\b{_RATING_WORDS}\s+(?:rating|recommendation|call)\b"
    rf"|\b(?:rated|rating|recommend\w*)\s+(?:it|this|the\s+(?:stock|shares|name))?\s*(?:as\s+|at\s+)?(?:an?\s+)?{_RATING_WORDS}\b"
    rf"|\brates?\s+(?:(?:it|this|the\s+(?:stock|shares|name))\s+(?:as\s+|at\s+)?(?:an?\s+)?|(?:as|at)\s+(?:an?\s+)?|an?\s+){_RATING_WORDS}\b"
    r"|(?<!earnings )(?<!conference )(?<!investor )(?<!credit )(?<!fed )(?<!policy )(?<!monetary )"
    r"\b(?:rating|stance|verdict|recommendation|call|my\s+take|our\s+take|bottom\s+line)\s*[:：]\s*"
    rf"(?:{_RATING_WORDS}|avoid|neutral|positive|negative|bullish|bearish)\b"
    rf"|^\W*{_RATING_WORDS}\W*$"
    r"|\b(?:my|our)\s+(?:rating|recommendation|price\s+target|target\s+price|fair\s+value|pick|verdict|stance)\b"
    r"|\b(?:i|we)\s+(?:would\s+|'d\s+)?(?:rate|recommend)\b"
    r"|\b(?:i|we)\s*(?:am|are|'m|'re|remain|stay|would\s+be|'d\s+be)\s+(?:\w+\s+)?(?:overweight|underweight|equal[-\s]weight)\b",
    re.I | re.M,
)
_AGGREGATE = r"(?:billion|million|trillion|bn|mn|[mbk]\b)"
# A figure per share, not an aggregate: "$240", not "$200 billion" or "$112-120 billion".
_PER_SHARE = (
    r"(?:[$€£¥₹]|\b(?:USD|EUR|GBP|US\$)\s?)\d[\d,]*(?:\.\d+)?"
    rf"(?![\d,.]*(?:\s*(?:-|to)\s*[$€£¥₹]?\d[\d,.]*)?\s*{_AGGREGATE})"
    r"|(?<![\d,.])\d[\d,]*(?:\.\d+)?\s?(?:美元|港元|元|日元|欧元)(?![亿万])"
)
_PCT = r"(?<![\d,.])\d[\d,]*(?:\.\d+)?\s?%"
_NOT_AGGREGATE = rf"(?<![\d,.])\d[\d,]*(?:\.\d+)?(?![\d,]|\.\d)(?!\s*{_AGGREGATE})"
_VALUE_CLAIM = re.compile(
    r"\b(?:under|over)[-\s]?valued\b"
    # overpriced about the stock, not "catastrophe risk the industry had underpriced"
    r"|\b(?:stock|shares|it|name|equity|company|(?-i:[A-Z][\w&.'-]*))\s+(?:is|are|was|were|looks?|seems?|"
    r"appears?|remains?|trades?|traded|became|becomes|now)\s+(?:\w+\s+){0,2}(?:under|over)[-\s]?priced\b"
    r"|\b(?:under|over)[-\s]?priced\s+(?:stock|shares|name|equity)\b"
    r"|\b(?:fairly|fully|richly|attractively|reasonably|cheaply)\s+valued\b"
    # a fair value with a figure, not "carried at fair value, narrowed to $4.2 billion"
    rf"|\b(?:fair|intrinsic)[-\s]?value\b[^.\n]{{0,40}}?{_NOT_AGGREGATE}"
    rf"|{_NOT_AGGREGATE}[^.\n]{{0,25}}?\b(?:fair|intrinsic)[-\s]?value\b"
    r"|\bprice\s+(?:targets?|objectives?)\b|\btarget\s+prices?\b|\b(?-i:PTs?)\s*(?::|of|at|\$|~)"
    r"|\bworth\s+(?:about|around|roughly|approximately|~)?\s*[$€£¥₹]\s?\d[\d,]*(?:\.\d+)?"
    rf"(?![\d,.]*\s*{_AGGREGATE})",
    re.I,
)
_UP_DOWN = r"(?:upside|downside)"
_ABOUT = r"(?:about|around|roughly|approximately|nearly|almost|over|more\s+than|at\s+least|~)"
_PRICED_CLAIM = re.compile(
    # upside or downside stated as a figure, not the word near an unrelated
    # percentage ("the main downside is China exposure, 17% of revenue")
    rf"\b{_UP_DOWN}\s+(?:potential\s+)?(?:(?:of|to|toward|towards|is|at|near)\s+)?(?:{_ABOUT}\s*)?(?:{_PER_SHARE}|{_PCT})"
    rf"|(?:{_PER_SHARE}|{_PCT})\s+(?:of\s+)?(?:{_ABOUT}\s+)?(?:potential\s+|further\s+|additional\s+|more\s+|"
    rf"possible\s+|implied\s+)?{_UP_DOWN}\b"
    rf"|\b(?:expected|implied|potential)\s+returns?\b[^\n]{{0,40}}?{_PCT}"
    rf"|{_PCT}[^\n]{{0,30}}?\b(?:expected|implied|potential)\s+returns?\b"
    r"|\breturns?\s+from\s+here\b"
    # a valuation model's value per share, not "Tesla's direct-sales model gives it $2,000 per car"
    rf"|\b(?:dcf|valuation|(?:the|our|my|vynn's|a|this)\s+(?:dcf\s+|valuation\s+|cash[-\s]flow\s+)?model(?:'s)?)\b"
    rf"[^!?\n]{{0,40}}?\b(?:puts|values|implies|suggests|gives|yields|points\s+to|estimates|output)\b"
    rf"[^!?\n]{{0,30}}?(?:{_PER_SHARE})",
    re.I,
)
# A scenario's value per share: "Bull case: $240", "| Bull | $240 |". Not the
# commodity price a scenario is built on ("Bear case: if Brent falls to $55"),
# nor "the base Model Y at $39,990" or "the 2023-24 bull run from $120".
_SCENARIO_LABEL = re.compile(
    r"\b(?:bull|bear|base)(?:[-\s]+(?:case|scenario))?(?:\s*[:：|]|\s+[-–—]\s)"
    r"|\b(?:bull|bear|base)[-\s]+(?:case|scenario)\b",
    re.I,
)
_FIGURE = re.compile(_PER_SHARE, re.I)
_COMMODITY = re.compile(r"\b(?:brent|wti|crude|oil|gas|henry\s+hub|lng|gold|copper|barrel)\b", re.I)
_SHARE_WORD = re.compile(r"\b(?:stock|shares?|share\s+price|valued?|worth|target|it)\b", re.I)
_UNIT_AFTER = re.compile(
    r"^\s*(?:/\s*|a\s+|an\s+|per\s+)(?:bbl|barrel|boe|mmbtu|mcf|ton|tonne|oz|ounce|mwh|kwh|gallon)", re.I
)
# Explicit rating and valuation terms in the other languages answers come back
# in; not 信用评级 (a credit rating) or 公允价值变动 (fair-value accounting).
_OTHER_LANGUAGE_CLAIM = re.compile(
    r"目标价|目標價|目标股价|目標株価|公允价值(?!变动|计量|变化)|合理价值|合理估值|内在价值|(?<!信用)评级|評級|"
    r"上涨空间|上行空间|下跌空间|下行空间|低估|高估|割安|割高|適正価格|"
    r"\b(?:precio\s+objetivo|objetivo\s+de\s+precio|pre[cç]o[-\s]alvo|prix\s+cible|kursziel|"
    r"valor\s+(?:justo|razonable|intr[ií]nseco)|juste\s+valeur|fairer\s+wert|"
    r"infravalorad\w*|sobrevalorad\w*|subvalorizad\w*|sous-[ée]valu\w*|sur[ée]valu\w*|"
    r"unterbewertet|[uü]berbewertet|recomendaci[oó]n\s+de\s+(?:compra|venta)|sobreponderar|"
    r"infraponderar)\b",
    re.I,
)
# What only repeats the fixed statement, which states it authoritatively:
# the rating status, and the Street's ratings, targets and rating actions.
_RESTATEMENT = re.compile(
    r"\bnot\s+rated\b|\bno\s+(?:rating|fair\s+value)\b|\bwithh(?:e|o)ld\w*\b|"
    r"\bdoes\s+not\s+publish\b|\bnot\s+published\b|\baudited\s+report\s+headline\b|"
    r"\bpoint\s+headline\b|\bpoint\s+estimate\b|"
    r"\b(?:analysts?'?|street'?s?|consensus|wall\s+street|sell[-\s]side|brokers?)\b[^.\n]{0,60}?"
    r"\b(?:targets?|rat(?:e|es|ed|ing|ings)|recommend\w*)\b|未评级|不予评级|分析师[^。\n]{0,20}(?:目标价|评级)|"
    r"\b(?:raised|lifted|cut|lowered|trimmed|boosted|reiterated|maintained|initiated|set|increased|"
    r"reduced|hiked)\s+(?:its|their|his|her|the)\s+(?:\d{1,2}-month\s+)?(?:price\s+target|target\s+price|"
    r"target\s+(?:on|for)\s+(?:the\s+)?(?:stock|shares))\b"
    r"|\b(?:raised|lifted|cut|lowered|trimmed|boosted|increased|reduced)\s+(?:its|their)\s+target\s+to\s+"
    rf"[$€£¥₹]\s?\d[\d,]*(?:\.\d+)?(?![\d,.]*\s*{_AGGREGATE})"
    r"|\b(?:upgraded|downgraded|initiated|reiterated|resumed)\b[^.\n]{0,40}?\b(?:strong\s+buy|buy|sell|"
    r"hold|neutral|outperform|underperform|overweight|underweight|equal[-\s]weight|market\s+perform|"
    r"sector\s+perform)\b"
    r"|\bnamed\s+(?:it|the\s+(?:stock|shares)|\w+)\s+(?:a|an|its|their)\s+(?:\w+\s+)?top\s+pick\b",
    re.I,
)

_SENTENCE_END = re.compile(
    r"(?<=[.!?])\s+|(?<=[.!?][*_)\"'”’])\s+|(?<=[.!?]\*\*)\s+|(?<=[。！？])"
)
_ABBREVIATION = re.compile(
    r"\b(?:approx|est|vs|e\.g|i\.e|inc|co|corp|ltd|plc|u\.s|u\.k|no|st|jr|sr|mr|ms|dr|jan|feb|mar|"
    r"apr|jun|jul|aug|sep|sept|oct|nov|dec)\.$",
    re.I,
)
_LINE_PREFIX = re.compile(r"^(\s*(?:[-*+•]\s+|\d+[.)]\s+|#{1,6}\s+|>\s*)?)(.*)$")
_HEADING = re.compile(r"^\s*(#{1,6})\s")
_LETTER = re.compile(r"[^\W\d_]", re.U)

# The benchmark block every guard template ends with.
_BENCHMARK_BLOCK = re.compile(
    r"\n\n(?=(?:The Street's view|Human-analyst and market benchmark reconciliation|"
    r"Market benchmark reconciliation|External benchmark reconciliation)\b)"
)

# Less than this, and what is left is a fragment rather than analysis.
_MIN_SECTION_LETTERS = 40


def _commodity_price(plain: str, start: int, end: int) -> bool:
    """A figure that prices a commodity: per unit, or governed by a commodity word."""
    if _UNIT_AFTER.match(plain[end:end + 14]):
        return True
    before = plain[max(0, start - 45):start]
    last = None
    for last in _COMMODITY.finditer(before):
        pass
    return bool(last) and not _SHARE_WORD.search(before[last.end():])


def _scenario_value(plain: str) -> bool:
    """A scenario label followed by a value per share that is not a commodity price."""
    for label in _SCENARIO_LABEL.finditer(plain):
        # 40 characters of reach, extended past each commodity price skipped --
        # at most three, so the work per label stays bounded.
        limit, skipped = label.end() + 40, 0
        for figure in _FIGURE.finditer(plain, label.end(), min(len(plain), label.end() + 260)):
            if figure.start() > limit:
                break
            if skipped < 3 and _commodity_price(plain, figure.start(), figure.end()):
                limit, skipped = max(limit, figure.end() + 40), skipped + 1
                continue
            return True
    return False


def makes_claim(text: str, forbidden_tokens: Sequence[str] = ()) -> bool:
    """True when the text explicitly states what only a published rating may."""
    plain = _normalize(text)
    if (_RATING_CLAIM.search(plain) or _VALUE_CLAIM.search(plain) or _PRICED_CLAIM.search(plain)
            or _OTHER_LANGUAGE_CLAIM.search(plain) or _scenario_value(plain)):
        return True
    # A withheld or contradicted figure as a whole number: "318.7" is in
    # "$318.70", the 200-day average, and must not match there.
    return any(
        token and re.search(rf"(?<![\d.,]){re.escape(_normalize(token))}(?![\d]|[.,]\d)", plain)
        for token in forbidden_tokens
    )


def restates(text: str, extra_patterns: Sequence[Pattern[str]] = ()) -> bool:
    """True when the text only repeats the fixed statement, or claims unsupported sentiment."""
    plain = _normalize(text)
    return bool(_RESTATEMENT.search(plain)) or any(p.search(plain) for p in extra_patterns)


def _letters(text: str) -> int:
    return len(_LETTER.findall(text))


def _sentences(body: str) -> List[str]:
    """Split a line into sentences, rejoining abbreviations and bare fragments."""
    out: List[str] = []
    for part in _SENTENCE_END.split(body):
        part = part.strip()
        if not part:
            continue
        # "approx." ends nothing; "$200." alone continues what came before. Only
        # the tail is examined, so a long run of joins stays linear.
        if out and (_ABBREVIATION.search(_normalize(out[-1][-12:])) or _letters(part) < 4):
            out[-1] = f"{out[-1]} {part}"
        else:
            out.append(part)
    return out


def _is_structural(line: str) -> bool:
    """A heading or a bare label that introduces what follows it."""
    if _HEADING.match(line):
        return True
    prefix, body = _LINE_PREFIX.match(line).groups()
    if prefix and prefix.strip() and not prefix.strip().startswith(">"):
        return False  # a list item is content
    bare = body.strip()
    plain = re.sub(r"[*_]", "", bare).strip()
    wrapped = bare.startswith("**") and bare.endswith("**") and bare.count("**") == 2
    return bool(plain) and len(plain.split()) <= 6 and (wrapped or plain.endswith(":"))


def _heading_level(line: str) -> int:
    match = _HEADING.match(line)
    return len(match.group(1)) if match else 7  # a bold label sits below every heading


def _balance(text: str) -> str:
    """Drop emphasis markers a removed sentence left unpaired."""
    if text.count("**") % 2:
        text = text.replace("**", "")
    if text.replace("**", "").count("*") % 2:
        text = re.sub(r"(?<!\*)\*(?!\*)", "", text)
    return text


@dataclass
class SectionReview:
    """What the deterministic check made of an analysis section."""

    text: str = ""
    # Sentences that only repeated the fixed statement; removed, harmless.
    repeated: List[str] = field(default_factory=list)
    # Explicit claims; any one of them means the section is not published.
    claims: List[str] = field(default_factory=list)

    @property
    def publishable(self) -> bool:
        return bool(self.text) and not self.claims


def review_section(
    section: str,
    *,
    forbidden_tokens: Iterable[str] = (),
    extra_patterns: Sequence[Pattern[str]] = (),
) -> SectionReview:
    """Strip what repeats the fixed statement, then list every explicit claim left."""
    tokens = tuple(token for token in forbidden_tokens if token)
    review = SectionReview()
    lines = str(section or "").replace("\r\n", "\n").split("\n")

    # Repeats go first: whatever they contain is never published, so a claim
    # inside one ("analysts rate it a Buy") cannot sink an otherwise good section.
    kept: List[str] = []
    for raw in lines:
        if not raw.strip():
            kept.append("")
            continue
        if raw.lstrip().startswith("|"):
            if restates(raw, extra_patterns):
                review.repeated.append(raw.strip())
            else:
                kept.append(raw)
            continue
        prefix, body = _LINE_PREFIX.match(raw).groups()
        prefix = prefix or ""
        parts = _sentences(body)
        good = [part for part in parts if not restates(part, extra_patterns)]
        review.repeated.extend(part for part in parts if restates(part, extra_patterns))
        text = _balance(" ".join(good))
        if not text:
            continue
        # Only a line that lost a sentence can be reduced to a fragment.
        if len(good) < len(parts) and _letters(text) < 12 and not _is_structural(f"{prefix}{text}"):
            continue
        kept.append(f"{prefix}{text}")

    # A heading or label whose content was all removed heads nothing.
    tidy: List[str] = []
    for position, line in enumerate(kept):
        if line.strip() and _is_structural(line):
            following = next((l for l in kept[position + 1:] if l.strip()), None)
            if following is None or (
                _is_structural(following) and _heading_level(following) <= _heading_level(line)
            ):
                continue
        tidy.append(line)
    text = re.sub(r"\n{3,}", "\n\n", "\n".join(tidy)).strip("\n")

    # Claims in what would be published: each sentence, each label read with
    # the line it introduces ("Bull case:" / "$240"), and a table as one text.
    published = [line for line in text.split("\n") if line.strip()]
    for index, line in enumerate(published):
        if line.lstrip().startswith("|"):
            units = [line]
        else:
            units = _sentences(_LINE_PREFIX.match(line).group(2))
        review.claims.extend(unit.strip() for unit in units if makes_claim(unit, tokens))
        if _is_structural(line) and index + 1 < len(published):
            pair = f"{line} {published[index + 1]}"
            if makes_claim(pair, tokens):
                review.claims.append(pair.strip())
    table = " ".join(line for line in published if line.lstrip().startswith("|"))
    if table and makes_claim(table, tokens) and not review.claims:
        review.claims.append(table[:200])

    review.text = text if _letters(text) >= _MIN_SECTION_LETTERS else ""
    return review


def compose(template: str, section: str) -> str:
    """The template's direct answer, then the analysis, then its benchmark block."""
    template = str(template or "").strip()
    section = str(section or "").strip("\n")
    if not section.strip():
        return template
    parts = _BENCHMARK_BLOCK.split(template, maxsplit=1)
    if len(parts) == 2:
        return f"{parts[0].rstrip()}\n\n{section}\n\n{parts[1].lstrip()}"
    return f"{template}\n\n{section}"
