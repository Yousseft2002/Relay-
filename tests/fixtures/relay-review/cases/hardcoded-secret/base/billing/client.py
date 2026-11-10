import os

PAYMENT_API_KEY = os.environ["PAYMENT_API_KEY"]


def headers():
    return {"Authorization": f"Bearer {PAYMENT_API_KEY}"}
