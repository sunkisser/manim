from __future__ import annotations

from typing import Iterable, Callable, TypeVar, Sequence

from scipy import linalg
import numpy as np
import numpy.typing as npt

from manimlib.utils.simple_functions import choose
from manimlib.utils.space_ops import find_intersection
from manimlib.utils.space_ops import cross2d
from manimlib.utils.space_ops import midpoint
from manimlib.logger import log

CLOSED_THRESHOLD = 0.001
T = TypeVar("T")

def bezier(
    points: Iterable[float | np.ndarray]
) -> Callable[[float], float | np.ndarray]:
    n = len(points) - 1

    def result(t):
        return sum(
            ((1 - t)**(n - k)) * (t**k) * choose(n, k) * point
            for k, point in enumerate(points)
        )

    return result


def partial_bezier_points(
    points: Sequence[np.ndarray],
    a: float,
    b: float
) -> list[float]:
    """
    Given an list of points which define
    a bezier curve, and two numbers 0<=a<b<=1,
    return an list of the same size, which
    describes the portion of the original bezier
    curve on the interval [a, b].

    This algorithm is pretty nifty, and pretty dense.
    """
    if a == 1:
        return [points[-1]] * len(points)

    a_to_1 = [
        bezier(points[i:])(a)
        for i in range(len(points))
    ]
    end_prop = (b - a) / (1. - a)
    return [
        bezier(a_to_1[:i + 1])(end_prop)
        for i in range(len(points))
    ]


# Shortened version of partial_bezier_points just for quadratics,
# since this is called a fair amount
def partial_quadratic_bezier_points(
    points: Sequence[np.ndarray],
    a: float,
    b: float
) -> list[float]:
    if a == 1:
        return 3 * [points[-1]]

    def curve(t):
        return points[0] * (1 - t) * (1 - t) + 2 * points[1] * t * (1 - t) + points[2] * t * t
    # bezier(points)
    h0 = curve(a) if a > 0 else points[0]
    h2 = curve(b) if b < 1 else points[2]
    h1_prime = (1 - a) * points[1] + a * points[2]
    end_prop = (b - a) / (1. - a)
    h1 = (1 - end_prop) * h0 + end_prop * h1_prime
    return [h0, h1, h2]


# Linear interpolation variants

def interpolate(start: T, end: T, alpha: float) -> T:
    try:
        if isinstance(alpha, float):
            return (1 - alpha) * start + alpha * end
        # Otherwise, assume alpha is a list or array, and return
        # an appropriated shaped array of all corresponding
        # interpolations
        result = np.outer(1 - alpha, start) + np.outer(alpha, end)
        return result.reshape((*np.shape(alpha), *np.shape(start)))
    except TypeError:
        log.debug(f"`start` parameter with type `{type(start)}` and dtype `{start.dtype}`")
        log.debug(f"`end` parameter with type `{type(end)}` and dtype `{end.dtype}`")
        log.debug(f"`alpha` parameter with value `{alpha}`")
        import sys
        sys.exit(2)


def set_array_by_interpolation(
    arr: np.ndarray,
    arr1: np.ndarray,
    arr2: np.ndarray,
    alpha: float,
    interp_func: Callable[[np.ndarray, np.ndarray, float], np.ndarray] = interpolate
) -> np.ndarray:
    arr[:] = interp_func(arr1, arr2, alpha)
    return arr


def integer_interpolate(
    start: T,
    end: T,
    alpha: float
) -> tuple[int, float]:
    """
    alpha is a float between 0 and 1.  This returns
    an integer between start and end (inclusive) representing
    appropriate interpolation between them, along with a
    "residue" representing a new proportion between the
    returned integer and the next one of the
    list.

    For example, if start=0, end=10, alpha=0.46, This
    would return (4, 0.6).
    """
    if alpha >= 1:
        return (end - 1, 1.0)
    if alpha <= 0:
        return (start, 0)
    value = int(interpolate(start, end, alpha))
    residue = ((end - start) * alpha) % 1
    return (value, residue)


def mid(start: T, end: T) -> T:
    return (start + end) / 2.0


def inverse_interpolate(start: T, end: T, value: T) -> float:
    return np.true_divide(value - start, end - start)


def match_interpolate(
    new_start: T, 
    new_end: T, 
    old_start: T, 
    old_end: T, 
    old_value: T
) -> T:
    return interpolate(
        new_start, new_end,
        inverse_interpolate(old_start, old_end, old_value)
    )


def get_smooth_quadratic_bezier_handle_points(
    points: Sequence[np.ndarray]
) -> np.ndarray | list[np.ndarray]:
    """
    Figuring out which bezier curves most smoothly connect a sequence of points.

    Given three successive points, P0, P1 and P2, you can compute that by defining
    h = (1/4) P0 + P1 - (1/4)P2, the bezier curve defined by (P0, h, P1) will pass
    through the point P2.

    So for a given set of four successive points, P0, P1, P2, P3, if we want to add
    a handle point h between P1 and P2 so that the quadratic bezier (P1, h, P2) is
    part of a smooth curve passing through all four points, we calculate one solution
    for h that would produce a parbola passing through P3, call it smooth_to_right, and
    another that would produce a parabola passing through P0, call it smooth_to_left,
    and use the midpoint between the two.
    """
    if len(points) == 2:
        return midpoint(*points)
    smooth_to_right, smooth_to_left = [
        0.25 * ps[0:-2] + ps[1:-1] - 0.25 * ps[2:]
        for ps in (points, points[::-1])
    ]
    if np.isclose(points[0], points[-1]).all():
        last_str = 0.25 * points[-2] + points[-1] - 0.25 * points[1]
        last_stl = 0.25 * points[1] + points[0] - 0.25 * points[-2]
    else:
        last_str = smooth_to_left[0]
        last_stl = smooth_to_right[0]
    handles = 0.5 * np.vstack([smooth_to_right, [last_str]])
    handles += 0.5 * np.vstack([last_stl, smooth_to_left[::-1]])
    return handles


def get_smooth_cubic_bezier_handle_points(
    points: npt.ArrayLike
) -> tuple[np.ndarray, np.ndarray]:
    points = np.array(points)
    num_handles = len(points) - 1
    dim = points.shape[1]
    if num_handles < 1:
        return np.zeros((0, dim)), np.zeros((0, dim))
    # Must solve 2*num_handles equations to get the handles.
    # l and u are the number of lower an upper diagonal rows
    # in the matrix to solve.
    l, u = 2, 1
    # diag is a representation of the matrix in diagonal form
    # See https://www.particleincell.com/2012/bezier-splines/
    # for how to arrive at these equations
    diag = np.zeros((l + u + 1, 2 * num_handles))
    diag[0, 1::2] = -1
    diag[0, 2::2] = 1
    diag[1, 0::2] = 2
    diag[1, 1::2] = 1
    diag[2, 1:-2:2] = -2
    diag[3, 0:-3:2] = 1
    # last
    diag[2, -2] = -1
    diag[1, -1] = 2
    # This is the b as in Ax = b, where we are solving for x,
    # and A is represented using diag.  However, think of entries
    # to x and b as being points in space, not numbers
    b = np.zeros((2 * num_handles, dim))
    b[1::2] = 2 * points[1:]
    b[0] = points[0]
    b[-1] = points[-1]

    def solve_func(b):
        return linalg.solve_banded((l, u), diag, b)

    use_closed_solve_function = is_closed(points)
    if use_closed_solve_function:
        # Get equations to relate first and last points
        matrix = diag_to_matrix((l, u), diag)
        # last row handles second derivative
        matrix[-1, [0, 1, -2, -1]] = [2, -1, 1, -2]
        # first row handles first derivative
        matrix[0, :] = np.zeros(matrix.shape[1])
        matrix[0, [0, -1]] = [1, 1]
        b[0] = 2 * points[0]
        b[-1] = np.zeros(dim)

        def closed_curve_solve_func(b):
            return linalg.solve(matrix, b)

    handle_pairs = np.zeros((2 * num_handles, dim))
    for i in range(dim):
        if use_closed_solve_function:
            handle_pairs[:, i] = closed_curve_solve_func(b[:, i])
        else:
            handle_pairs[:, i] = solve_func(b[:, i])
    return handle_pairs[0::2], handle_pairs[1::2]


def diag_to_matrix(
    l_and_u: tuple[int, int], 
    diag: np.ndarray
) -> np.ndarray:
    """
    Converts array whose rows represent diagonal
    entries of a matrix into the matrix itself.
    See scipy.linalg.solve_banded
    """
    l, u = l_and_u
    dim = diag.shape[1]
    matrix = np.zeros((dim, dim))
    for i in range(l + u + 1):
        np.fill_diagonal(
            matrix[max(0, i - u):, max(0, u - i):],
            diag[i, max(0, u - i):]
        )
    return matrix


def is_closed(points: Sequence[np.ndarray]) -> bool:
    return np.allclose(points[0], points[-1])


# Given 4 control points for a cubic bezier curve (or arrays of such)
# return control points for 2 quadratics (or 2n quadratics) approximating them.
def get_quadratic_approximation_of_cubic(
    a0: npt.ArrayLike,
    h0: npt.ArrayLike,
    h1: npt.ArrayLike,
    a1: npt.ArrayLike
) -> np.ndarray:
    a0 = np.array(a0, ndmin=2)
    h0 = np.array(h0, ndmin=2)
    h1 = np.array(h1, ndmin=2)
    a1 = np.array(a1, ndmin=2)
    # Tangent vectors at the start and end.
    T0 = h0 - a0
    T1 = a1 - h1

    # Search for inflection points.  If none are found, use the
    # midpoint as a cut point.
    # Based on http://www.caffeineowl.com/graphics/2d/vectorial/cubic-inflexion.html
    has_infl = np.ones(len(a0), dtype=bool)

    p = h0 - a0
    q = h1 - 2 * h0 + a0
    r = a1 - 3 * h1 + 3 * h0 - a0

    a = cross2d(q, r)
    b = cross2d(p, r)
    c = cross2d(p, q)

    disc = b * b - 4 * a * c
    has_infl &= (disc > 0)
    sqrt_disc = np.sqrt(np.abs(disc))
    settings = np.seterr(all='ignore')
    ti_bounds = []
    for sgn in [-1, +1]:
        ti = (-b + sgn * sqrt_disc) / (2 * a)
        ti[a == 0] = (-c / b)[a == 0]
        ti[(a == 0) & (b == 0)] = 0
        ti_bounds.append(ti)
    ti_min, ti_max = ti_bounds
    np.seterr(**settings)
    ti_min_in_range = has_infl & (0 < ti_min) & (ti_min < 1)
    ti_max_in_range = has_infl & (0 < ti_max) & (ti_max < 1)

    # Choose a value of t which starts at 0.5,
    # but is updated to one of the inflection points
    # if they lie between 0 and 1

    t_mid = 0.5 * np.ones(len(a0))
    t_mid[ti_min_in_range] = ti_min[ti_min_in_range]
    t_mid[ti_max_in_range] = ti_max[ti_max_in_range]

    m, n = a0.shape
    t_mid = t_mid.repeat(n).reshape((m, n))

    # Compute bezier point and tangent at the chosen value of t
    mid = bezier([a0, h0, h1, a1])(t_mid)
    Tm = bezier([h0 - a0, h1 - h0, a1 - h1])(t_mid)

    # Intersection between tangent lines at end points
    # and tangent in the middle
    i0 = find_intersection(a0, T0, mid, Tm)
    i1 = find_intersection(a1, T1, mid, Tm)

    m, n = np.shape(a0)
    result = np.zeros((6 * m, n))
    result[0::6] = a0
    result[1::6] = i0
    result[2::6] = mid
    result[3::6] = mid
    result[4::6] = i1
    result[5::6] = a1
    return result


def get_smooth_quadratic_bezier_path_through(
    points: list[np.ndarray]
) -> np.ndarray:
    # TODO
    h0, h1 = get_smooth_cubic_bezier_handle_points(points)
    a0 = points[:-1]
    a1 = points[1:]
    return get_quadratic_approximation_of_cubic(a0, h0, h1, a1)
