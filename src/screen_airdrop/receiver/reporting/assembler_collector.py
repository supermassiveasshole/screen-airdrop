"""Assembler state collector for extracting chunk assembly information."""

from typing import Any, Dict

from screen_airdrop.receiver.reporting.collector import Collector


class AssemblerCollector(Collector):
    """Collects assembler state (missing chunks, control plane).

    This collector wraps a ChunkAssembler object and extracts:
    - Missing chunk information
    - Control plane data (session, layout, generation)
    - Generation tracking
    """

    def __init__(self, assembler):
        """Initialize assembler collector.

        Args:
            assembler: ChunkAssembler instance
        """
        self._assembler = assembler

    def collect(self) -> Dict[str, Any]:
        """Collect assembler state.

        Returns:
            Dictionary containing:
            - missing_chunk_count: Number of missing chunks
            - missing_chunk_ids: List of missing chunk IDs (limited to 32)
            - control_plane_kinds: List of control plane item types
            - control_session: Session information (if available)
            - control_layout: Layout information (if available)
            - control_generation: Generation information (if available)
            - control_generations_seen: List of generation IDs seen
        """
        data: Dict[str, Any] = {}

        # Missing chunks
        missing = self._assembler.missing_chunk_ids(limit=32)
        if missing is not None:
            data["missing_chunk_count"] = len(missing)
            data["missing_chunk_ids"] = sorted(missing)
            data["missing_chunks"] = len(missing)  # Backward compatibility alias
        else:
            data["missing_chunk_count"] = 0
            data["missing_chunk_ids"] = []
            data["missing_chunks"] = 0  # Backward compatibility alias

        # Control plane
        data["control_plane_kinds"] = sorted(
            list(self._assembler.control_items.keys())
        )

        if self._assembler.session_info is not None:
            data["control_session"] = dict(self._assembler.session_info)

        if self._assembler.layout_info is not None:
            data["control_layout"] = dict(self._assembler.layout_info)

        if self._assembler.generation_info is not None:
            data["control_generation"] = dict(self._assembler.generation_info)

        coded_schemes = [
            str(info.get("coded_payload_envelope", "") or "")
            for info in self._assembler.generations.values()
            if str(info.get("coded_payload_envelope", "") or "")
        ]
        data["coded_scheme"] = coded_schemes[0] if coded_schemes else ""

        data["control_generations_seen"] = sorted(
            int(k) for k in self._assembler.generations.keys()
        )

        states = list(self._assembler.generation_store.generations.values())
        data["coded_units_seen"] = sum(int(state.coded_equation_count) for state in states)
        data["coded_units_duplicate"] = sum(int(state.duplicate_equation_count) for state in states)
        data["coded_units_invalid"] = int(self._assembler.invalid_coded_payload_count) + sum(
            int(state.invalid_equation_count) for state in states
        )
        data["coded_units_conflicting"] = sum(int(state.conflict_count) for state in states)
        data["coded_units_dependent"] = sum(int(state.dependent_equation_count) for state in states)
        data["solver_rank_peak"] = max([0] + [int(state.solver_rank) for state in states])
        data["recovered_source_symbols"] = sum(int(state.recovered_source_count) for state in states)
        if not data["coded_scheme"] and int(data["coded_units_seen"]) > 0:
            data["coded_scheme"] = "gf256_seed_v2"

        return data

    def reset(self) -> None:
        """Reset collector state.

        Assembler state is not reset during runtime, so this is a no-op.
        """
        pass
