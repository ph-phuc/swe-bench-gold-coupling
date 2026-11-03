"""Wilson score interval for a binomial proportion (used for the spot-check agreement figures).

    python code/wilson.py 8 10        ->  0.4902 0.9433
"""

from __future__ import annotations

import math
import sys

Z95 = 1.959963984540054


def wilson(k: int, n: int, z: float = Z95) -> tuple[float, float]:
    """Wilson score interval for k successes out of n trials (default 95%)."""
    if n <= 0 or not 0 <= k <= n:
        raise ValueError(f"need 0 <= k <= n and n > 0, got k={k}, n={n}")
    p = k / n
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return max(0.0, centre - half), min(1.0, centre + half)


if __name__ == "__main__":
    lo, hi = wilson(int(sys.argv[1]), int(sys.argv[2]))
    print(f"{lo:.4f} {hi:.4f}")
