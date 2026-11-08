"""Small, testable rules around generation (section 3.4)."""

from __future__ import annotations

import re

from ..schemas import Answer, Citation, Passage

ABSTAIN_TEXT = ("The documents I have do not cover this question, so I can't answer it "
                "reliably. Please check with the academic office.")
FALLBACK_TEXT = ("I couldn't produce a reliable, well-formed answer just now. "
                 "Please try again in a moment.")

_FOLLOW_UP = re.compile(
    r"^\s*(and|also|but|so|then|what about|how about|why( not)?|is (it|that|this)|"
    r"(it|that|this|those|these|they|them|he|she)\b)",
    re.IGNORECASE,
)


# The model saying, in its own answer, that the evidence does not cover the question.
_SELF_DECLINE = re.compile(
    r"(not (covered|mentioned|specified|addressed|provided|included|stated) (in|by)"
    r"|(does|do) not (cover|mention|provide|contain|specify|address|include)"
    r"|no (information|mention|details?|evidence|rules?) (about|on|regarding|for|is|are)"
    r"|(isn't|is not|aren't|are not) (covered|mentioned|addressed)"
    r"|cannot be (found|answered)|not (found|available) in the (evidence|documents?|context))",
    re.IGNORECASE,
)


def declines_in_text(text: str) -> bool:
    """Small models often 'answer' and then admit the evidence does not cover it.
    If the answer says so anywhere, it is an abstention, whatever the flag says."""
    return bool(_SELF_DECLINE.search(text))


def is_followup(question: str) -> bool:
    """Questions that depend on an earlier turn. Never cache them: the same words mean
    something different in another conversation."""
    return bool(_FOLLOW_UP.match(question)) or len(question.split()) <= 2


def abstention() -> Answer:
    return Answer(reasoning="no retrieved passage cleared the relevance floor",
                  answer=ABSTAIN_TEXT, citations=[], answered_from_context=False,
                  confidence="low")


def fallback() -> Answer:
    return Answer(reasoning="generation failed validation twice", answer=FALLBACK_TEXT,
                  citations=[], answered_from_context=False, confidence="low")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def _source_key(source: str) -> str:
    """'corpus/raw/Grading-Page.html' and 'grading page' name the same document."""
    name = source.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r"\.(pdf|html?|md|txt)$", "", name, flags=re.IGNORECASE)
    return _norm(name)


def _resolve(c: Citation, passages: list[Passage]) -> Passage | None:
    """The retrieved passage a citation refers to, or None if it names nothing retrieved.

    Small models copy names imperfectly, so match on the normalised document name, then:
    an exact (normalised) section, else a section that starts with the other (e.g. the
    clause number "5.4" vs "5.4 Academic Warning"), else the only passage retrieved from
    that document. A citation naming a document we did not retrieve never matches."""
    same_doc = [p for p in passages if _source_key(p.source) == _source_key(c.source)]
    if not same_doc:
        return None
    cited = _norm(c.section)
    for p in same_doc:
        if _norm(p.section) == cited:
            return p
    if cited:
        for p in same_doc:
            mine = _norm(p.section)
            if mine.startswith(cited) or cited.startswith(mine):
                return p
    return same_doc[0] if len(same_doc) == 1 else None


def valid_citations(answer: Answer, passages: list[Passage]) -> tuple[list[Citation], int]:
    """Keep only citations that resolve to a passage retrieved for THIS request.

    Each kept citation is rewritten with the retrieved passage's exact source, section
    and page, so what the user sees always names a real retrieved chunk. A citation the
    retriever never returned is fabricated and is dropped. Returns (kept, dropped)."""
    kept: list[Citation] = []
    for c in answer.citations:
        hit = _resolve(c, passages)
        if hit is None:
            continue
        citation = Citation(source=hit.source, section=hit.section, page=hit.page)
        if citation not in kept:
            kept.append(citation)
    return kept, len(answer.citations) - len(kept)
