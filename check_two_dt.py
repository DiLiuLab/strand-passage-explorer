# run:  sage -python check_two_dt.py
#
# Compares two signed DT codes: are they the same link topology, and do they
# have the same Jones polynomial (exactly, and up to mirror q->1/q + framing q^n,
# matching the strand-passage overview's merge rule)?
import re
from fractions import Fraction

import snappy

DT1 = [(14, 16), (4, 2, 12), (20, 18, 6), (10, 8)]
DT2 = [(18, -8), (2, 24, 14, 16), (20, 22), (6, 12, 10, -4)]


def dt_str(dt):
    return "DT: [" + ", ".join(
        "(" + ",".join(str(x) for x in c) + ")" for c in dt) + "]"


# ---- Jones canonicalisation (mirror q->1/q and overall q^n framing factor) ---
_TERM = re.compile(
    r"(?P<sign>[+-]?)\s*(?P<coeff>\d+)?\s*\*?\s*"
    r"(?P<var>[A-Za-z])?(?:\^\(?(?P<exp>-?\d+(?:/\d+)?)\)?)?")


def parse_laurent(text):
    s = str(text).replace(" ", "")
    if s in ("", "0"):
        return {}
    terms, consumed = {}, 0
    for m in _TERM.finditer(s):
        if m.start() != consumed:
            return None
        piece = m.group(0)
        if piece == "":
            continue
        consumed = m.end()
        if m.group("coeff") is None and m.group("var") is None:
            return None
        c = (-1 if m.group("sign") == "-" else 1) * (
            int(m.group("coeff")) if m.group("coeff") else 1)
        if m.group("var") is None:
            e = Fraction(0)
        elif m.group("exp") is None:
            e = Fraction(1)
        else:
            e = Fraction(m.group("exp"))
        terms[e] = terms.get(e, 0) + c
    if consumed != len(s):
        return None
    return {e: c for e, c in terms.items() if c != 0}


def canonical_key(jones_str):
    d = parse_laurent(jones_str)
    if not d:
        return ("raw", str(jones_str).strip())

    def shift(pairs):
        mn = min(e for e, _ in pairs)
        return tuple(sorted((e - mn, c) for e, c in pairs))

    orig = shift([(e, c) for e, c in d.items()])
    mirror = shift([(-e, c) for e, c in d.items()])
    return ("poly", min(orig, mirror))


def describe(name, dt):
    L = snappy.Link(dt_str(dt))
    print("--- %s : %s" % (name, dt_str(dt)))
    print("    diagram: %d crossings, %d components"
          % (len(L.crossings), len(L.link_components)))
    L.simplify("global")
    print("    simplified: %d crossings, %d components"
          % (len(L.crossings), len(L.link_components)))
    try:
        print("    linking matrix: %s" % (L.linking_matrix(),))
    except Exception as exc:
        print("    linking matrix: n/a (%s)" % exc)
    jones = None
    try:
        jones = L.jones_polynomial()
        print("    Jones: %s" % jones)
    except Exception as exc:
        print("    Jones: n/a (%s) -- are you running under sage?" % exc)
    try:
        print("    Alexander: %s" % L.alexander_polynomial())
    except Exception as exc:
        print("    Alexander: n/a (%s)" % exc)
    return L, jones


def mirror_dt(dt):
    """Mirror image of a link: swap over/under at every crossing = negate every
    signed DT entry.  The crossing count is unchanged."""
    return [tuple(-x for x in comp) for comp in dt]


def _try_backtrack(L, steps):
    for call in (lambda: L.backtrack(num_steps=steps),
                 lambda: L.backtrack(steps),
                 lambda: L.backtrack()):
        try:
            call()
            return True
        except Exception:
            continue
    return False


def backtrack_diagnostic(name, dt, steps=20):
    L = snappy.Link(dt_str(dt))
    L.simplify("global")
    n0 = len(L.crossings)
    fired = _try_backtrack(L, steps)
    n1 = len(L.crossings)
    if not fired:
        print("    %s: backtrack() NOT available in this build -> the 'hard' "
              "rows were only repeated simplify (no escape from plateaus)" % name)
    else:
        print("    %s: backtrack fired, %d -> %d crossings (should rise if it "
              "actually complicated the diagram)" % (name, n0, n1))
    return fired


def strong_reduce(name, dt, rounds=300, steps=25, target=None, verbose=True):
    """Backtrack + simplify repeatedly, logging the round at which each new
    lowest crossing count is reached.  If ``target`` is given, also report the
    first round that reaches it and stop early.

    NOTE: backtrack is randomised, so the exact round varies run to run; set the
    environment variable so you can reproduce a run if needed (see below).
    """
    L = snappy.Link(dt_str(dt))
    L.simplify("global")
    best = len(L.crossings)
    best_round = 0
    hit_target_round = None
    if verbose:
        print("    %s: start = %d crossings (round 0, after initial simplify)"
              % (name, best))
    for r in range(1, rounds + 1):
        before = len(L.crossings)
        _try_backtrack(L, steps)
        after_kick = len(L.crossings)
        L.simplify("global")
        n = len(L.crossings)
        if n < best:
            best = n
            best_round = r
            if verbose:
                print("    %s: round %4d  ->  new best %d crossings  "
                      "(kicked %d up to %d, then simplified to %d)"
                      % (name, r, n, before, after_kick, n))
        if target is not None and n <= target and hit_target_round is None:
            hit_target_round = r
            print("    %s: reached target %d at round %d -- stopping early"
                  % (name, target, r))
            break
    print("    %s: fewest = %d crossings; first reached at round %d "
          "(of %d, steps=%d)" % (name, best, best_round, rounds, steps))
    return best, best_round


def plain_loop(name, dt, rounds=200):
    """The literal 'for _ in range(200): L.simplify(global)' experiment."""
    L = snappy.Link(dt_str(dt))
    L.simplify("global")
    start = len(L.crossings)
    for _ in range(rounds):
        L.simplify("global")
    print("    %s: %d crossings after 1 simplify -> %d after %d more plain "
          "simplify('global') passes" % (name, start, len(L.crossings), rounds))
    return len(L.crossings)


def hard_simplify(name, dt, rounds=200, backtrack_steps=30):
    """Escape local minima: repeatedly complicate (backtrack) then re-simplify,
    tracking the fewest crossings ever seen."""
    L = snappy.Link(dt_str(dt))
    L.simplify("global")
    best = len(L.crossings)
    for _ in range(rounds):
        try:
            L.backtrack(num_steps=backtrack_steps)
        except Exception:
            # older/newer API: try a positional call, else skip the kick
            try:
                L.backtrack(backtrack_steps)
            except Exception:
                pass
        L.simplify("global")
        best = min(best, len(L.crossings))
    print("    %s: fewest crossings reached over %d backtrack+simplify rounds "
          "= %d" % (name, rounds, best))
    return best


def main():
    L1, j1 = describe("link 1", DT1)
    print()
    L2, j2 = describe("link 2", DT2)
    print()

    if j1 is not None and j2 is not None:
        print("Jones equal exactly?                    ", str(j1) == str(j2))
        print("Jones equal up to mirror + framing (q^n)?",
              canonical_key(j1) == canonical_key(j2))
    else:
        print("Jones comparison skipped (need sage for jones_polynomial).")

    print()
    print("Topology check:")
    same_simpl = (len(L1.crossings) == len(L2.crossings)
                  and len(L1.link_components) == len(L2.link_components))
    print("    same simplified crossing/component counts?", same_simpl,
          "(necessary, not sufficient)")
    # Compare the link exteriors.  NOTE: a homeomorphic complement determines a
    # KNOT (Gordon-Luecke) but NOT a link -- different links can share a
    # complement -- so for links this is strong evidence, not proof.
    try:
        iso = L1.exterior().is_isometric_to(L2.exterior())
        print("    exteriors isometric (strong evidence; not proof for links)?", iso)
    except Exception as exc:
        print("    isometry test unavailable (link may be non-hyperbolic): %s"
              % exc)
        print("    -> compare the invariants above; if you need certainty on a")
        print("       non-hyperbolic link, also compare HOMFLY or identify each")
        print("       piece after 'L.split_link_diagram()' / connected-sum split.")

    print()
    print("Explicit mirror of link 1 (negate every DT sign) -- a 10-crossing")
    print("diagram; if link 2 equals this, link 2's minimum is 10, not 12:")
    M1dt = mirror_dt(DT1)
    M1 = snappy.Link(dt_str(M1dt))
    print("    mirror(link1) DT: %s" % dt_str(M1dt))
    print("    mirror(link1) diagram crossings: %d" % len(M1.crossings))
    M1.simplify("global")
    print("    mirror(link1) simplified: %d crossings, %d components"
          % (len(M1.crossings), len(M1.link_components)))
    try:
        jm = M1.jones_polynomial()
        print("    mirror(link1) Jones: %s" % jm)
        if j2 is not None:
            print("    mirror(link1) Jones == link 2 Jones exactly? %s"
                  % (str(jm) == str(j2)))
    except Exception as exc:
        print("    mirror(link1) Jones: n/a (%s)" % exc)
    try:
        print("    mirror(link1) exterior isometric to link 2 exterior? %s"
              % M1.exterior().is_isometric_to(L2.exterior()))
    except Exception as exc:
        print("    isometry(mirror(link1), link2) unavailable: %s" % exc)

    print()
    print("Does backtrack actually fire in this SnapPy/Spherogram build?")
    backtrack_diagnostic("link 1", DT1)
    backtrack_diagnostic("link 2", DT2)

    print()
    print("Harder simplification (is 12 just a stuck local minimum?):")
    plain_loop("link 1", DT1)
    plain_loop("link 2", DT2)
    # link 1 already sits at 10; watch link 2 and report the exact round it hits 10.
    strong_reduce("link 1", DT1)
    strong_reduce("link 2", DT2, target=10)
    print("    (Mirror images share the same minimal crossing number.  If link 2")
    print("     equals mirror(link1) above, its true minimum is 10 and the 12 was")
    print("     only a heuristic plateau of simplify('global').)")


if __name__ == "__main__":
    main()
