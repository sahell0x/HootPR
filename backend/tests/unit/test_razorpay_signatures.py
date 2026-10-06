import hashlib
import hmac

from app.billing.razorpay import verify_payment_signature, verify_webhook_signature


def test_payment_signature() -> None:
    sig = hmac.new(b"secret", b"order_1|pay_1", hashlib.sha256).hexdigest()
    assert verify_payment_signature("secret", "order_1", "pay_1", sig)
    assert not verify_payment_signature("secret", "order_1", "pay_2", sig)
    assert not verify_payment_signature("", "order_1", "pay_1", sig)
    assert not verify_payment_signature("secret", "order_1", "pay_1", "")


def test_webhook_signature() -> None:
    body = b'{"event":"payment.captured"}'
    sig = hmac.new(b"wh", body, hashlib.sha256).hexdigest()
    assert verify_webhook_signature("wh", body, sig)
    assert not verify_webhook_signature("wh", body, None)
    assert not verify_webhook_signature("", body, sig)
    assert not verify_webhook_signature("wh", body + b" ", sig)
