"""The drawing tools' anchors and the highlight's shape (gui/static/app.js), the user, 2026-11-01:
"for the tools, lets replace the dot with an X, with an empty center, also for the highlight tool
lets expand and contract x and y from the center"."""
from __future__ import annotations

import re

from .test_frontend_guards import _function, _js


def _measure(app: str) -> str:
    """The measure overlay's template, as registered."""
    return app.split("kc.registerOverlay({\n  name: 'measure',", 1)[1].split("\n});\n", 1)[0]


def test_every_tools_anchors_are_an_x_with_an_empty_center():
    app = _js("app.js")
    marks = _function(app, "anchorMarks")
    anchor = re.search(r"const ANCHOR = \{ color: '#[0-9a-f]{6}', gap: ([\d.]+), reach: ([\d.]+), size: ([\d.]+) \};", app)
    assert anchor, "the X's measures"
    gap, reach, size = map(float, anchor.groups())
    assert 0 < gap < reach and size > 0  # four arms from the gap outwards: nothing drawn at the center
    assert "[[1, 1], [1, -1], [-1, 1], [-1, -1]]" in marks and "Math.SQRT1_2" in marks  # the diagonals
    assert "type: 'line', ignoreEvent: true" in marks  # not a figure the pointer lands on
    # the library's filled dots are kept for the pointer (they are what a drag is tested against), unseen
    dots = app.split("const ANCHOR_DOTS = ", 1)[1].split(";", 1)[0]
    for key in ("color", "borderColor", "activeColor", "activeBorderColor"):
        assert f"{key}: 'transparent'" in dots, key
    assert "radius" not in dots  # their size, the pointer's reach, stays the library's
    applied = _function(app, "applyChartType")
    assert applied.index("chart.setStyles(themeBase())") < applied.index("chart.setStyles(ANCHOR_DOTS)")  # after each theme
    # every tool with points to drag is registered again with the marks, the measure among them
    wrapped = _function(app, "withAnchorMarks")
    assert "overlay.isDrawing() ? coordinates.slice(0, -1)" in wrapped  # while drawn: the points placed
    assert "overlay.id === state.selectedOverlay || overlay.id === state.hoveredOverlay ? coordinates : []" in wrapped
    assert "if (base.needDefaultPointFigure) kc.registerOverlay(withAnchorMarks(base));" in app
    assert "TOOLS.filter(Boolean).map(([name]) => kc.getOverlayClass(name))" in app
    assert "'performEventPressedMove', 'performEventMoveForDrawing'" in app  # the templates' hooks carried over
    events = _function(app, "overlayEvents")
    assert "onMouseEnter: (e) => { state.hoveredOverlay = e.overlay.id; }" in events
    assert "onMouseLeave: (e) => { if (state.hoveredOverlay === e.overlay.id) state.hoveredOverlay = null; }" in events
    # the highlight's center mark too, in its own colour, and no dot left
    figures = _measure(app)
    assert "anchorMarks([{ x: cx, y: cy }], MID)" in figures and "type: 'circle'" not in figures
    assert 'r="1.3" fill="currentColor"' not in app  # the tool's icon: a small x at the center of its box


def test_the_highlight_grows_from_its_center():
    app = _js("app.js")
    measure = _measure(app)
    drawing = measure.split("performEventMoveForDrawing: ", 1)[1].split("\n  },\n", 1)[0]
    assert "if (currentStep !== 2 || points.length !== 2) return;" in drawing  # the second step: the pointer is a corner
    assert "highlightCenter ??= boxCenter([points[0], points[0]]);" in drawing  # the first click, kept aside
    assert "Object.assign(points[0], mirrorPoint(highlightCenter, points[1]));" in drawing  # the far corner
    dragging = measure.split("performEventPressedMove: ", 1)[1].split("\n  },\n", 1)[0]
    assert "if (!highlightCenter || points.length !== 2) return;" in dragging  # restored or pasted: its corners as they are
    assert "Object.assign(points[1 - performPointIndex], mirrorPoint(highlightCenter, points[performPointIndex]));" in dragging
    # the center is kept from the start of a corner's drag to its end, and never into another drawing
    events = _function(app, "overlayEvents")
    assert "onPressedMoveStart: (e) => { highlightCenter = e.overlay.name === 'measure' ? boxCenter(e.overlay.points) : null; }" in events
    assert "onPressedMoveEnd: () => { highlightCenter = null; saveDrawings(); }" in events
    assert "onDrawEnd: () => { highlightCenter = null;" in events
    for fn in ("startDrawing", "cancelDrawing"):
        assert "highlightCenter = null;" in _function(app, fn), fn
    # the mirror: as many bars the other side, as the chart places them, and as far in price
    mirror = _function(app, "mirrorPoint")
    assert "chart.convertToPixel({ timestamp: ts }, { paneId: 'candle_pane' }).x" in mirror
    assert "chart.convertFromPixel([{ x: 2 * cx - x(p.timestamp), y: 0 }], { paneId: 'candle_pane' })" in mirror
    assert "value: 2 * center.value - p.value" in mirror
    center = _function(app, "boxCenter")
    assert "ts: [a.timestamp, b.timestamp], value: (a.value + b.value) / 2" in center  # the drag's center: between the corners
    # start and end: the earlier corner and the later, whichever the pointer placed
    assert "const [pa, pb] = timeOrdered(overlay.points);" in measure
    assert "const [pa, pb] = timeOrdered(o.points);" in _function(app, "currentHighlight")
    assert "sort((p, q) => p.timestamp - q.timestamp)" in _function(app, "timeOrdered")
    assert "box grown from its center" in app  # the tool's tip says so
