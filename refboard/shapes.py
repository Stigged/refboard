"""Shared shapes: the G2 rounded rectangle ("squircle") used by all panels."""

import math

from PySide6.QtCore import QPointF
from PySide6.QtGui import QPainterPath

# Corner shape. 2 would be an ordinary circle-like corner; higher numbers are
# "squarer" with a smoother transition. 5 is close to Apple's icon corners.
CORNER_SMOOTHNESS = 5
CORNER_STEPS = 24  # how many little line pieces make up one corner


def squircle_path(rect, radius):
    """A rectangle with G2-continuous (curvature-continuous) rounded corners.

    Each corner is a quarter of a superellipse, |x|^n + |y|^n = 1. Unlike a
    circle arc, its curvature fades to zero where it meets the straight
    edge, so there's no visible "kink" where the corner begins.
    """
    r = min(radius, rect.width() / 2, rect.height() / 2)
    # Centre of each corner's curve, clockwise from top-right.
    centres = [
        QPointF(rect.right() - r, rect.top() + r),
        QPointF(rect.right() - r, rect.bottom() - r),
        QPointF(rect.left() + r, rect.bottom() - r),
        QPointF(rect.left() + r, rect.top() + r),
    ]
    power = 2 / CORNER_SMOOTHNESS
    path = QPainterPath()
    for corner, centre in enumerate(centres):
        for step in range(CORNER_STEPS + 1):
            t = step / CORNER_STEPS * (math.pi / 2)
            # One point on the top-right quarter of a superellipse...
            x, y = math.sin(t) ** power, -(math.cos(t) ** power)
            # ...turned 90 degrees once per corner, to fit that corner.
            for _ in range(corner):
                x, y = -y, x
            point = centre + QPointF(x * r, y * r)
            if corner == 0 and step == 0:
                path.moveTo(point)
            else:
                path.lineTo(point)  # the straight edges come for free between corners
    path.closeSubpath()
    return path
