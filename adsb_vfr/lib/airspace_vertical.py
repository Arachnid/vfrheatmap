"""Vertical containment for OpenAIP limits (AMSL vs flight level vs AGL)."""

from __future__ import annotations


def point_in_airspace_vertically(
    pressure_alt_ft: float,
    qnh_amsl_ft: float,
    lower_ft: int | None,
    lower_ref: str,
    upper_ft: int | None,
    upper_ref: str,
) -> bool:
    """
    Return True if the point lies within the vertical band of the volume.

    - FL limits: compare to pressure altitude (1013.25 hPa), same datum as flight levels.
    - AMSL limits: compare to QNH/MSLP-derived AMSL (ft).
    - Lower AGL: no terrain model — treat as **no lower bound** (any altitude passes the lower check).
    - Upper bound is always enforced when present (for AMSL/FL refs). Upper AGL without a DEM is not
      verifiable; upper_ft with ref AGL is treated as no ceiling constraint here.
    - Other / UNKNOWN refs with a numeric limit: treat the limit as AMSL ft.
    """
    lr = (lower_ref or "UNKNOWN").upper()
    ur = (upper_ref or "UNKNOWN").upper()
    pa = float(pressure_alt_ft)
    qa = float(qnh_amsl_ft)
    if not (pa == pa and qa == qa):  # NaN check without math import
        return False

    def above_lower() -> bool:
        if lower_ft is None:
            return True
        if lr == "AGL":
            return True
        lf = float(lower_ft)
        if lr == "FL":
            return pa >= lf
        if lr == "AMSL":
            return qa >= lf
        return qa >= lf

    def below_upper() -> bool:
        if upper_ft is None:
            return True
        uf = float(upper_ft)
        if ur == "AGL":
            return True
        if ur == "FL":
            return pa <= uf
        if ur == "AMSL":
            return qa <= uf
        return qa <= uf

    return above_lower() and below_upper()
