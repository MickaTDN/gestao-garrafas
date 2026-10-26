"""Human quantities shared by review pages and newly generated PDFs."""


def _parts(boxes, units):
    parts = []
    if boxes:
        parts.append(f"{boxes} {'caixa' if boxes == 1 else 'caixas'}")
    if units:
        parts.append(f"{units} {'garrafa' if units == 1 else 'garrafas'}")
    return " + ".join(parts) or "0 garrafas"


def stock_quantity(quantity, capacity=None):
    if quantity is None:
        return "—"
    if not capacity:
        return _parts(0, quantity)
    return _parts(*divmod(quantity, capacity))


def entered_quantity(boxes, units, quantity, capacity=None):
    # The entered breakdown is historical information, not a normalized box count.
    if boxes is not None or units is not None:
        return _parts(boxes or 0, units or 0)
    return stock_quantity(abs(quantity), capacity)
