"""Identity-point similarity engine for scripts/validate.py's mission-identity gate (#288).

Private implementation module, pushed down the way the count-lint engine was (RV-D1): validate.py
keeps the gate policy (IDENTITY_POINT_SAME / _NEAR / _MAX_TOKENS and identity_collisions) and
re-exports the three functions it and its tests call. The tokenizer is eval.py's, handed in by
validate.py as ``EVAL`` so the gate and the router agree on what a word is.

A point is "the same" when its two declarations carry the same content words; six same points
means one mission wearing two names, which is exactly what ARCHITECTURE.md forbids.

Negation words are deliberately NOT stopwords here: "issue closed" and "issue not closed" are
opposite points, and dropping "not" scored them 1.0. Polarity is read from the raw text
(NEGATORS) and a mismatch is a divergence outright. "no"/"nothing" are quantities, not polarity
("finds no open item" == "finds zero open items"), so they fold onto the zero concept.
"""
import re

# Set by validate.py to its loaded scripts/eval.py module. Left unset, tokenizing raises.
EVAL = None

STOPWORDS = {
    "a", "an", "and", "any", "are", "as", "at", "be", "by", "every", "for",
    "from", "in", "into", "is", "it", "its", "of", "on", "one",
    "or", "per", "that", "the", "their", "then", "this", "to", "with",
}
NEGATORS = {"not", "never", "without", "cannot", "nor", "neither"}
ZERO_WORDS = {"no", "nothing"}

# Concept canonicalisation for the identity gate (full-review probe T2b): the
# routing synonym table is eleven user-word entries, so a paraphrase that
# swaps every content word for an unlisted synonym (issue→ticket,
# reproduced→replicated, verified→confirmed, worktree→checkout,
# human→person, commit→revision) shared NO stems with the original and read
# as divergent on every point. Stemming cannot close that; only folding the
# mission-identity vocabulary onto shared concepts can. Keys are eval.py
# stems, values the canonical concept; "" drops a token whose synonym is a
# stopword ("single" for "one"). This is deliberately a closed, reviewable
# table — an open-ended thesaurus would make the gate's verdicts unexplainable.
CONCEPTS = {}
for _concept, _aliases in {
    "issu": ("ticket", "item", "entr", "finding"),
    "open": ("unresolv", "outstand", "remain"),
    "backlog": ("queu",),
    "fixed": ("frozen", "repair", "remediat"),
    "reproduc": ("replicat", "recreat"),
    "verif": ("confirm", "check", "validat"),
    "independentl": ("separatel", "separat", "independent", "alon", "isolat"),
    "clos": ("resolv", "complet", "finish", "done"),
    "recount": ("enumeration", "enumerat", "count"),
    "zero": ("none", "empt", "drain", "clear"),
    "worktre": ("checkout", "workspac"),
    "merg": ("landing", "land"),
    "serialis": ("sequentiall", "sequenc"),
    "park": ("held", "asid", "block"),
    "human": ("person", "maintainer"),
    "decis": ("decision", "decid"),
    "requir": ("must", "need"),
    "repositor": ("project", "repo", "codebas"),
    "test": ("automat", "suit"),
    "review": ("sign",),
    "commit": ("revision", "rev", "sha"),
    "find": ("show",),
    "": ("singl", "each"),
}.items():
    for _alias in _aliases:
        CONCEPTS[_alias] = _concept


def identity_tokens(value):
    """Identity-point tokens, STEMMED and synonym-expanded (#288).

    Raw surface tokens made this a duplicate-string detector wearing an identity test's name: one
    word defeated it. "…backlog drained to zero…" against "…backlog emptied to zero…" scored 0.667
    against a 0.85 bar, so a second mission could restate the first's identity and pass.

    eval.py already owns the repository's tokenizer — the same stemming and synonym table the
    router uses — so the two surfaces agree on what a word is instead of keeping separate
    definitions. Stemming alone closes the inflection paraphrase ("backlogs", "draining"); a true
    synonym swap is caught by validate.py's NEAR rule, not here.

    No fallback: a tokenizer failure raises. Falling back to unstemmed words used to loosen the
    gate silently — every inflection paraphrase would pass while the build stayed green.
    """
    if EVAL is None:
        raise RuntimeError("_identity.EVAL is unset: the identity gate has no tokenizer")
    _scoring, synonyms = EVAL.routing_config()
    tokens = set(EVAL.tokenize(value or "", synonyms))
    if words(value) & ZERO_WORDS:
        tokens.add("zero")  # eval's tokenizer drops "no" as a stopword; it is a quantity here
    folded = {CONCEPTS.get(t, t) for t in tokens if t not in STOPWORDS}
    return {t for t in folded if t}


def words(value):
    return set(re.findall(r"[a-z0-9']+", (value or "").lower()))


def negated(value):
    """Polarity of a point: does it carry a negator ("not", "never", "can't", …)?"""
    ws = words(value)
    return bool(ws & NEGATORS) or any(w.endswith("n't") for w in ws)


def point_similarity(a, b):
    """Containment of the two token sets; 0.0 when their polarity differs.

    Containment (|A∩B| / min(|A|,|B|)) is padding-resistant where Jaccard was not: filler added
    to one side grows the union but never the smaller set. A negation mismatch is a divergence
    whatever the overlap — "issue closed" and "issue not closed" share every content word.
    """
    if negated(a) != negated(b):
        return 0.0
    ta, tb = identity_tokens(a), identity_tokens(b)
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / min(len(ta), len(tb))


def identity_sims(ta, tb):
    """Per-point similarity across the six identity points."""
    return [point_similarity(x, y) for x, y in zip(ta, tb, strict=True)]
