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


def valid_citations(answer: Answer, passages: list[Passage]) -> tuple[list[Citation], int]:
    """Keep only citations that match a passage retrieved for THIS request.

    Returns (kept, dropped). A citation the retriever never returned is fabricated."""
    retrieved = {(p.source, p.section): p for p in passages}
    kept: list[Citation] = []
    for c in answer.citations:
        hit = retrieved.get((c.source, c.section))
        if hit is None:
            continue
        citation = Citation(source=hit.source, section=hit.section, page=hit.page)
        if citation not in kept:
            kept.append(citation)
    return kept, len(answer.citations) - len(kept)
