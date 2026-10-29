"""Swiggy tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.swiggy_connection import SwiggyMcpOperation
from agent.plugins.swiggy_connection import SwiggyError, LABELS, split_tool, swiggy_service, tool_name
from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools, digest, provider_result


def payload(result):
    value = provider_result(result, SwiggyError)
    for _ in range(3):
        if not isinstance(value, dict) or not isinstance(value.get('data'), dict):
            break
        value = value['data']
    return value if isinstance(value, dict) else {}


class SwiggyMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or swiggy_service(), runtime)

    def route(self, operation):
        return split_tool(operation.tool_name)

    def cart(self, operation):
        service, name = self.route(operation)
        if name not in {'place_food_order', 'checkout'}:
            return None
        address = operation.arguments.get('addressId')
        if not isinstance(address, str) or not address:
            raise SwiggyError('Select the delivery address before reviewing an order.')
        read_name = 'get_food_cart' if service == 'food' else 'get_cart'
        args = {'addressId': address} if service == 'food' else {}
        result = payload(self.read(SwiggyMcpOperation(tool_name=service + '__' + read_name, arguments=args)))
        pricing = result.get('pricing') or {}
        amount = pricing.get('to_pay') if service == 'food' else result.get('cartTotalAmount')
        items = result.get('items') or result.get('cartItems')
        selected = result.get('selectedAddressDetails') or {}
        destination = result.get('selectedAddress') or selected.get('id')
        if service == 'instamart' and destination != address:
            raise SwiggyError('The Instamart cart delivery address changed. Select the address and review again.')
        if amount is None or not isinstance(items, list) or not items:
            raise SwiggyError('A current priced cart is required before placing this order. Read the cart first.')
        methods = result.get('availablePaymentMethods') or []
        method = operation.arguments.get('paymentMethod')
        if not method:
            raise SwiggyError('Choose an available payment method before reviewing the order.')
        if methods and str(method).casefold() not in {str(value).casefold() for value in methods}:
            raise SwiggyError('The chosen payment method is not available for this cart.')
        return {'service': service, 'addressId': address, 'amount': amount,
            'items': items, 'paymentMethod': method, 'delivery': selected.get('address') or address}

    def prepare(self, operation):
        cart = self.cart(operation)
        binding = super().prepare(operation)
        service, _name = self.route(operation)
        binding['preview']['provider'] = LABELS[service]
        binding['preview']['description_note'] = 'Review the service, delivery destination, current charges and payment choice. A payment request is not a confirmed order.'
        if cart:
            binding['cart_digest'] = digest(cart)
            binding['preview']['fields'].extend([
                {'label': 'Delivery', 'value': str(cart['delivery'])},
                {'label': 'Current cart total (INR)', 'value': str(cart['amount'])},
                {'label': 'Cart items', 'value': str(cart['items'])},
                {'label': 'Payment', 'value': cart['paymentMethod']}])
            binding['preview']['confirm_label'] = 'Place ' + LABELS[service] + ' order'
        return binding

    def execute(self, operation, *, binding=None, confirmed=False):
        if not confirmed or not binding:
            raise SwiggyError('Review and confirm this exact Swiggy operation first.')
        if binding.get('cart_digest') and digest(self.cart(operation)) != binding['cart_digest']:
            raise SwiggyError('The cart, charges or destination changed. Review a fresh order summary.')
        result = super().execute(operation, binding=binding, confirmed=confirmed)
        _service, name = self.route(operation)
        if name in {'place_food_order', 'checkout', 'confirm_order'}:
            data = payload(result['result'])
            state = str(data.get('status', '')).upper()
            complete = state in {'CONFIRMED', 'PLACED', 'COMPLETED', 'SUCCESS'} and bool(data.get('orderId') or data.get('order_id'))
            result.update(pending=not complete,
                _message='Swiggy confirmed this order. Use its returned order ID to track delivery.' if complete else
                    'Swiggy returned an order/payment result. Check each payment and order status before claiming success; do not repeat checkout.')
        return result


def agent_tools():
    return deferred_tools(swiggy_service, SwiggyMcpOperation, tool_name, adapter_factory=SwiggyMcpAdapter)
