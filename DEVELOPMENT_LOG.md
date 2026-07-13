DT Link Toolkit Development Log
===============================

This file records version-specific development notes and implementation history.
For installation and everyday usage, see README.md.

draw_dt_original_labels V5.5 (2026-07-12)
-----------------------------------------
* 3D projection window navigation is now a free screen-axis TRACKBALL (Blender /
  ChimeraX / Maya tumble) instead of the elev/azim turntable.  Each motion applies
  an incremental rotation about the CURRENT screen axes -- horizontal drag about
  the screen vertical (y) axis, vertical drag about the screen horizontal (x)
  axis, right-/Shift-drag about the screen z axis (roll) -- with the object
  following the cursor.  The step is composed on the camera basis and decoded back
  to the renderer's (elev, azim, roll) each frame (`_rotate_view_screen_axes` +
  `_projection_angles_from_basis`, an exact inverse of `_projection_basis`, verified
  to round-trip to ~1e-15), so view presets and saved projections stay
  interoperable and there is no elevation pole to stall against.  (Earlier drafts
  tried the elev/azim turntable and a reversed "move the camera" convention; both
  felt unintuitive near the poles.)
* Live projection dragging is much smoother.  While a drag is in progress the
  skeleton/framework overlay is stroked as flat single-line polylines (the full
  depth-shaded halo returns on mouse release) instead of hundreds of per-chunk
  plot calls, crossing dots/IDs are skipped, and the view is framed to the
  object's rotation-invariant bounding sphere so an orbit only ROTATES the curve
  instead of autoscaling ("breathing") every frame -- ~9x fewer artists per frame
  on a skeleton-heavy view.
* Projection over/under gap and hide controls (GUI '3D view' tab + CLI, applied
  live and to saved projections): `crossing gap factor` (`--proj-gap-factor`,
  default 2.8) scales the white occlusion gap at apparent crossings as a multiple
  of the line width; `over/under crossing gaps` (`--proj-no-gaps`) draws strands
  solid with no break; `hide components` (`--proj-hide-components`, a 1-based list
  like `1,3`) hides individual rings.  Threaded through
  `render_projection_on_axis` / `save_projection_images` and the session files.
* Renamed the drawing/model helper to draw_dt_original_labelsV5_5.py and repointed
  the importers -- strand_passage_guiV4_0.py, link_engine_v4_0.py,
  score_diagramV2_0.py -- to it; the previous draw_dt_original_labelsV5_4.py is
  archived under old_scripts/.

draw_dt_original_labels V5.4 (2026-07-11)
-----------------------------------------
* Rotational-symmetry enforcement (`--enforce-symmetry` / `--no-enforce-symmetry`
  + GUI checkbox, default on).  A DT with a cyclic symmetry (each component is the
  next shifted by 2n/k positions, so a 2*pi/k turn maps the link to itself) should
  draw with that symmetry, but the layout pipeline broke it two ways: ring-equalize
  redistributed the crossings around the ring non-symmetrically (tangling the
  otherwise-symmetric solve -- 10 false crossings on the 3-fold BL example), and
  min-sep relaxation + framing added small asymmetric perturbations.
  `_detect_dt_rotational_symmetry(model)` finds the largest k>=2 whose position
  shift s=2n/k is a valid automorphism (crossing permutation + over/under
  preserved).  When found (and enforcement on), `prepare_diagram` disables
  ring-equalize for the solve, and after min-sep `symmetrize_positions` snaps the
  layout onto exact k-fold symmetry by orbit-averaging (Kabsch best-fit rotation
  must be ~2*pi/k with small residual, else it's a guarded no-op -- so a wrap axis
  that hides the symmetry, or a non-symmetric link, is left untouched).  On the
  3-fold BL session this takes residual 0.096 (10 false) -> 0.000 (0 false); the
  tertiary wrap axis was the one that already revealed the symmetry (best-fit
  rotation +120deg, vs ~0deg for primary/secondary).  No-op verified on the
  5-component Edwards-Venn link (no symmetry detected); the trefoil correctly gains
  its classic 3-fold symmetry.
* GUI crash fix (`Tcl_AsyncDelete: async handler deleted by the wrong thread` /
  `Variable.__del__` "main thread is not in main loop", ending in SIGABRT).  The
  Agg backend was forced only in NON-gui mode, so the GUI used the interactive
  TkAgg/MacOSX pyplot backend.  Every `plt.subplots()`/`plt.close()` then built a
  Tk figure manager holding tkinter Variables; the background preview worker does
  heavy allocation, so its cyclic garbage collector would finalize those
  Tcl-backed objects off the main thread and abort.  Now `matplotlib.use("Agg")`
  runs unconditionally -- the GUI embeds figures with `FigureCanvasTkAgg` directly
  (backend-independent) and never calls `plt.show()`, so it needs no interactive
  backend; pyplot figures now carry no Tcl objects for the worker's GC to touch.
* holed-tutte: generalized the 'secondary principal axis' toggle into a 3-way
  'wrap axis (PCA)' selector (`--wrap-axis {primary,secondary,tertiary}` + GUI
  dropdown, default primary).  `_holed_torus_coords(G, wrap_axis=...)` now picks the
  projection plane from the 3D-torus layout's three principal axes (eigh ascending:
  e[:,2]=widest W, e[:,1]=middle M, e[:,0]=thinnest T): primary=(W,M) donut plane,
  secondary=(W,T), tertiary=(M,T) -- the plane perpendicular to the widest axis, so
  the curved axis is orthogonal to both primary and secondary.  Cache key uses the
  wrap_axis string.  `holed_tutte_layout` gained a `wrap_axis` kwarg; the old
  `secondary_axis` bool is still accepted and maps to 'secondary' when `wrap_axis`
  is None, and `--secondary-axis` stays as a deprecated CLI alias.  GUI: the
  checkbox became a readonly Combobox (primary/secondary/tertiary), moved into
  session_string_vars (was a bool), with backward-compat load mapping an old
  boolean `secondary_axis` to 'secondary'.  Verified all three axes give distinct
  false=0 layouts and secondary matches the old boolean.
* flatten orthogonal: fixed the horizontal ring doubling back on the 6-comp
  (62-crossing) link.  The return-arc code assumed the OUT crossing's comp-order
  SUCCESSOR is the right (larger-s) extreme and its predecessor the left -- true for
  the 5-comp link, but reversed here (pred = right extreme c57, succ = left extreme
  c53).  It therefore flung c53 (a left crossing) out to the +R_out right end, so
  the line jumped ~1.5 spans back and forth.  Now it picks `far` = whichever
  neighbour has the larger s (attaches to it over the top via the return arc) and
  `near` = the smaller-s neighbour (a short on-axis diameter hop), placing the apex,
  the two stretched end corners, and the arc-interval metadata on the correct side.
  Worst backward step on the horizontal ring dropped from ~1.5 spans to <0.01 (the
  residual is the sub-percent stub offset where a shared crossing's drawn centre
  differs slightly from its axis projection -- invisible).  Verified single
  monotone diameters + perfect semicircles, false=0, on the 5-, 4-, and 6-comp
  Edwards-Venn links.
* flatten orthogonal, three more fixes for straightness / circularity / alignment:
  (a) The arc circle was fitted through three run control points, one of which is
  the OUT crossing's recomputed centre (mean of its gadget corners); the stretched
  corners pulled that centre off the true circle, tilting the fit so the inner arc
  read as an ellipse. Now `_override_flat_component` least-squares-fits the circle
  through only the run's seg/corner nodes (skipping crossing-centre nodes, index
  %4==1), which lie exactly on the intended circle -> both arcs are perfect,
  concentric semicircles. (b) Corners were placed as `mid +/- stub*u` regardless of
  travel direction, so on the return (leftward/downward) pass the in/out corners
  were swapped and the straight diameter zig-zagged by ~one stub at each crossing.
  Now `corners_toward_segs` points each in-corner at the seg it arrived from and
  each out-corner at the seg it leaves toward, so the diameter is monotone (single
  direction) and the crossing centre = corner mean stays put. c24's own corners sit
  just off the leftmost point ON the arc circle. (c) The two flat rings are mutually
  perpendicular but the collapsed pair can sit at any angle (e.g. 45deg/135deg for
  the 4-comp Edwards-Venn link, vs 0/90 for the 5-comp one). Before placing, the
  whole pre-framing layout is now rotated about its centre so the horizontal ring's
  axis lands on x (the other then on y), keeping the round wreath consistent, so
  both diameters come out axis-aligned ('always to the left' / 'to the top') for
  every input. Verified false=0 and clean axis-aligned D's with perfect semicircles
  on the 5-comp, 4-comp, and 6-comp (62-crossing) Edwards-Venn links.
* flatten orthogonal, two follow-up fixes: (1) `separation` no longer had a hidden
  0.05 floor (`R_in = R_out - max(0.05, sep)`), so `separation=0` kept a small gap
  instead of coinciding; now `R_in = min(R_out, max(0.15*dia, R_out - sep*dia))`,
  so at `sep=0` the inner and outer radii are equal and the two semicircles overlap
  in their shared quadrant (a degenerate limit that flags 2 overlap crossings, as
  expected). (2) The horizontal ring's RIGHT diameter end is the in-corner of the
  succ extreme (e.g. c29), which is shared with a round ring; stretching it to the
  end dragged c29's centre out (to +0.72 vs c28 at -0.50) and stretched that round
  strand. Fixed by recording such stretched corners in `model["flatten_exclude"]`
  and dropping them from `crossing_centers`' per-crossing average, so the crossing
  (and the round strand through it) stays put while the flat strand still reaches
  the end; c29 now sits symmetric to c28 (+0.55 vs -0.50). The vertical ring never
  had this because its arc ends on seg nodes, not corners.
* flatten orthogonal: reworked the 'D' geometry into two concentric D's drawn as
  EXACT straight-line + perfect-semicircle geometry. Each flat ring is now a
  straight DIAMETER through the centre (all its crossings on it, kept at their own
  signed axis positions so the diameter is symmetric about the centre) plus a
  perfect SEMICIRCLE joining the two diameter ends. The horizontal ring is the
  outer D (semicircle radius `R_out = outer_radius*dia` over the top); the vertical
  ring the inner D (semicircle radius `R_in = R_out - separation*dia` bulging left).
  The inner semicircle's leftmost point is the shared OUT crossing, which therefore
  lands on the outer diameter; the other shared crossing stays at the centre where
  the diameters cross. Because the arcs are true circles they cannot be Catmull
  splines through the sparse gadget nodes, so `_flatten_orthogonal_rings` records
  the arc control-point interval indices per component in `model["flatten_arcs"]`
  and a render override (`_override_flat_component`, via the shared
  `_component_dense` used by both `render_diagram` and the false-crossing audit)
  redraws those intervals as points on the fitted circle and every other interval
  as a straight segment. This yields perfect semicircles, dead-straight diameters,
  and genuine tangent-discontinuous right-angle CORNERS at the junctions (Catmull
  could give none of the three). `separation` changed meaning: it is now the radial
  GAP between the two concentric D's (inner radius = outer − separation), matching
  the original 'outer-ring radius + separation of the two rings' request. `false=0`
  on the 5-component Edwards-Venn link across `outer_radius` 0.9–1.6 / `separation`
  0.15–0.6; true no-op (empty `flatten_arcs`) when nothing is orthogonal or the
  option is off. Exact only at `ring_tilt=90` (the flat top view; other tilts are
  non-affine and warp the circles). (Superseded the asymmetric straight-line +
  return-arc spline form below.)
* holed-tutte `use secondary principal axis` (`--secondary-axis` + GUI checkbox).
  `_holed_torus_coords(G, secondary=...)` builds the closed principal curve from a
  3D Kamada-Kawai layout projected onto two principal axes of `q3.T @ q3`
  (`numpy.linalg.eigh`, ascending). Primary uses `evec[:,2]`,`evec[:,1]` (the two
  widest — the donut plane); secondary swaps the second axis for `evec[:,0]` (the
  thinnest / hole axis), wrapping the diagram around the perpendicular principal
  curve. For the Edwards-Venn examples the 3D eigenvalues come out roughly
  `[small, large, large]` (two near-equal wide axes + one thin), so the secondary
  view is a real ~90° reorientation, not a trivial rotate. `secondary` is folded
  into the torus cache key and threaded `holed_tutte_layout` -> `tutte_opts`.
* GUI: moved every parameter-panel checkbox from `column=1, columnspan=2` to
  `column=0, columnspan=3` (auto-aspect check to `column=0, columnspan=2`, keeping
  its value label at column 2) so long checkbox labels are no longer clipped. The
  flatten radius/separation entries now grey unless the flatten checkbox is on
  (`flatten_on = is_holed_tutte and flatten_orthogonal_var.get()`), and
  `flatten_orthogonal_var` was added to the selector-var trace list so toggling it
  re-runs `_apply_dynamic_states`.
* Over/under gap rendering: at each crossing the under strand is masked with a
  white piece (`_plot_local_curve_piece_by_index`, `radius=gap` arc length) and
  the over strand is redrawn on top. The over piece was hardcoded at `gap * 1.25`,
  too short to cover the white mask at shallow crossings (a visible white nick).
  Replaced the constant with an `over_gap_factor` parameter on `render_diagram`
  (and threaded through `draw` / `render_figure` / `render_prepared_diagram` /
  `run_pipeline`), default `2.0`, clamped to `>= 1.0` via
  `over_gap = gap * max(1.0, over_gap_factor)`; applied to both true and
  false-crossing over pieces. Exposed as `--over-gap-factor` and a GUI `over gap
  factor` field (saved in sessions, recorded in image metadata).
* holed-tutte: added `flatten orthogonal components` (`--flatten-orthogonal` +
  `--flatten-outer-radius` / `--flatten-separation`, and matching GUI fields next
  to `invert ring`). Rings that lie edge-on to the diagram collapse under the
  boundary-pinned harmonic solve onto a straight line through the centre
  (near-zero PCA minor axis), overlapping everything. Verified on three examples
  (the 5-component link above, plus a 4-component and a 6-component Edwards-Venn
  case): each has exactly two flat rings sharing exactly two crossings, antipodal
  in each traversal. The `_flatten_orthogonal_rings(pos, model, center,
  outer_radius, separation)` helper (called inside `holed_tutte_layout`, after
  invert-ring and before ring-tilt/framing) detects each near-collinear component
  (`sv[1]/sv[0] < 0.18`) and redraws it as a big "D": a long straight line plus one
  large-radius arc. The OUT crossing = the single movable (shared-between-flat)
  crossing that lies strictly between the ring's two extreme crossings; it is
  pushed to a shared point `P_out` far to one side along the HORIZONTAL ring's own
  axis. The construction is asymmetric so `P_out` lands on one ring's straight line
  and the other ring's arc (their intersection): the horizontal ring (axis nearest
  x) keeps the out crossing ON its dead-straight line — its only curve is the
  RETURN connector between the two line ends, thrown over the top via an apex seg
  node; the vertical ring's arc bulges sideways THROUGH `P_out`, a big circle whose
  seg-node poles are the line ends `O ± u*(half_len + separation*diameter)` (past
  the extreme crossings, so those stay internal). Two subtleties keep the vertical
  arc clean under the uniform (non-centripetal) Catmull-Rom: (a) every line crossing
  stubs ALONG the ring axis `u` (not `mid[i+1]-mid[i-1]`, which for the extremes
  points off toward `P_out` and kinks the line); (b) the out crossing's in/out
  corners are offset a real FRACTION (0.32) of the way toward each pole rather than
  a tiny stub, so pole->corner->centre is evenly spaced and the tip doesn't pinch a
  loop (a tiny segment flanked by a far neighbour makes the uniform spline
  overshoot). Distances are in ring diameters (not the span, which is inflated by
  the collapsed gadget corners): `outer_radius` (default 1.1) scales `P_out` and
  the return-arc apex, `separation` (default 0.25) the pole extension. The central
  shared crossing stays at the centre (both diameters cross there). Only flat
  components' own gadget nodes move; round-shared crossings keep their centre fixed,
  so the wreath is untouched. `model` threaded via `tutte_opts["model"]`. True
  no-op when nothing is orthogonal. The 5-component Edwards-Venn link renders
  false=0 with c18/c21 and c28/c29 internal on their straight lines, the shared out
  crossing (c24) far on the left as a clean crossing, and c26 at the centre;
  `sphere-stereo` stays the route for fully clean overlapping ovals. (Earlier V5.4
  iterations drew a symmetric big-arc "D" with both arcs connecting extended poles;
  superseded by this asymmetric straight-line + return-arc form on request.)
* Added `audit_xyz.py`, an importable and standalone Spherogram/SnapPy audit
  that reconstructs the link represented by a finished 3D polyline and compares
  it with the source signed DT link. Its dependencies are loaded lazily so
  imports and `--help` still work outside the Sage/SnapPy environment.
* Added the correct-by-construction `--sphere-layout stereo-safe`, which lifts
  the audited planar layout stereographically and changes only radial position
  at over/under crossings.
* Added optional clearance repair for Kamada XYZ layouts (`--xyz-clearance`,
  `--no-xyz-repair`) and exposed those controls in the standalone GUI and V5.4
  session files.
* `Save XYZ`, `View XYZ`, and `Redraw 3D projection` now use the same repair and
  topology-audit pipeline. Audit results appear in the main status log and as
  persistent color-coded banners in both interactive 3D windows.
* Follow-up GUI polish: live 2-D state calculation runs on a single background
  worker with stale jobs discarded, and scroll-panel geometry is debounced so
  parameter tabs paint before preview work resumes. Fixed projection grids
  retain their view basis across `Redraw 3D projection`. The projection save
  dialog now proposes the XYZ basename without its `.xyz` extension.
* strand_passage_guiV4_0.py, link_engine_v4_0.py, and score_diagramV2_0.py now
  import draw_dt_original_labelsV5_4.py as the live drawing/model helper.

draw_dt_original_labels V5.3 (2026-07-10)
-----------------------------------------
* Surface wireframe styling: --proj-grid-density (meridian count; parallels ~
  half; 0 = no mesh; needs a projection redraw since the mesh is built with
  the curve via skeleton_grid=...), --proj-grid-color and --proj-grid-lw
  (render-side, applied live from the cached curve).
* Framework chords between crossing anchors can be hidden independently
  ('framework chords' checkbox / --proj-hide-chords).
* Mouse roll in the projection window: right-drag or Shift+left-drag rotates
  about the view axis, pivoting on the canvas centre (incremental atan2 of
  the cursor about the centre; Tk y-down sign gives the grab-and-turn feel).
  Left-drag still orbits, wheel still zooms.
* Render-side style toggles (chords / skeleton / IDs / skeleton-only) now
  re-render the cached curve immediately -- no 3D rebuild.
* Projection crossing anchor dots can be shown independently and are hidden by
  default (`crossing anchor dots` / --proj-crossing-dots).
* The mapped-surface grid can be fixed to the last projection rebuild view while
  live orbit/roll rotates the strands (`fixed grid while rotating` /
  --proj-fixed-grid).
* At the V5.3 release, strand_passage_guiV4_0.py, link_engine_v4_0.py, and
  score_diagramV2_0.py imported V5.3 as the live drawing/model helper.

draw_dt_original_labels V5.2 (2026-07-10)
-----------------------------------------
User feedback round on V5.1:

* Mapped skeleton redone to match score_diagramV2_0's sphere panels: 'show
  mapped skeleton' now draws (a) a light depth-shaded WIREFRAME of the whole
  mapped surface -- a unit-sphere grid stored in skeleton_out['surface_wires'],
  scaled and passed through the same warp as the strands, so the mesh IS the
  actual sphere/ellipsoid/cylinder/torus -- (b) NEUTRAL dark-gray framework
  chords (component colours are reserved for the smooth strands; colouring the
  chords doubled the palette and read as noise), and (c) black depth-faded
  anchors.
* New 2D layout 'sphere-stereo' (the creative answer for FLAT diagrams of
  links whose rings lie in near-orthogonal planes, e.g. Edwards-Venn AM5,
  which collapse in every boundary-pinned layout): 3D Kamada-Kawai unit
  directions + gadget compaction (same machinery as the XYZ pipeline), pole =
  Fibonacci-sphere direction with the largest angular clearance from all
  nodes AND strand-arc samples, then stereographic projection from the pole
  (a homeomorphism of the punctured sphere, so the image is a genuine planar
  diagram; the pole's face becomes the outer region).  'ring equalize' now
  also applies here as a smooth power-law radial expansion (gamma = 1-0.6s)
  about the centroid -- rank-based equalization broke planarity of straight
  chords (2 false crossings), the smooth monotone map does not (audit-clean at
  s = 0.5-0.8 with relax 12 + min-sep 0.02 on AM5).

draw_dt_original_labels V5.1 (2026-07-10)
-----------------------------------------
Motivation: the corrected Edwards-Venn AM5 code [(32,18,...),...] has rings in
near-orthogonal planes -- every axis-aligned projection leaves one ring
edge-on (a sliver), so V5.0 projections were ambiguous.

New in draw_dt_original_labelsV5_1.py:
* auto_projection_view(): grid+refine search over the view sphere maximizing
  the WORST component's projected isoperimetric roundness (4*pi*A/P^2), so no
  ring degenerates edge-on.  'Auto view' buttons + --proj-auto-view.
* Depth-cue transparency (--proj-depth-fade, default 0.55) for strands and
  skeleton, following score_diagramV2_0's _draw_sphere_depth style.
* Perspective camera option (--proj-perspective, scene radii; 0 = ortho).
* Mapped skeleton is now the whole framework: per-strand quadratic arcs
  through the connector anchors, component colours, per-segment depth alpha,
  depth-faded anchor dots; --proj-skeleton-only for a framework-only view
  (skeleton_out gains 'segment_comps').
* Projection window: left-drag rotates (0.4 deg/px, throttled fast redraw
  while dragging -- plain thin lines -- full halo render on release), scroll
  wheel zooms about the view centre (zoom preserved across re-renders).
* All new fields in sessions/CLI/help; V4.x and V5.0 sessions still load.

draw_dt_original_labels V5.0 (2026-07-10)
-----------------------------------------
Motivation: the 80-crossing closed-fishtail link (16 crossings/band, 5 bands)
exposed two limits of V4.5 -- the holed-tutte harmonic solve compresses
interior strands toward the pinned rims (uneven, edge-crowded 2D diagrams),
and some links (e.g. the Edwards-Venn Brunnian family) have no readable flat
diagram at all.

New in draw_dt_original_labelsV5_0.py (V5.5 is now the live helper imported by
the strand-passage and scoring tools):
* --ring-equalize (holed-tutte): radial histogram equalization across the ring
  width after the harmonic solve; angles kept; 0..1 blend.
* --relax-passes / --relax-strength (all 2D layouts): planarity-guarded
  relaxation (centroid + edge-length equalization); a pass is rejected and the
  step halved if it would create a straight-edge crossing (vectorized
  all-pairs segment test); pinned boundary nodes from the layout are held
  (holed-tutte exports meta 'pinned_nodes'; others pin an angular-bin hull).
* Illustrative 2D projections of the 3D Sphere-XYZ curve: orthographic
  projection with depth-ordered chunks stroked over butt-capped white halos
  (round/projecting halo caps overhang the chunk ends and erase the strand's
  own continuation -- the butt cap plus one-step chunk overlap is what makes
  strands continuous with gaps only at true occlusions).  New '3D view' GUI
  tab + persistent projection window; heavy 3D construction only on 'Redraw 3D
  projection', quick-view buttons re-project the cached curve.  'Mapped
  skeleton' overlay = per-crossing anchors + strand chords of the sphere
  layout, put through the same surface warp (kamada layouts).
* Save projections as SVG+PNG next to the .xyz ('Save projection(s)' button,
  'Save XYZ also saves projections' checkbox, CLI --save-projections
  --proj-views current,top,front,side --proj-elev/azim/roll
  --proj-line-width --proj-skeleton --proj-skeleton-ids).
* UI: third parameter tab '3D view'; 'View XYZ' moved there; save-button row
  compacted; sessions serialize all new fields and still load V4.x files.
* build_spherical_xyz_components gains skeleton_out=...;
  _warp_components_to_surface gains return_warp=... (point-set warp reuse).


DT-code link toolkit with component-colour-preserving strand-passage
exploration, drawing, SnapPy/Sage comparison and search utilities, and diagram
scoring. Every crossing you click in the strand-passage GUI opens a NEW WINDOW
showing the chosen after-passage topology; each new window is itself clickable,
so passages chain (and may branch) across as many windows as you like.

Files
-----
    strand_passage_guiV4_0.py         (V4.0) interactive GUI + --nongui + --demo
    link_engine_v4_0.py               (V4.0) passage / DT-choice / SnapPy engine
    draw_dt_original_labelsV5_5.py    (V5.5) drawing + model layer
    audit_xyz.py                       XYZ topology audit helper / CLI
    check_two_dt.py                   standalone SnapPy/Sage utility: compare two
                                      DT codes (topology + Jones + backtrack test)
    find_link_in_snappy.py            standalone SnapPy database search utility
    score_diagramV2_0.py              standalone SnapPy/Sage diagram scoring utility
    assets/strand_passage_icon.png    optional Tk window/task-menu icon
    assets/score_diagram_icon.png     optional scoring-tool Tk window icon
    bin/strand-passage                convenience launcher
    DEVELOPMENT_LOG.md

--nongui outputs
----------------
    <name>.xlsx           the two-pass spreadsheet (run_info sheet, first_pass
                          sheet, and one sheet per merged first-step structure)
    <name>_overview.svg   a large, tidy overview of every resulting structure

Run
---
    sage -python strand_passage_guiV4_0.py                     # SnapPy enabled
    sage -python strand_passage_guiV4_0.py --dt "DT: [(4,6,2)]"
    python3 strand_passage_guiV4_0.py --gui-backend agg        # if TkAgg won't load
    ./bin/strand-passage --help                                # launcher

Backtrack-assisted simplification (ON by default: 200 rounds, 30 steps):
    sage -python strand_passage_guiV4_0.py                     # backtrack ON
    sage -python strand_passage_guiV4_0.py --backtrack-rounds 400
    sage -python strand_passage_guiV4_0.py --no-backtrack      # turn it OFF
    (in the GUI, the "Backtrack simplify" checkbox + rounds/steps fields start
     ON at 200/30 and can be toggled live between clicks.)

Non-interactive two-pass spreadsheet:
    sage -python strand_passage_guiV4_0.py --nongui \
        --dt "DT: [(-8,-12,16),(-24,-22,-28,-26),(-10,-14,-2),(-20,-6,-18,-4)]" \
        --out strand_passage_results.xlsx        # backtrack ON by default

Headless cascade figure (no display needed):
    python3 strand_passage_guiV4_0.py --dt "DT: [(4,6,2)]" --demo 2 1 --out chain.png


What is new in V4.0 (GUI simplify + drawing sessions)
-----------------------------------------------------
  * Bumped the live strand-passage entry point to strand_passage_guiV4_0.py and
    the engine bridge to link_engine_v4_0.py.
  * Added a per-diagram "Simplify" button in GUI windows.  It simplifies the
    currently displayed root or after-passage diagram with the active SnapPy
    global/backtrack settings and refreshes the properties panel, including
    Jones data when Sage/SnapPy can compute it.
  * Replaced the two GUI crossing-label fields with one `Crossing labels` field.
    Assignment-style text such as `c1=1,c7=3` is detected as a crossing map;
    otherwise the text is treated as a crossing order.  The old
    `--crossing-order` and `--crossing-map` CLI options remain supported, and
    `--crossing-labels` exposes the combined parser on the CLI.
  * Strand-passage drawing defaults are now `shaped-tutte` with `tutte shape =
    ellipse`, manual `tutte aspect = 1.0`, and helper-compatible false-crossing
    visualization.  These defaults apply in the GUI, `--demo`, `--nongui`
    overview SVG, and following strand-passage diagrams.
  * Added `--drawing-session PATH` plus the GUI `Load drawing session` button.
    Sessions saved by draw_dt_original_labelsV5_4.py supply DT/crossing labels
    and 2-D drawing settings; explicit `--dt` still takes priority in CLI modes.
  * Moved `Close passage windows` and `Load drawing session` to the second
    control row beside the crossing-label field, and added light-blue `?` help
    buttons for SnapPy global and backtrack simplify settings.


Scoring utility V2.0
--------------------
  * Added score_diagramV2_0.py, a standalone Sage/SnapPy utility for generating
    alternative simplified diagrams of one link, deduplicating signed diagram
    isomorphs, scoring each representative, and writing Excel/SVG/JSON reports.
  * The tool imports the live V4.0 engine and drawing helper (V4.5 at its
    initial release; V5.5 now), uses the same backtrack-simplify mechanism for
    generation, and scores canonical DT forms so representative rankings are
    reproducible across relabellings.
  * With no arguments it opens a Tk configuration GUI; CLI mode supports
    resumable checkpoints, time-limited generation chunks, membership checks for
    pasted DT codes, optional exact VF2 verification, and generated reports.
  * The scoring GUI uses `assets/score_diagram_icon.png` as its Tk window icon
    when the asset can be loaded.
  * Generated scoring outputs (`chain*.jsonl`, `diagram_scores*`,
    `canonical_cache.json`, and `results/`) are ignored by Git.


Utility update (SnapPy database search)
---------------------------------------
  * Added find_link_in_snappy.py, a standalone utility that searches SnapPy's
    HTLinkExteriors and LinkExteriors databases for DT-code matches.
  * Search order is extended alphabetic DT with flips, exact numeric DT,
    optional loose numeric DT, then meridian-preserving exterior identification
    for hyperbolic links.  Output is a TSV table.


Utility update (DT comparison CLI)
----------------------------------
  * check_two_dt.py now has a real argparse CLI.  `--help` prints usage without
    starting the SnapPy comparison/backtrack workflow.
  * Added `--dt1` / `--dt2` for comparing arbitrary signed DT codes, plus
    `--rounds`, `--steps`, `--plain-rounds`, `--diagnostic-steps`, `--target`,
    `--skip-mirror`, and `--skip-backtrack` controls.
  * Running with no arguments preserves the historical built-in DT1/DT2
    comparison and its old link-2 target of 10 crossings.


Drawing helper V4.5 (tabbed parameter panel)
--------------------------------------------
  * draw_dt_original_labelsV4_5.py became the live drawing/model helper imported
    by link_engine_v4_0.py and strand_passage_guiV4_0.py.
  * The standalone helper GUI splits its right-hand parameter panel into two
    independently scrollable tabs: "2D diagram" and "3D XYZ", so only relevant
    controls are shown at a time.
  * Earlier V4 features are retained, including shaped/holed Tutte layouts,
    holed-tutte torus/wreath placement, session save/load, false-crossing
    visualization, self-crossing gaps, editable SVG text, and metadata captions.


Drawing helper V3.14 (false-crossing visualization)
---------------------------------------------------
  * draw_dt_original_labelsV4_5.py keeps the requested 2-D layout even when it
    introduces false crossings; it no longer silently falls back to `planar`.
  * False crossings are drawn with the same local over/under gap style as true
    crossings, with deterministic but arbitrary over/under choice because they
    are layout artifacts rather than real DT crossings.
  * Live previews and saved images/SVGs show a red false-crossing warning.
  * Saved diagrams now also draw the generator metadata as a visible bottom
    caption, in addition to embedding it in file metadata.
  * link_engine_v4_0.py preserves the helper's requested layout so
    strand_passage_guiV4_0.py matches the helper rendering behavior.


Drawing helper V3.13 (self-crossing gaps + metadata)
----------------------------------------------------
  * draw_dt_original_labelsV3_13.py fixes over/under gap rendering at
    self-crossings, e.g. the trefoil `DT: [(4,6,2)]`, by selecting local
    crossing pieces along the curve parameter rather than by spatial radius.
  * Saved SVG/PDF/PNG diagrams now embed generator metadata: script name,
    helper version, component/crossing counts, key drawing parameters, and a
    timestamp.
  * The standalone helper GUI reduces the DT-code box to two lines, removes the
    redundant refresh button and explicit CSV table field, and improves
    mouse-wheel scrolling over the right parameter panel.
  * The strand-passage GUI/engine imported V3.13 directly before the later
    V3.14 helper bump.


What is new in V3.8 (overview SVG text-box sizing)
--------------------------------------------------
  * --nongui overview SVGs now apply Arial before the figure is measured and
    drawn, instead of only immediately before saving the SVG.
  * The overview card/header geometry is slightly roomier, and the arrow-label,
    footer, DT-label, and crossing-ID text boxes/circles use larger padding.
  * draw_dt_original_labelsV4_5.py includes the same font/padding adjustment
    for standalone helper SVG/PDF exports, so the live helper preview and final
    SVG are less likely to diverge in Illustrator.
  * Font sizes still come from the GUI/CLI values: `DT label font` /
    `--font-size` and `crossing ID font` / `--crossing-id-font-size`.
  * This keeps text editable while reducing the mismatch where Illustrator could
    display the final SVG text as slightly larger than the live Matplotlib view,
    making the surrounding boxes/circles look too small.


What is new in V3.7 (editable overview SVG text)
------------------------------------------------
  * --nongui overview SVGs now keep all labels and captions as editable SVG text
    instead of expanding glyphs to outline paths.
  * Overview text is forced to Arial before export to reduce Adobe Illustrator
    font-substitution warnings while keeping the text selectable/editable.


What is new in V3.6 (continuation rule + run metadata)
------------------------------------------------------
  * --nongui now continues a first-step passage into the second pass when
    `new_components > 2` and the first-step row has a usable chosen DT code.
    This replaces the previous same-component-count criterion.
  * CLI output now prints the exact second-pass continuation criterion and
    reports "continuable first-step passage(s)" rather than "eligible" passages.
  * Each --nongui workbook now starts with a `run_info` sheet containing the
    software version, engine/drawing module versions, runtime, command/arguments,
    output paths, key parameters, continuation criterion, and continuation
    counts used for that result.


What is new in V3.5 (merged first-step continuations)
-----------------------------------------------------
  * --nongui now runs the second-pass strand-passage enumeration once per merged
    first-step structure, not once per raw first-step crossing. The first-step
    nodes are reconciled with the same per-step merge logic used by the overview
    before any second-pass continuations are launched.
  * This makes repeated runs more consistent and avoids spending time on
    equivalent first-step diagrams that would later collapse into the same
    overview card.
  * Second-pass workbook sheets are named after the merged first-step node
    (`merged_<node>_<labels...>`). Each second-pass row records
    `first_step_passages` and `first_step_representative` so the spreadsheet
    still shows exactly which first-step crossings merged and which diagram was
    used for continuation.


What is new in V3.4 (GitHub packaging + icon)
---------------------------------------------
  * The public README now includes clone, pull, install, run, and executable-use
    notes for a GitHub checkout.
  * The repository includes an MIT license and a small bin/strand-passage
    launcher. The launcher uses sage -python when Sage is on PATH and otherwise
    falls back to python3.
  * draw_dt_original_labelsV3_11.py adds optional Tk window/task-menu icon
    support using assets/strand_passage_icon.png. If the icon file is absent or
    the local Tk build cannot load it, the GUI simply continues without an icon.
  * Bug fix: the GUI and --nongui outputs now report the Jones polynomial of the
    exact DT code shown/drawn and used for the next passage step. This avoids
    mismatches when a transient SnapPy simplified object and its exported
    DT_code do not round-trip with identical Jones values.
  * --nongui spreadsheets now also report hidden split unknots omitted by a
    SnapPy DT export.  In that case `Jones_polynomial` remains the polynomial of
    the visible `DT_code_chosen`, while `topological_Jones_polynomial` keeps the
    SnapPy simplified-link polynomial with the split-circle factor included.
  * Bug fix: DT strings generated by the explorer now use canonical tuple
    syntax for one-crossing components, e.g. `DT: [(4,), (2,)]`, so SnapPy can
    read them for Jones calculations.
  * strand_passage_guiV3_4.py now accepts `--crossing-order` and
    `--crossing-map`, and the interactive GUI exposes matching fields. These
    options use the same syntax as draw_dt_original_labelsV3_11.py and affect
    the displayed crossing IDs without changing the internal passage engine.
  * Bug fix: each --nongui pass now first normalizes its source DT code to the
    same simplified representative used for that pass's crossing-count
    baseline. This prevents second-pass rows from flipping crossings on an
    unreduced parent while comparing against a lower-crossing parent baseline,
    which could previously produce an invalid `increase` outcome.


What is new in V3.3 (backtrack-assisted simplification)
------------------------------------------------------
SnapPy's simplify('global') is a greedy heuristic and can stop at a NON-minimal
diagram (a real example we hit: a 4-component link whose minimum is 10 crossings
was reported as 12 by simplify('global'); backtracking down to 10 confirmed the
minimum).  This affects every diagram the tool draws and every DT-code choice,
not just the overview merge.  V3.3 adds an OPTIONAL backtrack-assisted
simplification that repeatedly complicates the diagram, then re-simplifies, and
keeps the fewest-crossing result:

  * link_engine_v3_4.backtrack_simplify(snappy, link, mode, rounds, steps)
    is the core routine; rounds<=0 is a plain single simplify (unchanged).
  * It is threaded through the SnapPy path used by BOTH the GUI (advance ->
    snappy_global_simplification) and --nongui (every passage result and the
    original link).
  * Controls -- ON BY DEFAULT (200 rounds, 30 steps):
      CLI:  --no-backtrack to disable; --backtrack-rounds N / --backtrack-steps K
            to tune (--backtrack is kept as a no-op for compatibility).
      GUI:  the "Backtrack simplify" checkbox + "rounds"/"steps" fields in the
            top bar start ON at 200/30 and can be toggled live between clicks.
  * Cost: each round is one backtrack + one simplify, so N rounds ~ N extra
    simplifications per structure; lower the rounds if a large --nongui sweep is
    slow.
  * Because backtrack is randomised, the exact rounds needed vary run to run.

The standalone check_two_dt.py utility demonstrates the effect (plain loop vs.
backtrack, and reports the round at which a lower crossing count is reached).


Overview SVG refinements (V3.3)
-------------------------------
  * Targeted per-step reconciliation (reconcile_steps): within a step, any
    structures that share the same Jones (up to mirror q->1/q and framing q^n)
    and component count but show DIFFERENT crossing counts are the same link left
    at different simplify('global') plateaus.  The higher-crossing ones are
    driven DOWN to the step's minimum with a *targeted* backtrack (it stops the
    moment it reaches that count -- far cheaper than a big global round count),
    then the now-identical structures are merged and their arrows combined.  This
    removes the redundant near-duplicate cards.
  * Structures are deduplicated WITHIN each step only, never across steps.
  * All cards share one fixed size; each column is centred vertically so the
    figure is symmetric.  Diagrams are enlarged (bigger artboard) so DT and
    crossing labels are not crowded; the small filled component-colour dots were
    removed.  Card text (DT / crossings+components / Jones) is blank-line
    separated and set in a larger font.
  * Each arrow has its own colour; its label (the flipped DT crossing) is drawn
    in that colour and placed ON its own arrow (spread along the arc so labels
    never stack), and long labels are wrapped so they don't overrun the panels.
  * Illustrator-friendly export: all text is outlined to vector paths (no more
    "Font Problems" dialog about DejaVu/Computer Modern/etc.) and artist clipping
    is turned off (no more "Clipping will be lost on roundtrip to Tiny").


What changed from V3.1 (the five requested items)
-------------------------------------------------
1. Drawing helper is now draw_dt_original_labelsV3_11.py, imported through
   link_engine_v3_4.py.  The strand-passage views draw 2-D links with the
   helper's OWN default settings: default layout (DEFAULT_LAYOUT = "tutte"),
   top-to-bottom orientation, and the helper's false-crossing audit with a
   planar fallback.  Those defaults now live in one place
   (draw_dt_original_labelsV3_11.DEFAULT_LAYOUT / DEFAULT_Y_DIRECTION /
   DEFAULT_ROTATE) so the engine and the standalone helper stay in sync.

2. --nongui reproduces the old two-pass spreadsheet (sheet "first_pass" plus one
   sheet per first-flip crossing) using SnapPy directly.  DT-code choice rule:
   after a passage, if the DIRECT after-passage DT code has MORE crossings than
   the SnapPy simplify('global') code, the SnapPy-simplified code is used;
   otherwise (fewer-or-equal, i.e. a tie) the direct after-passage code is kept.
   New columns record both codes, the chosen code, the chosen source, and the
   direct / SnapPy / chosen crossing counts.  The second pass continues from the
   CHOSEN code.

3. The same DT-choice rule drives the interactive GUI (advance()).  DT traversal
   labels stay visible in the view even after a SnapPy simplification, because
   the chosen diagram is always built from its own DT code and carries a
   _dt_labels_valid flag; render() shows labels for any such pristine drawing
   (original, direct after-passage, or SnapPy-simplified) and hides them the
   moment the drawing is further passage-changed or reduced.

4. The mouse cursor becomes a pointing hand ("hand2") whenever it is near a
   crossing where a strand passage can be performed (same hit radius as the
   click test), in both the TkAgg and the Agg-in-Tk backends.

5. SVG-vs-live-view difference (diagnosed and FIXED in V3.10):
   * Cause: the knot geometry (deterministic Tutte layout) is IDENTICAL in both
     the live GUI preview and the saved file.  The visible difference was purely
     framing.  The live preview reframes the diagram to the wide Tk canvas
     aspect ratio and applies the interactive zoom (_apply_preview_zoom), while
     the saved image was written from a SQUARE figure cropped with
     bbox_inches='tight'.  Different aspect + zoom + crop margins made the two
     look different even though the drawing was the same.
   * Fix: a single shared routine, apply_content_framing(), now frames both the
     live preview AND the file save with the same content bounds, padding,
     preview zoom, and panel aspect ratio.  draw()/save_image()/save_all() take
     match_view={"aspect", "zoom"} and write the whole figure (no tight crop),
     so the saved SVG reproduces exactly what is on screen.  (The plain CLI
     pipeline keeps its legacy square/tight output, since it has no live view to
     match.)
   GUI layout was also optimised: a resizable diagram/properties split, a
   scrollable properties panel, a hint bar, a larger diagram, and Save PNG / Save
   SVG buttons that save exactly the on-screen view.

Earlier live files are kept only in the local maintenance archive and are not
part of the public GitHub package.


V3.2 refinements (second round)
-------------------------------
a. The strand-passage 2-D views now apply the helper's full default look,
   including crossing IDs coloured by the over-strand's component colour
   (link_engine_v3_2 tags each crossing with its odd/even visit and passes
   color_crossing_ids_by_overstrand=True).
b. draw_dt_original_labelsV3_11: the GUI window title reads "V3_11",
   and the final XYZ smoothing defaults changed to smooth window = 10 and smooth
   passes = 5 (argparse, GUI fields, and function defaults).
c. The pointing-hand cursor now uses an ADAPTIVE radius (just under half the
   nearest-crossing gap, capped small), so it only appears when the cursor is
   genuinely on a crossing instead of far away.
d. Running under plain python (not `sage -python`) prints a warning that Jones
   polynomials -- and the SnapPy colour-matching that relies on them -- cannot
   be computed, and suggests Sage.
e. --nongui now also writes <name>_overview.svg: one large figure of every
   resulting structure across the two passage steps.  Three columns (original /
   after 1 passage / after 2 passages), colour-coded cards (green = fewer
   crossings than the original, gray = same, orange = more, gold = unknot/
   unlink), each card showing the helper-default 2-D view, DT code, crossing and
   component counts, Jones polynomial, a component colour key, an outcome tag,
   and a badge when several passages merge into it.  Curved arrows labelled with
   the flipped DT crossing show the operation order.  Cards never overlap and the
   diagrams are drawn on top of the arrows so nothing is hidden.

   Merging rule: two structures are treated as the SAME card when they share the
   SnapPy-simplified crossing count, the component count, and the Jones
   polynomial UP TO (a) the mirror symmetry q -> 1/q and (b) an overall monomial
   factor q^n.  The mirror image of a link has Jones V(1/q), so a chiral link and
   its mirror merge; an overall q^n factor is only a framing/writhe (Reidemeister
   I) normalization artifact, so those merge too.  The crossing/component/Jones
   values shown
   on each card are exactly the values written to the spreadsheet (the overview
   reuses them rather than recomputing), so the two outputs always agree -- this
   also fixes the earlier case where the overview showed "n/a" Jones for
   structures that had a Jones value in the spreadsheet.


Colour tracking (unchanged from V3.1)
-------------------------------------
When SnapPy's simplified diagram is chosen, component colours are recovered by
matching the linking matrix + per-component Jones signatures over all component
permutations and orientation reversals.  A unique match => original colours are
kept and the log says "colours tracked".  If the outcome has topologically
interchangeable components (e.g. two split unknots after unlinking a Hopf link)
no invariant can label them; the diagram is still shown in default colours and
the log says "COLOURS NOT TRACKED" with the reason.  colours_tracked propagates
to all descendants.


Dependencies / testing notes
----------------------------
* Python 3 with numpy, networkx, matplotlib; tkinter for the GUI.
* SnapPy is optional but is the intended path -- run under `sage -python`.
* --nongui additionally needs pandas + openpyxl (.xlsx writer) and matplotlib
  (overview SVG).
* In environments WITHOUT networkx / SnapPy / pandas:
    - all scripts were syntax-checked (py_compile) and pass;
    - the --nongui DT-choice logic was unit-tested with a mock SnapPy (tie keeps
      the direct code; strictly-fewer crossings picks the SnapPy code);
    - the _dt_labels_valid flag and apply_content_framing() math were unit-tested;
    - the engine block-model odd/even + over-strand colouring was unit-tested;
    - the adaptive cursor radius and the Sage warning were unit-tested;
    - the overview-SVG layout/arrows/merge/badge rendering was exercised with a
      stubbed engine + mock SnapPy and produced a clean, non-overlapping figure.
  A live `sage -python` smoke test on your machine remains the first
  confirmation step: the GUI + SnapPy path (chained multi-window passages,
  colour-tracking messages, Save PNG/SVG matching the view) and a real --nongui
  run (spreadsheet + overview SVG on your 14-crossing 4-component link).
