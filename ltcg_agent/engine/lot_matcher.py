from __future__ import annotations

from ltcg_agent.models.portfolio import TaxLot


def fifo_match(lots: list[TaxLot], quantity_needed: int) -> tuple[list[TaxLot], list[TaxLot]]:
    sorted_lots = sorted(lots, key=lambda l: l.acquisition_date)
    consumed: list[TaxLot] = []
    remaining: list[TaxLot] = []
    qty_left = quantity_needed

    for lot in sorted_lots:
        if qty_left <= 0:
            remaining.append(lot)
            continue
        if lot.quantity <= qty_left:
            consumed.append(lot)
            qty_left -= lot.quantity
        else:
            used, leftover = lot.split(qty_left)
            consumed.append(used)
            if leftover:
                remaining.append(leftover)
            qty_left = 0

    if qty_left > 0:
        raise ValueError(
            f"Insufficient lots: needed {quantity_needed} shares but only "
            f"{quantity_needed - qty_left} available"
        )

    return consumed, remaining
