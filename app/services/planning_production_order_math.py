from __future__ import annotations


def _ceil_to_int(value: float) -> int:
    as_int = int(value)
    if value > as_int:
        return as_int + 1
    return as_int


def _normalize_weights(size_ids: list[int], raw_weights: dict[int, float]) -> dict[int, float]:
    if not size_ids:
        return {}

    weights: dict[int, float] = {}
    for size_id in size_ids:
        weight = raw_weights.get(size_id)
        if weight is not None and weight > 0:
            weights[size_id] = float(weight)

    if not weights:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    total = sum(weights.values())
    if total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    normalized = {size_id: weight / total for size_id, weight in weights.items()}

    for size_id in size_ids:
        normalized.setdefault(size_id, 0.0)

    norm_total = sum(normalized.values())
    if norm_total <= 0:
        uniform = 1.0 / len(size_ids)
        return {size_id: uniform for size_id in size_ids}

    return {size_id: normalized[size_id] / norm_total for size_id in size_ids}


def _allocate_units(total_units: int, weights: dict[int, float]) -> dict[int, int]:
    if total_units <= 0 or not weights:
        return {key: 0 for key in weights}

    keys = sorted(weights.keys())
    raw_values: dict[int, float] = {
        key: float(total_units) * max(weights.get(key, 0.0), 0.0) for key in keys
    }

    allocated: dict[int, int] = {key: int(raw_values[key]) for key in keys}
    assigned = sum(allocated.values())
    remainder = max(total_units - assigned, 0)

    if remainder > 0:
        remainders = sorted(
            keys,
            key=lambda key: (raw_values[key] - allocated[key], -key),
            reverse=True,
        )
        for index in range(remainder):
            allocated[remainders[index % len(remainders)]] += 1

    return allocated


def _add_units_for_color(
    line_qty: dict[tuple[int, int], int],
    color_id: int,
    additional_qty: int,
    color_to_sizes: dict[int, list[int]],
    global_size_weights: dict[int, float],
) -> None:
    if additional_qty <= 0:
        return

    sizes = color_to_sizes.get(color_id, [])
    if not sizes:
        return

    local_weights = _normalize_weights(sizes, global_size_weights)
    allocated = _allocate_units(additional_qty, local_weights)

    for size_id, qty in allocated.items():
        if qty <= 0:
            continue
        key = (color_id, size_id)
        line_qty[key] = line_qty.get(key, 0) + qty
