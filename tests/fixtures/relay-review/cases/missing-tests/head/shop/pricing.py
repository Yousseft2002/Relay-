FREE_SHIPPING_THRESHOLD = 50.0


def shipping_cost(subtotal: float) -> float:
    if subtotal > FREE_SHIPPING_THRESHOLD:
        return 0.0
    return 4.99
