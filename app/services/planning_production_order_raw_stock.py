from __future__ import annotations


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


def _estimate_competition_aware_raw_bundle_stock(
    *,
    bundle_type_ids: list[int],
    recipe_colors_by_bundle: dict[int, set[int]],
    all_recipe_color_ids: list[int],
    size_ids: list[int],
    stock_by_color_size: dict[tuple[int, int], int],
    shares_by_bundle: dict[int, float],
) -> dict[int, int]:
    raw_by_bundle: dict[int, int] = {bundle_type_id: 0 for bundle_type_id in bundle_type_ids}

    color_consumers: dict[int, list[int]] = {}
    for color_id in all_recipe_color_ids:
        color_consumers[color_id] = [
            bundle_type_id
            for bundle_type_id in bundle_type_ids
            if color_id in recipe_colors_by_bundle.get(bundle_type_id, set())
        ]

    for size_id in size_ids:
        color_bundle_alloc: dict[tuple[int, int], int] = {}

        for color_id in all_recipe_color_ids:
            color_qty = max(stock_by_color_size.get((color_id, size_id), 0), 0)
            if color_qty <= 0:
                continue

            consumers = color_consumers.get(color_id, [])
            if not consumers:
                continue

            if len(consumers) == 1:
                color_bundle_alloc[(color_id, consumers[0])] = color_qty
                continue

            consumer_weights = _normalize_weights(
                consumers,
                {bundle_type_id: shares_by_bundle.get(bundle_type_id, 0.0) for bundle_type_id in consumers},
            )
            allocated = _allocate_units(color_qty, consumer_weights)
            for bundle_type_id, allocated_qty in allocated.items():
                if allocated_qty <= 0:
                    continue
                color_bundle_alloc[(color_id, bundle_type_id)] = allocated_qty

        for bundle_type_id in bundle_type_ids:
            recipe_colors = recipe_colors_by_bundle.get(bundle_type_id, set())
            if not recipe_colors:
                continue

            color_quantities = [
                color_bundle_alloc.get((color_id, bundle_type_id), 0) for color_id in recipe_colors
            ]
            if not color_quantities or any(quantity <= 0 for quantity in color_quantities):
                continue

            raw_by_bundle[bundle_type_id] += min(color_quantities)

    return raw_by_bundle
