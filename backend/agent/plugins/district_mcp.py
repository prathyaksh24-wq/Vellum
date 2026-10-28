"""District tools use shared discovery, approvals and App Action reviews."""
from agent.contracts.district_connection import DistrictMcpOperation
from agent.plugins.district_connection import district_service, tool_name
import re

from agent.plugins.web_mcp_actions import WebMcpAdapter, deferred_tools, provider_result


class DistrictMcpAdapter(WebMcpAdapter):
    def __init__(self, service=None, runtime=None):
        super().__init__(service or district_service(), runtime)

    def execute(self, operation, *, binding=None, confirmed=False):
        result = super().execute(operation, binding=binding, confirmed=confirmed)
        value = provider_result(result['result'], self.service.error_type)
        # A tool returning does not establish payment or order completion.
        # Preserve the provider output and require an explicit final state/id.
        if re.search(r'order|payment|checkout|booking|reservation|purchase|(?:^|_)pay(?:_|$)', operation.tool_name, re.I):
            for _ in range(3):
                if isinstance(value, dict) and isinstance(value.get('data'), dict):
                    value = value['data']
                else:
                    break
            state = str(value.get('status', '')).upper() if isinstance(value, dict) else ''
            complete = isinstance(value, dict) and state in {'CONFIRMED', 'PLACED', 'COMPLETED', 'SUCCESS'} and bool(value.get('booking_id') or value.get('bookingId') or value.get('order_id') or value.get('orderId'))
            result.update(pending=not complete,
                _message='District confirmed this booking/order. Use its returned identifier to check the details.' if complete else
                    'District returned a booking/order/payment result. Verify its final status before reporting completion; do not repeat the change.')
        return result


def agent_tools():
    return deferred_tools(district_service, DistrictMcpOperation, tool_name, adapter_factory=DistrictMcpAdapter)
