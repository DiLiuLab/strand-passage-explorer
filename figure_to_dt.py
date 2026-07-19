#!/usr/bin/env python3
"""
figure_to_dt.py  (v2) — Extract an extended (link) DT code from a raster image
of a knot/link diagram.  Handles BOTH inter-component crossings and a
component that crosses ITSELF.

Method
------
Each colored strand is traced through its morphological skeleton, and its
under-pass GAPS are bridged.  This yields, for every component, one cyclic
centerline polyline whose vertices are tagged real vs. bridged.

Crossings are every intersection of these polylines -- including the
SELF-intersections of a single component's polyline.  Over/under uses one
universal rule:

    the strand that was BRIDGED at a crossing is the UNDER strand
    (a gap means it passed underneath something there);
    the continuous (non-bridged) strand is OVER.

Color presence at the crossing point is only a tie-breaker when the
bridged/continuous test is ambiguous.  This replaces the v1 region-fill
method, which could not represent a component crossing itself.

DT sign convention (Knotscape/SnapPy): an even label is NEGATED when that
even-numbered pass is the OVER strand.

Assumptions / limitations
--------------------------
* Each component is one distinct, saturated, solid color on a light
  background (dark outlines fine).
* Under-pass gaps must be genuine color breaks, and cleaning/pruning must not
  merge two truly-separate same-color strands.  Tune with --max-gap.
* Very tight features can still be smoothed away.  ALWAYS check the annotated
  figure and printed crossing table against your drawing; ambiguous over/under
  calls and unmatched gap ends are printed as warnings.
* --method fill restores the v1 region-fill tracer (robust, fast, blind to
  self-crossings) for messy inputs.

Usage
-----
    python3 figure_to_dt.py diagram.png
    python3 figure_to_dt.py trefoil.png --colors "K:200,30,30"
    python3 figure_to_dt.py diagram.png --order Y,R,B,G --annotate out.png --validate
    python3 figure_to_dt.py messy.png --method fill

Dependencies: numpy, scipy, scikit-image, Pillow.  Optional: spherogram.
"""

import argparse
import itertools
import colorsys
import os
import sys
import warnings

import numpy as np

warnings.filterwarnings("ignore", category=FutureWarning)
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage
from scipy.spatial import cKDTree
from skimage.measure import find_contours
from skimage.morphology import (skeletonize, opening, closing, disk, erosion,
                                remove_small_holes, remove_small_objects)


# ==========================================================================
# 1. Color segmentation
# ==========================================================================

def _hue_image(rgb):
    arr = rgb / 255.0
    r, g, b = arr[..., 0], arr[..., 1], arr[..., 2]
    mx = arr.max(2); mn = arr.min(2); delta = mx - mn
    hue = np.zeros(rgb.shape[:2]); m = delta > 1e-9
    idx = m & (mx == r); hue[idx] = ((g - b)[idx] / delta[idx]) % 6
    idx = m & (mx == g) & (mx != r); hue[idx] = ((b - r)[idx] / delta[idx]) + 2
    idx = m & (mx == b) & (mx != r) & (mx != g)
    hue[idx] = ((r - g)[idx] / delta[idx]) + 4
    sat = np.where(mx > 0, delta / np.maximum(mx, 1e-9), 0)
    return hue / 6.0, sat, mx


def auto_detect_colors(rgb, min_frac=0.004, sat_min=0.35, val_min=0.35,
                       hue_tol=0.06):
    hue, sat, val = _hue_image(rgb)
    keep = (sat > sat_min) & (val > val_min)
    hues = hue[keep]
    if hues.size == 0:
        raise RuntimeError("No saturated pixels; supply --colors.")
    nbins = 90
    hist, edges = np.histogram(hues, bins=nbins, range=(0, 1))
    total = keep.sum(); used = np.zeros(nbins, bool); clusters = []
    for _ in range(12):
        h2 = np.where(used, 0, hist); b = int(h2.argmax())
        if h2[b] == 0:
            break
        lo = hi = b
        while h2[(lo - 1) % nbins] > 0.15 * h2[b] and not used[(lo - 1) % nbins]:
            lo = (lo - 1) % nbins
        while h2[(hi + 1) % nbins] > 0.15 * h2[b] and not used[(hi + 1) % nbins]:
            hi = (hi + 1) % nbins
        bins = []; i = lo
        while True:
            bins.append(i)
            if i == hi:
                break
            i = (i + 1) % nbins
        for i in bins:
            used[i] = True
        if hist[bins].sum() > min_frac * total:
            clusters.append((edges[b] + 0.5 / nbins, hist[bins].sum()))
    clusters.sort(key=lambda t: -t[1])
    merged = []
    for h, cnt in clusters:
        for j, (h2, c2) in enumerate(merged):
            if min(abs(h - h2), 1 - abs(h - h2)) < 2 * hue_tol:
                merged[j] = (h2, c2 + cnt); break
        else:
            merged.append((h, cnt))
    names = {}
    for i, (h, _) in enumerate(merged):
        nm = f"C{i}"
        for cand, hh in [("R", 0), ("Y", 1/6), ("G", 1/3), ("C", .5),
                         ("B", 2/3), ("M", 5/6)]:
            if min(abs(h - hh), 1 - abs(h - hh)) < 0.09:
                nm = cand if cand not in names else f"{cand}{i}"; break
        names[nm] = h
    return names, hue_tol


def masks_from_hues(rgb, hues, hue_tol, sat_min=0.35, val_min=0.35):
    hue, sat, val = _hue_image(rgb)
    good = (sat > sat_min) & (val > val_min)
    out = {}
    for name, h in hues.items():
        dh = np.minimum(np.abs(hue - h), 1 - np.abs(hue - h))
        out[name] = good & (dh < hue_tol)
    return out


# ==========================================================================
# 2a. Strand tracer  (skeleton + gap bridging) -- supports self-crossings
# ==========================================================================

def band_halfwidth(mask):
    dt = ndimage.distance_transform_edt(mask)
    sk = skeletonize(mask)
    v = dt[sk]
    if v.size == 0:
        raise RuntimeError("Empty mask.")
    return float(np.median(v))


def clean_mask(mask, hw=6):
    m = remove_small_objects(mask, 30)
    m = closing(m, disk(2)); m = opening(m, disk(2))
    m = remove_small_holes(m, int(6 * hw ** 2) + 50)
    return m


def _neighbors(p, pts):
    y, x = p
    return [(y+dy, x+dx) for dy in (-1, 0, 1) for dx in (-1, 0, 1)
            if (dy or dx) and (y+dy, x+dx) in pts]


def _prune(pts, thresh):
    pts = set(pts); changed = True
    while changed:
        changed = False
        for e in [p for p in pts if len(_neighbors(p, pts)) == 1]:
            if e not in pts:
                continue
            branch = [e]; prev = None; cur = e
            for _ in range(thresh + 1):
                nb = [q for q in _neighbors(cur, pts) if q != prev]
                if len(nb) != 1:
                    break
                prev, cur = cur, nb[0]; branch.append(cur)
                if len(_neighbors(cur, pts)) >= 3:
                    for b in branch[:-1]:
                        pts.discard(b)
                    changed = True; break
    return pts


def _arcs(pts):
    deg = {p: len(_neighbors(p, pts)) for p in pts}
    nodes = {p for p in pts if deg[p] != 2}
    arcs = []; used = set()

    def walk(a, b):
        arc = [a, b]; prev, cur = a, b
        while deg.get(cur, 0) == 2:
            nb = [q for q in _neighbors(cur, pts) if q != prev]
            if not nb:
                break
            prev, cur = cur, nb[0]; arc.append(cur)
        return arc

    for nd in nodes:
        for f in _neighbors(nd, pts):
            if (nd, f) in used:
                continue
            arc = walk(nd, f)
            for a, b in zip(arc, arc[1:]):
                used.add((a, b)); used.add((b, a))
            arcs.append(arc)
    rem = pts - {p for a in arcs for p in a}
    while rem:
        s = next(iter(rem)); nb = [q for q in _neighbors(s, rem) if q in rem]
        if not nb:
            rem.discard(s); continue
        arc = walk(s, nb[0])
        for p in arc:
            rem.discard(p)
        arcs.append(arc)
    return arcs


def _tangent(arc, which, k=6):
    a = np.array(arc, float)
    if which == 'start':
        p, q = a[0], a[min(k, len(a) - 1)]
    else:
        p, q = a[-1], a[-1 - min(k, len(a) - 1)]
    v = p - q
    return v / (np.linalg.norm(v) + 1e-9)


def trace_component(mask, hw, max_gap=None, verbose=False, log=print):
    """Return dict(poly=(N,2), tags=(N,) bool bridged, pairs, unmatched)."""
    if max_gap is None:
        max_gap = int(7 * hw) + 10
    m = clean_mask(mask, hw)
    sk = skeletonize(m)
    ys, xs = np.where(sk); pts = set(zip(ys.tolist(), xs.tolist()))
    pts = _prune(pts, thresh=int(2.5 * hw) + 4)
    arcs = [a for a in _arcs(pts) if len(a) >= 3]
    if not arcs:
        return None

    ends = []      # (point, arc_idx, which_end, tangent)
    for i, a in enumerate(arcs):
        if a[0] == a[-1] and len(a) > 4:
            continue                     # pure cycle: no gap ends
        ends.append((a[0], i, 'start', _tangent(a, 'start')))
        ends.append((a[-1], i, 'end', _tangent(a, 'end')))

    idxs = list(range(len(ends))); pairs = []
    while idxs:
        i = idxs[0]; pi, ai, ei, ti = ends[i]
        best, bc = None, 1e18
        for j in idxs[1:]:
            pj, aj, ej, tj = ends[j]
            gap = np.hypot(pi[0]-pj[0], pi[1]-pj[1])
            if gap > max_gap:
                continue
            dirn = np.array([pj[0]-pi[0], pj[1]-pi[1]], float)
            dirn /= (np.linalg.norm(dirn) + 1e-9)
            ai_, aj_, straight = dirn @ ti, (-dirn) @ tj, ti @ (-tj)
            if ai_ < 0.2 or aj_ < 0.2:
                continue
            cost = gap * (2 - ai_ - aj_) + 15 * (1 - straight)
            if cost < bc:
                bc, best = cost, j
        if best is None:
            idxs.remove(i); continue
        pairs.append((i, best)); idxs.remove(i); idxs.remove(best)
    unmatched = idxs

    key = {k: (ends[k][1], ends[k][2]) for k in range(len(ends))}
    bridge = {}
    for i, j in pairs:
        bridge[key[i]] = (key[j], ends[i][0], ends[j][0])
        bridge[key[j]] = (key[i], ends[j][0], ends[i][0])

    poly = []; tags = []; visited = set(); cur = (0, 'start'); guard = 0
    while guard < len(arcs) * 3 + 5:
        guard += 1; ai, ei = cur
        if ai in visited:
            break
        visited.add(ai)
        seq = arcs[ai] if ei == 'start' else arcs[ai][::-1]
        for p in seq:
            poly.append((float(p[0]), float(p[1]))); tags.append(False)
        nxt = bridge.get((ai, 'end' if ei == 'start' else 'start'))
        if nxt is None:
            break
        (naj, nej), pf, pt = nxt
        steps = max(2, int(np.hypot(pf[0]-pt[0], pf[1]-pt[1]) / 2))
        for q in np.linspace(pf, pt, steps)[1:-1]:
            poly.append((float(q[0]), float(q[1]))); tags.append(True)
        cur = (naj, nej)
        if naj == 0:
            break
    if verbose:
        log(f"    arcs={len(arcs)} gap_pairs={len(pairs)} "
            f"unmatched={len(unmatched)} poly={len(poly)}")
    return dict(poly=np.array(poly), tags=np.array(tags),
                pairs=pairs, unmatched=unmatched, mask=m, hw=hw)


# ==========================================================================
# 2b. Region-fill tracer (v1 fallback: robust, no self-crossings)
# ==========================================================================

def fill_centerline(mask, pad=40, radii=(10, 14, 18, 22, 26, 32)):
    hw = band_halfwidth(mask); mp = np.pad(mask, pad); solid = None
    for rad in radii:
        s = ndimage.binary_fill_holes(closing(mp, disk(rad)))
        if s.sum() > mp.sum() * 3:
            solid = s; break
    if solid is None:
        raise RuntimeError("Could not close band into a loop.")
    er = erosion(solid, disk(max(1, int(round(hw)))))
    cs = sorted(find_contours(er.astype(float), 0.5), key=len, reverse=True)
    c = cs[0]
    if not np.allclose(c[0], c[-1]):
        raise RuntimeError("Fill contour open (border?). Increase --pad.")
    poly = c[:-1] - pad
    return dict(poly=poly, tags=np.zeros(len(poly), bool),
                pairs=[], unmatched=[], mask=mask, hw=hw)


# ==========================================================================
# 3. Crossings (inter-component + self), universal over/under
# ==========================================================================

def _intersections(P, Q, self_mode):
    nP, nQ = len(P), len(Q)
    Qa, Qb = Q, np.roll(Q, -1, axis=0)
    Qlo, Qhi = np.minimum(Qa, Qb), np.maximum(Qa, Qb)
    out = []
    for i in range(nP):
        p, pr = P[i], P[(i+1) % nP] - P[i]
        lo = np.minimum(P[i], P[(i+1) % nP]) - 1
        hi = np.maximum(P[i], P[(i+1) % nP]) + 1
        cand = np.where(~((Qhi < lo).any(1) | (Qlo > hi).any(1)))[0]
        for j in cand:
            if self_mode:
                if j <= i:
                    continue
                d = min((i - j) % nP, (j - i) % nP)
                if d <= 1:
                    continue
            q, qr = Q[j], Q[(j+1) % nQ] - Q[j]
            den = pr[0]*qr[1] - pr[1]*qr[0]
            if abs(den) < 1e-9:
                continue
            t = ((q[0]-p[0])*qr[1] - (q[1]-p[1])*qr[0]) / den
            u = ((q[0]-p[0])*pr[1] - (q[1]-p[1])*pr[0]) / den
            if 0 <= t < 1 and 0 <= u < 1:
                out.append((i + t, j + u, p + t*pr))
    return out


def _bridged_at(tags, t, n):
    i = int(t) % n
    return bool(tags[i] or tags[(i+1) % n])


def all_crossings(traces, masks, order, min_sep=8):
    comp_passes = {k: [] for k in order}
    crossings = []; cid = 0; ambiguous = 0
    H, W = next(iter(masks.values())).shape
    yy, xx = np.ogrid[:H, :W]
    pairs = [(a, a) for a in order] + list(itertools.combinations(order, 2))
    for a, c in pairs:
        Pa, Ta = traces[a]['poly'], traces[a]['tags']
        Pc, Tc = traces[c]['poly'], traces[c]['tags']
        na, nc = len(Pa), len(Pc)
        raw = _intersections(Pa, Pc, self_mode=(a == c))
        found = []
        for (ti, tj, pt) in raw:
            if all(np.hypot(pt[0]-f[2][0], pt[1]-f[2][1]) > min_sep
                   for f in found):
                found.append((ti, tj, pt))
        for (ti, tj, pt) in found:
            ba = _bridged_at(Ta, ti, na)
            bc = _bridged_at(Tc, tj, nc)
            if ba != bc:
                a_over = not ba
            else:
                ambiguous += 1
                if a == c:
                    a_over = not ba
                else:
                    circ = (yy-pt[0])**2 + (xx-pt[1])**2 <= 3.5**2
                    a_over = (masks[a] & circ).sum() >= (masks[c] & circ).sum()
            comp_passes[a].append((ti, cid, a_over))
            comp_passes[c].append((tj, cid, not a_over))
            crossings.append(dict(id=cid, y=float(pt[0]), x=float(pt[1]),
                                  a=a, c=c, a_over=a_over,
                                  ambig=(ba == bc)))
            cid += 1
    return crossings, comp_passes, dict(ambiguous=ambiguous)


# ==========================================================================
# 4. DT code (per-pass over flag; works for self-crossings)
# ==========================================================================

def dt_code(comp_passes, crossings, order):
    ids = [cr['id'] for cr in crossings]

    def build(flips, offs):
        lab = 1; seq = []; cl = {i: [] for i in ids}
        for k in order:
            pl = sorted(comp_passes[k], reverse=flips[k])
            pl = [(c, o) for _, c, o in pl]
            pl = pl[offs[k]:] + pl[:offs[k]]
            for (c, o) in pl:
                cl[c].append((lab, o)); seq.append((lab, k, c, o)); lab += 1
        for ls in cl.values():
            if len(ls) != 2 or (ls[0][0] % 2) == (ls[1][0] % 2):
                return None
        pair = {}
        for c, ((l1, o1), (l2, o2)) in cl.items():
            o, e = (l1, l2) if l1 % 2 else (l2, l1)
            e_over = o1 if e == l1 else o2
            pair[o] = -e if e_over else e
        comp_of = {l: k for l, k, _, _ in seq}
        groups = [tuple(pair[o] for o in
                        sorted(p for p in pair if comp_of[p] == k))
                  for k in order]
        return groups

    ns = {k: max(1, len(comp_passes[k])) for k in order}
    sols = []
    for f in itertools.product([0, 1], repeat=len(order)):
        flips = dict(zip(order, f))
        for offv in itertools.product(*[range(ns[k]) for k in order]):
            g = build(flips, dict(zip(order, offv)))
            if g:
                sols.append((flips, dict(zip(order, offv)), g))
    if not sols:
        raise RuntimeError("No basepoint/orientation satisfies DT parity.")

    def key(s):
        flat = [x for g in s[2] for x in g]
        return ([abs(v) for v in flat], [v < 0 for v in flat])

    sols.sort(key=key)
    return sols[0]


# ==========================================================================
# 5. Annotation
# ==========================================================================

def annotate(img, traces, seq2, order, flips, path, scale=2):
    im = img.resize((img.width*scale, img.height*scale), Image.LANCZOS)
    d = ImageDraw.Draw(im)
    try:
        font = ImageFont.truetype(
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 17)
    except OSError:
        font = ImageFont.load_default()
    pal = [(160, 0, 0), (0, 0, 170), (0, 110, 0), (140, 110, 0),
           (130, 0, 130), (0, 110, 110)]
    col = {k: pal[i % len(pal)] for i, k in enumerate(order)}

    def pt_tan(k, t):
        P = traces[k]['poly']; n = len(P); i = int(t) % n; fr = t - int(t)
        p = P[i]*(1-fr) + P[(i+1) % n]*fr
        tan = P[(i+4) % n] - P[(i-4) % n]
        if flips[k]:
            tan = -tan
        tan = tan/(np.hypot(*tan)+1e-9)
        return p, tan

    for (lab, k, cid, over, param) in seq2:
        p, tan = pt_tan(k, param); lp = p - tan*15
        x, y = lp[1]*scale, lp[0]*scale
        txt = str(lab); bb = d.textbbox((0, 0), txt, font=font)
        w, h = bb[2]-bb[0], bb[3]-bb[1]
        d.rectangle((x-w/2-2, y-h/2-2, x+w/2+2, y+h/2+3),
                    fill=(255, 255, 255), outline=col[k])
        d.text((x-w/2, y-h/2-2), txt, fill=col[k], font=font)
    for k in order:
        first = next((s for s in seq2 if s[1] == k), None)
        if first is None:
            continue
        tt = (first[4] + (30 if flips[k] else -30)) % len(traces[k]['poly'])
        p, tan = pt_tan(k, tt); tip, base = p+tan*10, p-tan*6
        perp = np.array([-tan[1], tan[0]])
        a1, a2 = tip-tan*9+perp*6, tip-tan*9-perp*6
        d.line((base[1]*scale, base[0]*scale, tip[1]*scale, tip[0]*scale),
               fill=col[k], width=4)
        d.polygon([(tip[1]*scale, tip[0]*scale), (a1[1]*scale, a1[0]*scale),
                   (a2[1]*scale, a2[0]*scale)], fill=col[k])
    im.save(path)


# ==========================================================================
# 6. Shared pipeline (used by both the CLI and the GUI)
# ==========================================================================

def run_extraction(image_path, colors=None, order=None, method="trace",
                   max_gap=None, pad=40, hue_tol=0.06, annotate_path=None,
                   validate=False, log=print):
    """Extract a DT code from a diagram image.

    Emits progress lines through ``log`` (default ``print``) and returns a result
    dict with the DT code and the data needed to re-annotate the figure.  Shared
    by ``main`` (CLI) and ``launch_gui`` so both behave identically.
    """
    img = Image.open(image_path).convert("RGB")
    rgb = np.array(img).astype(float)

    if colors:
        hues = {}
        for spec in colors.split():
            name, val = spec.split(":")
            r, g, b = (int(v) for v in val.split(","))
            hues[name] = colorsys.rgb_to_hsv(r/255, g/255, b/255)[0]
        htol = hue_tol
    else:
        hues, htol = auto_detect_colors(rgb, hue_tol=hue_tol)
        log(f"[info] detected components: {list(hues)}")

    masks = masks_from_hues(rgb, hues, htol)
    for k in list(masks):
        if masks[k].sum() < 200:
            log(f"[warn] dropping tiny component {k}")
            del masks[k]
    if not masks:
        raise RuntimeError("No components found; supply --colors or check the image.")

    traces = {}
    for k, m in masks.items():
        hw = band_halfwidth(clean_mask(m))
        if method == "trace":
            tr = trace_component(m, hw, max_gap=max_gap, verbose=True, log=log)
        else:
            tr = fill_centerline(m, pad=pad)
        if tr is None:
            raise RuntimeError(f"Trace failed for {k}; try method 'fill'.")
        tree = cKDTree(tr['poly']); ys, xs = np.where(clean_mask(m))
        cov = (tree.query(np.column_stack([ys, xs]))[0] < hw+3).mean()
        u = len(tr['unmatched'])
        log(f"[info] {k}: hw={hw:.1f} poly={len(tr['poly'])} "
            f"bridged={int(tr['tags'].sum())} coverage={cov:.1%}"
            + (f"  [warn {u} unmatched gap ends]" if u else ""))
        if cov < 0.9:
            log(f"[warn] {k}: low coverage; trace may be wrong "
                f"(try method 'fill' or a larger max-gap).")
        traces[k] = tr

    order = order.split(",") if order else list(traces)
    if set(order) != set(traces):
        raise RuntimeError(f"order must be a permutation of {list(traces)}")

    crossings, comp_passes, stats = all_crossings(traces, masks, order)
    n_self = sum(1 for cr in crossings if cr['a'] == cr['c'])
    log(f"[info] {len(crossings)} crossings "
        f"({n_self} self, {len(crossings)-n_self} inter-component)")
    for cr in crossings:
        kind = "SELF" if cr['a'] == cr['c'] else f"{cr['a']}x{cr['c']}"
        ov = cr['a'] if cr['a_over'] else cr['c']
        tag = "  <-- color tie-break, verify" if cr['ambig'] else ""
        log(f"  [{cr['id']:2d}] {kind:>7} at ({cr['x']:.0f},{cr['y']:.0f}) "
            f"over={ov}{tag}")
    if stats['ambiguous']:
        log(f"[warn] {stats['ambiguous']} crossing(s) needed a tie-break.")

    flips, offs, dt = dt_code(comp_passes, crossings, order)

    seq2 = []; lab = 1
    for k in order:
        pl = sorted(comp_passes[k], reverse=flips[k])
        pl = pl[offs[k]:] + pl[:offs[k]]
        for (param, cid, over) in pl:
            seq2.append((lab, k, cid, over, param)); lab += 1

    log(f"\nComponent order: {order}")
    log(f"Orientation flips: {flips}   basepoint offsets: {offs}")
    log(f"\nDT: {dt}\n")
    log("Convention: even label negated iff its pass is the over-strand.")

    saved = None
    if annotate_path:
        annotate(img, traces, seq2, order, flips, annotate_path)
        log(f"[info] annotated figure -> {annotate_path}")
        saved = annotate_path

    if validate:
        try:
            import spherogram
            L = spherogram.Link(f"DT: {dt}")
            log(f"[validate] spherogram: {len(L.link_components)} comp, "
                f"{len(L.crossings)} crossings, "
                f"linking matrix {L.linking_matrix()}")
        except ImportError:
            log("[validate] spherogram not installed.")

    return dict(dt=dt, dt_string=f"DT: {dt}",
                order=order, flips=flips, offs=offs, crossings=crossings,
                n_self=n_self, annotate_path=saved,
                _img=img, _traces=traces, _seq2=seq2)


# ==========================================================================
# 7. Graphical interface
# ==========================================================================

def launch_gui():
    try:
        import tkinter as tk
        from tkinter import ttk, filedialog, scrolledtext, messagebox
    except Exception as exc:  # pragma: no cover
        sys.stderr.write("[error] GUI mode requires Tkinter: %s\n" % exc)
        return 1
    import queue as _queue
    import tempfile
    import threading

    root = tk.Tk()
    root.title("figure_to_dt -- image to DT code")
    root.geometry("1000x740")
    root.minsize(860, 600)
    root.columnconfigure(0, weight=1)
    root.rowconfigure(3, weight=1)

    pad = dict(padx=6, pady=3)

    # --- input image row --------------------------------------------------
    top = ttk.Frame(root, padding=(8, 8, 8, 0))
    top.grid(row=0, column=0, sticky="ew")
    top.columnconfigure(1, weight=1)
    ttk.Label(top, text="Diagram image:").grid(row=0, column=0, sticky="w", **pad)
    image_var = tk.StringVar()
    ttk.Entry(top, textvariable=image_var).grid(row=0, column=1, sticky="ew", **pad)

    def browse_image():
        p = filedialog.askopenfilename(
            title="Choose a diagram image",
            filetypes=[("Images", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff *.gif"),
                       ("All files", "*.*")])
        if p:
            image_var.set(p)
            if not annotate_path_var.get():
                stem, _ = os.path.splitext(p)
                annotate_path_var.set(stem + "_annotated.png")
    ttk.Button(top, text="Browse...", command=browse_image).grid(row=0, column=2, **pad)

    # --- options ----------------------------------------------------------
    opts = ttk.LabelFrame(root, text="Options", padding=8)
    opts.grid(row=1, column=0, sticky="ew", padx=8, pady=(6, 0))
    for c in range(4):
        opts.columnconfigure(c, weight=1 if c in (1, 3) else 0)

    colors_var = tk.StringVar()
    order_var = tk.StringVar()
    method_var = tk.StringVar(value="trace")
    maxgap_var = tk.StringVar()
    pad_var = tk.StringVar(value="40")
    huetol_var = tk.StringVar(value="0.06")
    validate_var = tk.BooleanVar(value=False)
    annotate_var = tk.BooleanVar(value=True)
    annotate_path_var = tk.StringVar()

    def _row(r, label, widget, hint=None):
        ttk.Label(opts, text=label).grid(row=r, column=0, sticky="w", **pad)
        widget.grid(row=r, column=1, sticky="ew", **pad)
        if hint:
            ttk.Label(opts, text=hint, foreground="#777").grid(
                row=r, column=2, columnspan=2, sticky="w", **pad)

    _row(0, "Colors:", ttk.Entry(opts, textvariable=colors_var),
         "blank = auto-detect; else e.g.  R:220,30,30 B:30,30,220")
    _row(1, "Component order:", ttk.Entry(opts, textvariable=order_var),
         "blank = detected order; else e.g.  Y,R,B,G")
    _row(2, "Method:",
         ttk.Combobox(opts, textvariable=method_var, values=["trace", "fill"],
                      state="readonly", width=10),
         "trace = skeleton+gap-bridging (self-crossings); fill = region fill")
    _row(3, "Max gap (px):", ttk.Entry(opts, textvariable=maxgap_var),
         "blank = auto; larger bridges longer under-pass gaps (trace mode)")
    _row(4, "Pad:", ttk.Entry(opts, textvariable=pad_var),
         "border padding for the fill method")
    _row(5, "Hue tol:", ttk.Entry(opts, textvariable=huetol_var),
         "color-matching tolerance for auto-detect")

    chk = ttk.Frame(opts)
    chk.grid(row=6, column=0, columnspan=4, sticky="w", **pad)
    ttk.Checkbutton(chk, text="Validate with spherogram",
                    variable=validate_var).grid(row=0, column=0, sticky="w", padx=(0, 16))
    ttk.Checkbutton(chk, text="Save annotated figure",
                    variable=annotate_var).grid(row=0, column=1, sticky="w")
    ap_entry = ttk.Entry(opts, textvariable=annotate_path_var)
    ap_entry.grid(row=7, column=1, sticky="ew", **pad)
    ttk.Label(opts, text="Annotated out:").grid(row=7, column=0, sticky="w", **pad)

    def browse_annotate():
        p = filedialog.asksaveasfilename(
            title="Save annotated figure", defaultextension=".png",
            filetypes=[("PNG", "*.png")])
        if p:
            annotate_path_var.set(p)
    ttk.Button(opts, text="...", width=3, command=browse_annotate).grid(row=7, column=2, **pad)

    # --- action bar + DT result ------------------------------------------
    bar = ttk.Frame(root, padding=(8, 6, 8, 0))
    bar.grid(row=2, column=0, sticky="ew")
    bar.columnconfigure(2, weight=1)
    run_btn = ttk.Button(bar, text="Extract DT")
    run_btn.grid(row=0, column=0, **pad)
    status_var = tk.StringVar(value="Choose an image and press Extract DT.")
    ttk.Label(bar, textvariable=status_var, foreground="#555").grid(row=0, column=1, **pad)
    dt_var = tk.StringVar()
    dt_entry = ttk.Entry(bar, textvariable=dt_var, state="readonly")
    dt_entry.grid(row=1, column=0, columnspan=3, sticky="ew", **pad)

    def copy_dt():
        if dt_var.get():
            root.clipboard_clear(); root.clipboard_append(dt_var.get())
            status_var.set("DT code copied to clipboard.")
    ttk.Button(bar, text="Copy DT", command=copy_dt).grid(row=1, column=3, **pad)

    # --- body: log (left) + annotated preview (right) --------------------
    body = ttk.Frame(root, padding=(8, 6, 8, 8))
    body.grid(row=3, column=0, sticky="nsew")
    body.columnconfigure(0, weight=1)
    body.columnconfigure(1, weight=1)
    body.rowconfigure(0, weight=1)

    log_frame = ttk.LabelFrame(body, text="Log", padding=4)
    log_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 4))
    log_frame.columnconfigure(0, weight=1); log_frame.rowconfigure(0, weight=1)
    log_text = scrolledtext.ScrolledText(log_frame, wrap="word", height=12, width=48)
    log_text.grid(row=0, column=0, sticky="nsew")
    log_text.configure(state="disabled")

    prev_frame = ttk.LabelFrame(body, text="Annotated figure (verify over/under!)",
                                padding=4)
    prev_frame.grid(row=0, column=1, sticky="nsew", padx=(4, 0))
    prev_frame.columnconfigure(0, weight=1); prev_frame.rowconfigure(0, weight=1)
    prev_label = ttk.Label(prev_frame, anchor="center",
                           text="(the annotated figure appears here)")
    prev_label.grid(row=0, column=0, sticky="nsew")
    preview_ref = {"img": None}   # keep a reference so Tk does not GC it

    def append_log(msg):
        log_text.configure(state="normal")
        log_text.insert("end", msg.rstrip("\n") + "\n")
        log_text.see("end")
        log_text.configure(state="disabled")

    def show_preview(path):
        try:
            from PIL import ImageTk
            im = Image.open(path)
            maxw, maxh = max(prev_label.winfo_width() - 8, 360), \
                max(prev_label.winfo_height() - 8, 360)
            im.thumbnail((maxw, maxh), Image.LANCZOS)
            photo = ImageTk.PhotoImage(im)
            preview_ref["img"] = photo
            prev_label.configure(image=photo, text="")
        except Exception as exc:  # pragma: no cover
            prev_label.configure(text="(preview unavailable: %s)" % exc)

    result_q = _queue.Queue()

    def worker(params):
        try:
            def log(m):
                result_q.put(("log", m))
            res = run_extraction(log=log, **params)
            result_q.put(("done", res))
        except Exception as exc:  # noqa: BLE001
            result_q.put(("error", str(exc)))

    def poll():
        try:
            while True:
                kind, payload = result_q.get_nowait()
                if kind == "log":
                    append_log(payload)
                elif kind == "done":
                    dt_var.set(payload["dt_string"])
                    status_var.set("Done. Verify the annotated figure and crossings.")
                    prev = payload.get("annotate_path")
                    if not prev:
                        # annotate to a temp file just for the preview
                        try:
                            tmp = tempfile.NamedTemporaryFile(
                                suffix="_preview.png", delete=False).name
                            annotate(payload["_img"], payload["_traces"],
                                     payload["_seq2"], payload["order"],
                                     payload["flips"], tmp)
                            prev = tmp
                        except Exception:  # pragma: no cover
                            prev = None
                    if prev and os.path.exists(prev):
                        show_preview(prev)
                    run_btn.configure(state="normal")
                elif kind == "error":
                    append_log("[error] " + payload)
                    status_var.set("Failed: " + payload)
                    run_btn.configure(state="normal")
        except _queue.Empty:
            pass
        root.after(80, poll)

    def start():
        path = image_var.get().strip()
        if not path or not os.path.exists(path):
            messagebox.showerror("figure_to_dt", "Please choose an existing image file.")
            return
        try:
            params = dict(
                image_path=path,
                colors=colors_var.get().strip() or None,
                order=order_var.get().strip() or None,
                method=method_var.get(),
                max_gap=int(maxgap_var.get()) if maxgap_var.get().strip() else None,
                pad=int(pad_var.get()) if pad_var.get().strip() else 40,
                hue_tol=float(huetol_var.get()) if huetol_var.get().strip() else 0.06,
                annotate_path=(annotate_path_var.get().strip()
                               if annotate_var.get() and annotate_path_var.get().strip()
                               else None),
                validate=validate_var.get(),
            )
        except ValueError as exc:
            messagebox.showerror("figure_to_dt", "Invalid numeric option: %s" % exc)
            return
        log_text.configure(state="normal"); log_text.delete("1.0", "end")
        log_text.configure(state="disabled")
        dt_var.set("")
        status_var.set("Running (image processing may take a few seconds)...")
        run_btn.configure(state="disabled")
        threading.Thread(target=worker, args=(params,), daemon=True).start()

    run_btn.configure(command=start)
    root.after(80, poll)
    root.mainloop()
    return 0


# ==========================================================================
# main
# ==========================================================================

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[1])
    ap.add_argument("image", nargs="?", default=None,
                    help="Diagram image; omit (or pass --gui) to open the GUI.")
    ap.add_argument("--gui", action="store_true",
                    help="Open the graphical interface (also the default when no "
                         "image is given).")
    ap.add_argument("--colors", default=None,
                    help="Manual colors 'R:220,30,30 B:30,30,220'.")
    ap.add_argument("--order", default=None, help="e.g. Y,R,B,G")
    ap.add_argument("--method", choices=["trace", "fill"], default="trace",
                    help="trace = skeleton+gap-bridging (self-crossings, "
                         "default); fill = v1 region fill (no self-crossings).")
    ap.add_argument("--max-gap", type=int, default=None,
                    help="Max bridged gap length in px (trace mode).")
    ap.add_argument("--annotate", default=None, metavar="OUT.png")
    ap.add_argument("--validate", action="store_true")
    ap.add_argument("--pad", type=int, default=40)
    ap.add_argument("--hue-tol", type=float, default=0.06)
    args = ap.parse_args(argv)

    if args.gui or args.image is None:
        return launch_gui()

    run_extraction(args.image, colors=args.colors, order=args.order,
                   method=args.method, max_gap=args.max_gap, pad=args.pad,
                   hue_tol=args.hue_tol, annotate_path=args.annotate,
                   validate=args.validate, log=print)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
