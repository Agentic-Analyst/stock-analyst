"""
Which sentences of a recommendation narrative only restate VYNN's own numbers.

The recommendation contract forbids citing news for the rating, the fair
value, its method range or the confidence alert: no news item states VYNN's
numbers. So a sentence that restates them carries no [E#], and citation
coverage must not count it as an uncited news claim. That exemption is only
safe when the sentence says nothing else. An independent review of the first
version (one anchor word plus numbers that rounded to any fixed figure) shipped
"Our STRONG SELL rating reflects Apple losing its Epic Games appeal", "VYNN's
valuation does not include the $12 billion EU fine" and "VYNN's fair value
implies 33% upside" (the model said 33% downside) as model statements.

A sentence is a model statement only when both hold:

- Every figure binds to a FIXED_NUMBERS figure by unit, role and sign: money
  beside "fair value" is the fair value or its range, beside "price" the price
  at the run, beside "analysts" their mean target; a percentage matches a gap
  or return at its written precision (no rounding a numeric 3.62 to "4"; the
  alert's own "4% below" is a written figure) and in its direction ("upside"
  never matches a negative gap); a bare integer is an analyst count only before
  "analysts", the 12 only in "12-month". "$12 billion", "53 million" and "39
  countries" bind to nothing.
- Its words are accounted for: removing the words of FIXED_NUMBERS' own
  sentences (the target assumption, the alert), a fixed vocabulary of
  valuation terms, glue words and the company's own name leaves nothing.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterator, List, Optional, Set, Tuple

RATING_LABELS = ("STRONG BUY", "STRONG SELL", "BUY", "SELL", "HOLD")

# Valuation and analytic vocabulary a model statement may use. No verbs that
# bridge to events ("reflects", "includes", "ignores", "absorbs", "captures"):
# with them a sentence about the model can carry news.
_MODEL_WORDS = {
    "vynn", "model", "valuation", "value", "intrinsic", "fair", "dcf", "discount",
    "wacc", "terminal", "perpetuity", "perpetual", "exit", "multiple", "leg", "method",
    "single", "triangulated", "triangulation", "independent", "independently",
    "convergence", "converge", "case", "base", "bull", "bear", "scenario", "range",
    "published", "fixed", "deterministic", "calculator", "output", "result", "derived",
    "assumption", "assume", "explicit", "statistical", "statistically", "forecast",
    "market", "price", "current", "target", "implied", "implies", "imply", "expected",
    "return", "gap", "downside", "upside", "below", "above", "rating", "rated", "rate",
    "assigned", "confidence", "low", "moderate", "high", "alert", "analyst", "mean",
    "street", "consensus", "benchmark", "view", "recommendation", "directional",
    "direction", "magnitude", "estimate", "blend", "blended", "caution", "cautious",
    "cautiously", "disagreement", "divergence", "reason", "treat", "weigh", "own",
    "month", "share", "per", "percent", "point", "less", "half", "move", "smaller",
    "larger", "opposite", "corroborate", "back", "support", "material", "evidence",
    "available", "external", "strong", "buy", "sell", "hold", "stronger", "versus",
    "compared", "relative", "implying", "result", "outcome", "conclusion",
    "negative", "positive", "modest", "modestly", "slight", "slightly", "stated",
    "retain", "retains", "based", "probability", "probabilistic", "weighted", "horizon",
    # Neutral discourse words the captured drafts used about the model.
    "substantial", "significant", "confirm", "separate", "determine", "differ",
    "remain", "follow", "use", "input", "citation", "call", "news", "factor", "whereas",
    "indicated", "decline", "close", "path", "basis",
}
_GLUE = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "of", "to",
    "from", "in", "on", "at", "by", "for", "with", "and", "or", "but", "not", "no",
    "this", "that", "these", "those", "it", "its", "as", "so", "than", "rather",
    "while", "which", "who", "whose", "there", "here", "both", "each", "only",
    "also", "still", "yet", "if", "then", "under", "over", "vs", "against", "about",
    "around", "roughly", "approximately", "nearly", "we", "our", "us", "should",
    "would", "could", "may", "might", "can", "will", "does", "do", "has", "have",
    "had", "given", "supplied", "say", "says", "said", "show", "shows", "indicate",
    "indicates", "mean", "means", "make", "makes", "taken", "together", "into",
    "across", "between", "within", "one", "any", "all", "more", "most", "such",
    "same", "other", "what", "when", "where", "how", "because", "since", "though",
    "although", "however", "therefore", "thus", "i", "e", "g", "per",
}
# Words that make a sentence about the model at all.
_ANCHORS = {"vynn", "model", "valuation", "intrinsic", "dcf", "rating", "convergence",
            "alert", "wacc", "fair"}

_ROLE_WORDS = (
    ("street", re.compile(r"\banalysts?(?:'s|’s|')?\b|\bstreet(?:'s|’s)?\b|\bconsensus\b|\bmean target\b", re.I)),
    ("value", re.compile(r"\bfair value\b|\bintrinsic[- ]value\b|\bvaluation\b|\bvalue\b|\btarget\b|"
                         r"\bconvergence\b|\bdcf\b|\brange\b|\bcase\b|\bestimate\b", re.I)),
    ("price", re.compile(r"\bprice\b|\bmarket\b|\btrad(?:es|ing)\b|\bquote\b", re.I)),
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9.])(\d[\d,]*(?:\.\d+)?)")
_CURRENCY_BEFORE = re.compile(r"(?:US\$|HK\$|S\$|A\$|C\$|NT\$|R\$|MX\$|[$€£¥₹₩]|\b(?:USD|EUR|GBP|JPY|CHF|INR))\s?[-+−]?$")
_SIGN_BEFORE = re.compile(r"[-−]\s?$")
_PLUS_BEFORE = re.compile(r"\+\s?$")
_PERCENT_AFTER = re.compile(r"^\s?(?:%|percent\b|per cent\b)")
_MAGNITUDE_AFTER = re.compile(r"^\s?(?:%\s*)?(?:million|billion|trillion|thousand|bn|mn|[mbk])\b", re.I)
_MONTHS_AFTER = re.compile(r"^[- ]?months?\b", re.I)
_COUNT_AFTER = re.compile(r"^[- ]?(?:analysts?|ratings?)\b", re.I)
# Direction words. Not "under"/"over"/"more"/"less": "a 14.86% return under
# the 12-month assumption" says nothing about the sign.
_NEGATIVE = {"below", "downside", "lower", "decline", "declines", "drop", "drops", "fall",
             "falls", "negative"}
_POSITIVE = {"above", "upside", "higher", "gain", "gains", "rise", "rises", "premium",
             "positive"}
_TEXT_PERCENT = re.compile(r"(?<![A-Za-z0-9.])([-+−]?)(\d+(?:\.\d+)?)%(?:\s+(below|above))?")


@dataclass
class ModelFacts:
    """What FIXED_NUMBERS lets a sentence restate."""
    money: Dict[str, List[float]] = field(default_factory=dict)
    # (magnitude, sign or 0 when unsigned, written=True when FIXED_NUMBERS
    # itself prints it at that precision)
    percents: List[Tuple[float, int, bool]] = field(default_factory=list)
    counts: Set[int] = field(default_factory=set)
    horizons: Set[int] = field(default_factory=set)
    vocabulary: Set[str] = field(default_factory=set)
    rating: str = ""
    ticker: str = ""


def _number(value: Any) -> Optional[float]:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    value = float(value)
    return value if value == value and abs(value) != float("inf") else None


def _get(node: Any, *path: str) -> Any:
    for key in path:
        node = node.get(key) if isinstance(node, dict) else None
    return node


def _strings(node: Any) -> Iterator[str]:
    if isinstance(node, str):
        yield node
    elif isinstance(node, dict):
        for value in node.values():
            yield from _strings(value)
    elif isinstance(node, (list, tuple)):
        for value in node:
            yield from _strings(value)


def _stem(word: str) -> str:
    word = word.lower().replace("’", "'")
    if word.endswith("'s"):
        word = word[:-2]
    word = word.strip("'")
    for suffix in ("ingly", "edly", "ing", "ies", "ed", "es", "ly", "s"):
        if word.endswith(suffix) and len(word) - len(suffix) >= 3:
            word = word[: -len(suffix)] + ("y" if suffix == "ies" else "")
            break
    # "corroborate" and "corroborated", "base" and "based" meet here.
    return word[:-1] if word.endswith("e") and len(word) > 3 else word


def words(text: str) -> List[str]:
    """Stemmed words, hyphenated compounds split, numbers dropped."""
    return [_stem(w) for w in re.findall(r"[A-Za-z][A-Za-z']*", text or "")]


def model_facts(fixed_numbers: Optional[Dict[str, Any]]) -> ModelFacts:
    fixed = fixed_numbers if isinstance(fixed_numbers, dict) else {}
    inputs = fixed.get("inputs") if isinstance(fixed.get("inputs"), dict) else {}
    reliability = inputs.get("valuation_reliability") if isinstance(
        inputs.get("valuation_reliability"), dict) else {}
    alert = fixed.get("confidence_alert") if isinstance(fixed.get("confidence_alert"), dict) else {}
    facts = ModelFacts(rating=str(fixed.get("rating") or "").strip(),
                       ticker=_stem(str(fixed.get("ticker") or "").split(".")[0]))

    value = []
    for period in ("m3", "m6", "m12"):
        for key in ("price", "range_low", "range_high"):
            value.append(_number(_get(fixed, "targets", period, key)))
    value += [_number(inputs.get("valuation_value")), _number(reliability.get("range_low")),
              _number(reliability.get("range_high"))]
    value += [_number(v) for v in (reliability.get("legs") or {}).values()] \
        if isinstance(reliability.get("legs"), dict) else []
    facts.money = {
        "value": [v for v in value if v is not None],
        "price": [v for v in (_number(fixed.get("current_price")),) if v is not None],
        "street": [v for v in (_number(inputs.get("analyst_target")),) if v is not None],
    }

    # Gaps and returns already in percent, then the two the alert keeps as
    # fractions. Only these are scaled: -1.03 (percent) is not -103%.
    for key in ("expected_return_pct_12m",):
        v = _number(fixed.get(key))
        if v is not None:
            facts.percents.append((abs(v), (v > 0) - (v < 0), False))
    for key in ("raw_val_gap_pct", "adj_val_gap_pct", "analyst_target_gap_pct"):
        v = _number(inputs.get(key))
        if v is not None:
            facts.percents.append((abs(v), (v > 0) - (v < 0), False))
    for key in ("model_gap", "benchmark_gap"):
        v = _number(alert.get(key))
        if v is not None and abs(v) <= 10:
            facts.percents.append((abs(v * 100), (v > 0) - (v < 0), False))

    texts = [fixed.get("target_assumption"), fixed.get("confidence_alert_text"),
             fixed.get("rating_withheld_reason"), reliability.get("warning"),
             reliability.get("withheld_reason")] + list(_strings(alert))
    for text in texts:
        if not isinstance(text, str):
            continue
        for sign, number, direction in _TEXT_PERCENT.findall(text):
            signed = -1 if sign in "-−" and sign else 1 if sign == "+" else 0
            if not signed and direction:
                signed = -1 if direction == "below" else 1
            facts.percents.append((float(number), signed, True))
        facts.vocabulary.update(words(text))

    for v in (inputs.get("analyst_count"), inputs.get("analyst_rating_count"),
              alert.get("analyst_count"), alert.get("analyst_rating_count")):
        if isinstance(v, int) and not isinstance(v, bool):
            facts.counts.add(v)
    if _get(fixed, "targets", "m12", "price") is not None or "12-month" in str(
            fixed.get("target_assumption") or ""):
        facts.horizons.add(12)
    facts.vocabulary |= {_stem(w) for w in _MODEL_WORDS}
    return facts


def _direction(sentence: str, start: int, end: int) -> int:
    after = re.findall(r"[A-Za-z]+", sentence[end:end + 40])[:3]
    before = re.findall(r"[A-Za-z]+", sentence[max(0, start - 30):start])[-2:]
    for word in after + list(reversed(before)):
        w = word.lower()
        if w in _NEGATIVE:
            return -1
        if w in _POSITIVE:
            return 1
    return 0


def _role(sentence: str, start: int, end: int) -> Optional[str]:
    """The nearest role word before the figure (same clause), else just after."""
    window = sentence[max(0, start - 60):start]
    window = re.split(r"[;:]|\d", window)[-1]
    best, best_at = None, -1
    for role, pattern in _ROLE_WORDS:
        for match in pattern.finditer(window):
            if match.end() > best_at:
                best, best_at = role, match.end()
    if best:
        return best
    ahead = re.split(r"[;:,]|\d", sentence[end:end + 25])[0]
    for role, pattern in _ROLE_WORDS:
        if pattern.search(ahead):
            return role
    return None


def _decimals(text: str) -> int:
    return len(text.split(".", 1)[1]) if "." in text else 0


def bind_numbers(sentence: str, facts: ModelFacts) -> Tuple[List[str], List[str]]:
    """The sentence's figures that are FIXED_NUMBERS figures, and those that are not."""
    bound, unbound = [], []
    for match in _NUMBER.finditer(sentence or ""):
        raw = match.group(1)
        text = raw.replace(",", "")
        value = float(text)
        decimals = _decimals(text)
        before, after = sentence[:match.start()], sentence[match.end():]
        ok = False
        if _MAGNITUDE_AFTER.match(after):
            ok = False
        elif _PERCENT_AFTER.match(after):
            sign = -1 if _SIGN_BEFORE.search(before) else 1 if _PLUS_BEFORE.search(before) else 0
            sign = sign or _direction(sentence, match.start(), match.end())
            for magnitude, fig_sign, written in facts.percents:
                if sign and fig_sign and sign != fig_sign:
                    continue
                if decimals == 0 and not written and magnitude != round(magnitude):
                    continue  # no rounding a numeric 3.62 to "4"
                if round(magnitude, decimals) == value:
                    ok = True
                    break
        elif _CURRENCY_BEFORE.search(before) or "." in text:
            role = _role(sentence, match.start(), match.end())
            pools = [facts.money.get(role, [])] if role else list(facts.money.values())
            ok = any(abs(figure - value) < 0.005 if decimals >= 2 else figure == value
                     for pool in pools for figure in pool)
        elif _MONTHS_AFTER.match(after):
            ok = int(value) in facts.horizons and value == int(value)
        elif _COUNT_AFTER.match(after):
            ok = value == int(value) and int(value) in facts.counts
        (bound if ok else unbound).append(raw)
    return bound, unbound


_CORPORATE = {"inc", "incorporated", "corp", "corporation", "company", "co", "holding",
              "holdings", "group", "plc", "ltd", "limited", "the", "sa", "se", "ag", "nv",
              "llc", "lp", "and"}


def subject_names(name: Any, ticker: Any, *, stem: bool = True) -> Set[str]:
    """The company's own name and ticker as words: "JPMorgan Chase & Co." -> jpmorgan, chase.

    Stemmed as `words` stems, or lower-cased only for another tokenizer.
    """
    text = " ".join(str(v) for v in (name, str(ticker or "").split(".")[0]) if v and v != "N/A")
    raw = [w.lower().replace("’", "'") for w in re.findall(r"[A-Za-z][A-Za-z']*", text)]
    raw = [w[:-2] if w.endswith("'s") else w for w in raw if w not in _CORPORATE]
    return {_stem(w) for w in raw} if stem else set(raw)


def residual_words(sentence: str, facts: ModelFacts, subject: Set[str] = frozenset()) -> Set[str]:
    """Words left once the model's vocabulary, glue and the company's name are accounted for."""
    glue = {_stem(w) for w in _GLUE}
    labels = {_stem(w) for label in RATING_LABELS for w in label.split()}
    return {w for w in words(sentence)
            if w not in glue and w not in facts.vocabulary and w not in labels
            and w not in subject and w != facts.ticker and len(w) > 1}


def model_statement_gap(sentence: str, facts: ModelFacts,
                        subject: Set[str] = frozenset()) -> Optional[Dict[str, List[str]]]:
    """What keeps a sentence about the model from being a model statement.

    None when it does not name the model at all (it is news) or when it is
    one. Otherwise the figures that are not VYNN's and the words beyond the
    model's, so the rewrite is told what to drop rather than to cite.
    """
    text = sentence or ""
    if not (set(words(text)) & {_stem(w) for w in _ANCHORS}) or is_model_statement(
            text, facts, subject):
        return None
    _, unbound = bind_numbers(text, facts)
    extra = residual_words(text, facts, subject)
    # The words as written, not their stems.
    surface: List[str] = []
    for word in re.findall(r"[A-Za-z][A-Za-z']*", text):
        if _stem(word) in extra and word.lower() not in surface:
            surface.append(word.lower())
    return {"unbound": unbound, "extra_words": surface}


def is_model_statement(sentence: str, facts: ModelFacts, subject: Set[str] = frozenset()) -> bool:
    """True when the sentence restates FIXED_NUMBERS and says nothing else.

    `subject` is the company's name (subject_names). Without it one word is
    allowed for the name; with it, none.
    """
    text = sentence or ""
    if re.search(r"\[E\d+\]", text):
        return False
    stems = set(words(text))
    names_rating = bool(facts.rating) and re.search(
        rf"\b{re.escape(facts.rating)}\b", text) is not None
    if not (stems & {_stem(w) for w in _ANCHORS}) and not names_rating:
        return False
    if names_rating is False and any(
            re.search(rf"\b{label}\b", text) for label in RATING_LABELS):
        # Names a rating that is not the fixed one.
        return False
    _, unbound = bind_numbers(text, facts)
    if unbound:
        return False
    return len(residual_words(text, facts, subject)) <= (0 if subject else 1)
