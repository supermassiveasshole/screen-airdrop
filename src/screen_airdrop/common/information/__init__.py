"""Common information-layer package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.information.identities import (
        UnitIdentity,
        systematic_unit_identity,
    )
    from screen_airdrop.common.information.units import (
        SystematicUnit,
        TransmissionUnit,
        UnitType,
    )

__all__ = [
    "SystematicUnit",
    "TransmissionUnit",
    "UnitIdentity",
    "UnitType",
    "systematic_unit_identity",
]


def __getattr__(name):
    if name in {"UnitIdentity", "systematic_unit_identity"}:
        from screen_airdrop.common.information import identities as _identities

        return getattr(_identities, name)
    if name in {"SystematicUnit", "TransmissionUnit", "UnitType"}:
        from screen_airdrop.common.information import units as _units

        return getattr(_units, name)
    raise AttributeError(name)
