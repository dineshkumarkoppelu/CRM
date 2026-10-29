"""The fixed rep profile table (phase-02 R2.1).

Win rates must come out EXACTLY as listed, so the generator creates exactly `closed` deals per
(rep, domain) cell and marks exactly `won` of them WON. A missing domain in `window` means the
rep has no deals at all in that domain inside the window (and no older history either).
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.core.domains import DOMAINS

AI, CYBER, IOT, DEVOPS, CLOUD = DOMAINS


@dataclass(frozen=True)
class RepProfile:
    id: str
    name: str
    region: str
    # domain -> (won, closed) inside the lookback window
    window: dict[str, tuple[int, int]]
    open_deals: int
    # Extra older history outside the window (beyond the formula), domain -> (won, closed)
    extra_older: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def email(self) -> str:
        first, last = self.name.lower().split(" ", 1)
        return f"{first}.{last.replace(' ', '')}@democrm.local"

    @property
    def window_domains(self) -> list[str]:
        """The rep's window domains in the fixed domain order (used for open-deal round-robin)."""
        return [d for d in DOMAINS if d in self.window]


Cell = tuple[int, int] | None


def _cells(
    ai: Cell = None, cyber: Cell = None, iot: Cell = None, devops: Cell = None, cloud: Cell = None
) -> dict[str, tuple[int, int]]:
    values = {AI: ai, CYBER: cyber, IOT: iot, DEVOPS: devops, CLOUD: cloud}
    return {domain: cell for domain, cell in values.items() if cell is not None}


PROFILES: tuple[RepProfile, ...] = (
    RepProfile("SP-001", "Aarav Mehta", "South",
               _cells(ai=(7, 10), iot=(8, 10), devops=(6, 10), cloud=(7, 10)), 8),
    RepProfile("SP-002", "Bhavna Rao", "South",
               _cells(ai=(7, 10), devops=(6, 10), cloud=(7, 10)), 2),
    RepProfile("SP-003", "Rohan Kulkarni", "West",
               _cells(ai=(4, 10), devops=(4, 10), cloud=(5, 10)), 5,
               # Window trap: strong Cybersecurity history, but ALL of it outside the window.
               extra_older={CYBER: (4, 5)}),
    RepProfile("SP-004", "Sneha Pillai", "South",
               _cells(ai=(5, 10), cyber=(3, 10), devops=(8, 10), cloud=(4, 10)), 5),
    RepProfile("SP-005", "Chetan Iyer", "North",
               _cells(cyber=(9, 10), devops=(5, 10), cloud=(6, 10)), 8),
    RepProfile("SP-006", "Divya Nair", "North",
               _cells(cyber=(7, 10), devops=(5, 10), cloud=(6, 10)), 4),
    RepProfile("SP-007", "Imran Qureshi", "North",
               _cells(cyber=(6, 10), devops=(4, 10), cloud=(4, 10)), 6),
    RepProfile("SP-008", "Kavya Reddy", "East",
               _cells(ai=(3, 10), cyber=(5, 10), cloud=(5, 10)), 5),
    RepProfile("SP-009", "Manoj Das", "East",
               _cells(ai=(5, 10), cyber=(4, 10), iot=(6, 10)), 7),
    RepProfile("SP-010", "Neha Kapoor", "West",
               _cells(ai=(4, 10), cyber=(5, 10), iot=(5, 10)), 6),
    RepProfile("SP-011", "Omkar Joshi", "West",
               _cells(ai=(6, 10), iot=(5, 10), cloud=(3, 10)), 6),
    RepProfile("SP-012", "Priya Menon", "International",
               _cells(ai=(2, 4), cyber=(1, 4), iot=(1, 4), devops=(2, 4), cloud=(1, 4)), 4),
    RepProfile("SP-013", "Rahul Verma", "International",
               _cells(ai=(1, 4), cyber=(2, 4), iot=(1, 4), devops=(1, 4), cloud=(2, 4)), 5),
    RepProfile("SP-014", "Sana Sheikh", "East",
               _cells(ai=(2, 4), cyber=(1, 4), iot=(2, 4), devops=(2, 4), cloud=(1, 4)), 4),
    RepProfile("SP-015", "Tarun Bose", "North",
               _cells(ai=(1, 4), cyber=(2, 4), iot=(1, 4), devops=(1, 4), cloud=(2, 4)), 5),
)  # fmt: skip


def older_counts(won: int, closed: int) -> tuple[int, int]:
    """(won_old, closed_old) for a window cell, using the integer half-up formulas of R2.1.

    10 closed -> 4 older with won_old = (won*4 + 5) // 10
     4 closed -> 2 older with won_old = (won*2 + 2) // 4
    """
    if closed == 10:
        return (won * 4 + 5) // 10, 4
    if closed == 4:
        return (won * 2 + 2) // 4, 2
    raise ValueError(f"No older-history rule for a cell with {closed} closed deals")


# Expected totals (R2.1) - asserted by the unit tests.
EXPECTED_WINDOW_CLOSED = 430
EXPECTED_OLDER_CLOSED = 185
EXPECTED_OPEN = 80
EXPECTED_TOTAL_DEALS = EXPECTED_WINDOW_CLOSED + EXPECTED_OLDER_CLOSED + EXPECTED_OPEN  # 695
