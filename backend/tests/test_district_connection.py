"""District uses its own registered OAuth client and exact catalog/approval owner."""
from types import SimpleNamespace
from urllib.parse import parse_qs,urlsplit

import pytest

from agent.contracts.district_connection import DistrictOAuthRequest, DistrictMcpOperation
from agent.plugins.district_connection import DistrictService,CALLBACK


class Keyring:
    def __init__(self): self.values={}
    def get_password(self,service,account): return self.values.get((service,account))
    def set_password(self,service,account,value): self.values[(service,account)]=value
    def delete_password(self,service,account): self.values.pop((service,account),None)


@pytest.fixture
def connection():
    calls=[]
    def request(method,url,**kwargs):
        calls.append((url,kwargs))
        if url.endswith('/register'):
            assert kwargs['json']['client_name']=='Vellum'
            assert kwargs['json']['redirect_uris']==[CALLBACK]
            assert 'scope' not in kwargs['json']
            return SimpleNamespace(status_code=200,json=lambda:{'client_id':'fixture-client','client_secret':'fixture-client-secret','token_endpoint_auth_method':'client_secret_post','redirect_uris':[CALLBACK]})
        assert url=='https://mcp-server.district.in/token'
        assert 'resource' not in kwargs['data']
        assert kwargs['data']['client_secret']=='fixture-client-secret'
        return SimpleNamespace(status_code=200,json=lambda:{'access_token':'fixture-access','refresh_token':'fixture-refresh','token_type':'Bearer','expires_in':3600})
    class Transport:
        async def list_tools(self,connector):
            assert connector.url=='https://mcp-server.district.in/mcp'
            return [{'name':name,'description':name,'input_schema':{'type':'object','properties':{}},'read_only':True}
                for name in ['search_movies','create_booking']]
    current=DistrictService(keyring=Keyring(),enabled=lambda:True,clock=lambda:1000,request=request,transport=Transport(),invalidator=lambda:None)
    current.calls=calls
    return current


def authorize(connection):
    flow=connection.start(DistrictOAuthRequest())
    connection._finish(flow.flow_id,'fixture-code')
    assert connection.flow_status(flow.flow_id).status=='connected'
    return flow


def test_own_localhost_client_pkce_without_invented_scope_or_resource(connection):
    flow=authorize(connection)
    query=parse_qs(urlsplit(flow.authorization_url).query)
    assert query['redirect_uri']==['http://localhost:8000/api/plugins/district/oauth/callback']
    assert query['code_challenge_method']==['S256']
    assert 'scope' not in query and 'resource' not in query
    assert connection.status().mcp_tool_count==2
    assert 'fixture-access' not in connection.status().model_dump_json()
    assert 'fixture-client-secret' not in flow.model_dump_json()
    assert 'fixture-client-secret' not in connection.status().model_dump_json()


def test_registration_is_reused_and_disconnect_retains_registration_only(connection):
    authorize(connection)
    before=connection.load()['revision']
    connection.disconnect()
    saved=connection.load()
    assert saved['client_id']=='fixture-client' and saved['revision']!=before
    assert saved['client_secret']=='fixture-client-secret'
    assert 'access_token' not in saved and 'refresh_token' not in saved
    connection.start(DistrictOAuthRequest())
    assert sum(url.endswith('/register') for url,_ in connection.calls)==1


def test_booking_is_reviewed_even_when_misannotated(connection):
    from agent.plugins.district_mcp import DistrictMcpAdapter
    authorize(connection)
    adapter=DistrictMcpAdapter(connection,SimpleNamespace())
    with pytest.raises(ValueError,match='review'):
        adapter.read(DistrictMcpOperation(tool_name='create_booking'))
    with pytest.raises(ValueError,match='confirm'):
        adapter.execute(DistrictMcpOperation(tool_name='create_booking'))


def test_reviewed_discovery_reads_without_hints_and_unknown_tools_stay_conservative(connection):
    class Transport:
        async def list_tools(self, connector):
            return [
                {'name': name, 'description': name, 'input_schema': {'type': 'object', 'properties': {}},
                    'read_only': name == 'create_table_reservation_booking'}
                for name in ['search_movies', 'get_table_reservation_slots', 'get_booking_details',
                    'get_new_booking_action', 'create_table_reservation_booking']
            ]
    connection.transport = Transport()
    authorize(connection)
    modes = {tool['name']: tool['read_only'] for tool in connection.cached_tools()}
    assert modes == {'search_movies': True, 'get_table_reservation_slots': True,
        'get_booking_details': True, 'get_new_booking_action': False,
        'create_table_reservation_booking': False}


def test_refresh_keeps_previous_refresh_token_when_not_rotated(connection):
    authorize(connection)
    connection.clock=lambda:4600
    connection.request=lambda *args,**kwargs:SimpleNamespace(status_code=200,json=lambda:{'access_token':'renewed-fixture','token_type':'Bearer','expires_in':7200})
    assert connection.require()['refresh_token']=='fixture-refresh'


def test_denied_replacement_keeps_previous_grant(connection):
    authorize(connection)
    saved=connection.load()
    flow=connection.start(DistrictOAuthRequest())
    state=connection.flows[flow.flow_id]['state']
    connection.callback(state,'','access_denied')
    assert connection.load()==saved
    assert connection.flow_status(flow.flow_id).status=='failed'


def test_legacy_shape_record_gets_one_complete_replacement_and_is_reused(connection):
    connection.save({'pending_registration':{'client_id':'legacy-fixture','token_endpoint_auth_method':'client_secret_post','unexpected_secret':True,'redirect_uris':[CALLBACK]}})
    authorize(connection)
    assert connection.load()['client_secret']=='fixture-client-secret'
    connection.start(DistrictOAuthRequest())
    assert sum(url.endswith('/register') for url,_ in connection.calls)==1


def test_confidential_refresh_authentication_uses_saved_secret(connection):
    authorize(connection)
    connection.clock=lambda:4600
    connection.require()
    url,kwargs=connection.calls[-1]
    assert url=='https://mcp-server.district.in/token'
    assert kwargs['data']['grant_type']=='refresh_token'
    assert kwargs['data']['client_secret']=='fixture-client-secret'
