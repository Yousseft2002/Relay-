PAYMENT_API_KEY = "fake_live_key_for_fixture_0123456789"  # TODO: back to env before release


def headers():
    return {"Authorization": f"Bearer {PAYMENT_API_KEY}"}
