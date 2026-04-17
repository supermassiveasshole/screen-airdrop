"""Common information-layer package."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from screen_airdrop.common.information.coding import (
        CodingScheme,
        CodingSeedMetadata,
        EquationTerm,
        expand_equation_indices,
        expand_equation_terms,
        gf256_add,
        gf256_div,
        gf256_inv,
        gf256_linear_combine,
        gf256_mul,
        gf256_scale_payload,
        xor_payloads,
    )
    from screen_airdrop.common.information.identities import (
        CodedUnitIdentity,
        SystematicUnitIdentity,
        UnitIdentity,
        coded_unit_identity,
        systematic_unit_identity,
    )
    from screen_airdrop.common.information.units import (
        CodedUnit,
        SystematicUnit,
        TransmissionUnit,
        UnitType,
    )

__all__ = [
    "CodedUnit",
    "CodedUnitIdentity",
    "CodingSeedMetadata",
    "CodingScheme",
    "EquationTerm",
    "SystematicUnitIdentity",
    "SystematicUnit",
    "TransmissionUnit",
    "UnitIdentity",
    "UnitType",
    "coded_unit_identity",
    "expand_equation_indices",
    "expand_equation_terms",
    "gf256_add",
    "gf256_div",
    "gf256_inv",
    "gf256_linear_combine",
    "gf256_mul",
    "gf256_scale_payload",
    "systematic_unit_identity",
    "xor_payloads",
]


def __getattr__(name):
    if name in {
        "CodingSeedMetadata",
        "CodingScheme",
        "EquationTerm",
        "expand_equation_indices",
        "expand_equation_terms",
        "gf256_add",
        "gf256_div",
        "gf256_inv",
        "gf256_linear_combine",
        "gf256_mul",
        "gf256_scale_payload",
        "xor_payloads",
    }:
        from screen_airdrop.common.information import coding as _coding

        return getattr(_coding, name)
    if name in {
        "CodedUnitIdentity",
        "SystematicUnitIdentity",
        "UnitIdentity",
        "coded_unit_identity",
        "systematic_unit_identity",
    }:
        from screen_airdrop.common.information import identities as _identities

        return getattr(_identities, name)
    if name in {"CodedUnit", "SystematicUnit", "TransmissionUnit", "UnitType"}:
        from screen_airdrop.common.information import units as _units

        return getattr(_units, name)
    raise AttributeError(name)
