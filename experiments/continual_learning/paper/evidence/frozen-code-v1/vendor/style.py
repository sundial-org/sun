"""Private evaluation only. This module never provides feedback to a writer."""
from difflib import SequenceMatcher
from functools import lru_cache
import re

TAG_VERBS = {"say", "ask", "reply", "whisper", "shout", "mutter", "murmur", "call", "add", "answer", "cry"}
RULES = {
    "A": ["No standalone word suddenly (case insensitive).",
          "No standalone word very (case insensitive).", "No semicolon characters.",
          "No em dash characters (U+2014).",
          "At least 90% of finite verbs outside double-quoted dialogue are present tense; avoid past tense and modal finite verbs in narration.",
          "The first sentence has at most 12 whitespace-separated words.",
          "Dialogue tags use only the verb say (says and said match the lemma). The separate present-tense rule also applies to tags outside quotes, so normally use says. A dialogue tag is a verb from say, ask, reply, whisper, shout, mutter, murmur, call, add, answer, cry within six tokens outside a double quotation mark. No tags is acceptable.",
          "No capitalized word other than I, except at the start of a sentence or DOUBLE quotation. This includes personal names, weekdays such as Thursday, and months. Single quotes are not quotation marks for this rule; convert single-quoted dialogue to standard double quotes as needed."],
    "B": ["No standalone word suddenly (case insensitive).",
          "No standalone word very (case insensitive).", "No semicolon characters.",
          "No ellipses, either three periods or U+2026.", "No exclamation mark characters.",
          "The first sentence has at least 25 whitespace-separated words.",
          "Dialogue tags never use say, says, or said. A dialogue tag is a verb from say, ask, reply, whisper, shout, mutter, murmur, call, add, answer, cry within six tokens outside a double quotation mark. No tags is acceptable.",
          "Include a full two-word name (two consecutive capitalized words) in the first sentence."]
}


@lru_cache(maxsize=1)
def nlp():
    import spacy
    import torch
    torch.set_num_threads(2)
    return spacy.load("en_core_web_trf", disable=["ner"])


@lru_cache(maxsize=32)
def analyzed(text):
    return nlp()(text)


def segments(text):
    return [sentence for sentence in analyzed(text).sents if sentence.text.strip()]


def score(text, guide="A"):
    doc = analyzed(text)
    sentences = [sentence for sentence in doc.sents if sentence.text.strip()]
    first = sentences[0].text.strip() if sentences else ""
    quoted = [(m.start(), m.end()) for m in re.finditer(r'"[^"\n]*"|“[^”\n]*”', text)]
    inside = lambda token: any(a <= token.idx < b for a, b in quoted)
    finite = [t for t in doc if not inside(t) and t.tag_ in {"VBD", "VBP", "VBZ", "MD"}]
    present = sum(t.tag_ in {"VBP", "VBZ"} for t in finite) / len(finite) if finite else 1.0
    quote_indices = [t.i for t in doc if t.text in {'"', '“', '”'}]
    tags = [t for t in doc if not inside(t) and t.pos_ in {"VERB", "AUX"}
            and t.lemma_.lower() in TAG_VERBS and any(0 < abs(t.i - q) <= 6 for q in quote_indices)]
    names = []
    for sentence in sentences:
        words = [t for t in sentence if re.search(r"[A-Za-z]", t.text)]
        for i, token in enumerate(words):
            quote_start = any(a <= token.idx < b and not re.search(r"[A-Za-z]", text[a:token.idx]) for a, b in quoted)
            if i and not quote_start and token.text != "I" and re.match(r"[A-Z][a-z]+", token.text):
                names.append(token.text)
    common = [not re.search(r"\bsuddenly\b", text, re.I),
              not re.search(r"\bvery\b", text, re.I), ";" not in text]
    if guide == "A":
        values = common + ["\u2014" not in text, present >= .9, len(first.split()) <= 12,
                           all(t.lemma_.lower() == "say" for t in tags) if tags else None, not names]
    else:
        values = common + [not re.search(r"\.{3}|\u2026", text), "!" not in text,
                           len(first.split()) >= 25,
                           all(t.lemma_.lower() != "say" for t in tags) if tags else None,
                           bool(re.search(r"\b[A-Z][a-z]+\s+[A-Z][a-z]+\b", first))]
    applicable = [v for v in values if v is not None]
    return {"S": sum(applicable) / len(applicable), "rules": values,
            "present_share": present, "first_words": len(first.split()),
            "tag_verbs": [t.lemma_ for t in tags], "names": names,
            "words": len(text.split()),
            "dialogue_share": sum(len(text[a:b].split()) for a, b in quoted) / max(1, len(text.split()))}


def edit_metrics(draft, edited):
    a, b = draft.split(), edited.split()
    matched = sum(x.size for x in SequenceMatcher(None, a, b, autojunk=False).get_matching_blocks())
    # Token Levenshtein distance counts insertion-only edits too.
    row = list(range(len(b) + 1))
    for i, left in enumerate(a, 1):
        new = [i]
        for j, right in enumerate(b, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j - 1] + (left != right)))
        row = new
    return {"kept": matched / max(1, len(a)), "words_changed": len(a) - matched,
            "token_edit_distance": row[-1], "edit_similarity": 1 - row[-1] / max(1, len(a), len(b)),
            "length_change": len(b) - len(a)}
