"""Provider status remains inspectable when the OS credential store is locked."""
import pytest

from agent.plugins import district_connection, swiggy_connection, zomato_connection


@pytest.mark.parametrize('module,service_type,status_name,factory_name', [
    (swiggy_connection, swiggy_connection.SwiggyService, 'swiggy_plugin_status', 'swiggy_service'),
    (district_connection, district_connection.DistrictService, 'district_plugin_status', 'district_service'),
    (zomato_connection, zomato_connection.ZomatoService, 'zomato_plugin_status', 'zomato_service'),
])
def test_locked_store_reports_unavailable_without_breaking_catalog(
        monkeypatch, module, service_type, status_name, factory_name):
    class LockedKeyring:
        def get_password(self, *args):
            raise RuntimeError('locked')
    def forbidden(*args, **kwargs):
        raise AssertionError('Status browsing must not open a provider session')
    service = service_type(keyring=LockedKeyring(), enabled=lambda: True,
        clock=lambda: 1000, request=forbidden, invalidator=lambda: None)
    monkeypatch.setattr(module, factory_name, lambda: service)
    status = getattr(module, status_name)()
    assert status['status'] == 'keyring_unavailable'
    assert status['configured'] is False
    assert status['metadata']['connection']['connected'] is False
    assert 'Unlock the system credential store' in status['notes']
    if module is swiggy_connection:
        assert all(not item['connected'] for item in status['metadata']['connection']['services'])
