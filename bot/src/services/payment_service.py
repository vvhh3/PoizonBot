from src.models.order import Order


class PaymentService:
    def build_payment_url(self, order: Order) -> str:
        return f"https://example.com/pay/order/{order.id}"
