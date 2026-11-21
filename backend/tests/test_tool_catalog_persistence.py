"""Connector sign-ins and published MCP catalogs survive restarts and stale days."""
import json

import pytest

from agent.plugins.tool_catalog import PersistedToolCatalog
from tests.test_web_mcp_connections import Keyring, connection  # noqa: F401  (fixture)


def restart(service, keyring, *, clock):
    """A new process: same OS credential store and data folder, empty memory."""
    fresh = type(service)(keyring=keyring, enabled=lambda: True, request=service.request,
                          transport=service.transport, clock=clock, invalidator=lambda: None)
    fresh.configured_credential = service.configured_credential
    return fresh


def test_catalog_and_connection_survive_a_restart_two_days_later(connection):
    connection.use_configured()
    published = connection.catalog()
    keyring = connection.keyring

    later = restart(connection, keyring, clock=lambda: 1000 + 2 * 86400)

    assert later.status().connected and later.status().status == 'ready'
    assert later.tools_revision == later.load()['revision']
    assert [tool['name'] for tool in later.cached_tools()] == [tool['name'] for tool in published]


def test_cache_holds_public_schemas_only_never_credentials_or_the_revision(connection):
    connection.use_configured()
    connection.catalog()
    text = connection._catalog_path().read_text(encoding='utf-8')
    saved = connection.load()
    assert saved['revision'] not in text and saved['access_token'] not in text
    assert json.loads(text)['tools'][0]['name']


def test_cache_from_an_older_connection_is_not_restored(connection):
    connection.use_configured()
    connection.catalog()
    outdated = connection._catalog_path().read_text(encoding='utf-8')
    keyring = connection.keyring
    connection.disconnect()
    assert not connection._catalog_path().exists()

    connection.use_configured()  # a new connection revision
    connection._catalog_path().write_text(outdated, encoding='utf-8')
    later = restart(connection, keyring, clock=lambda: 1000)
    assert later.cached_tools() == [] and later.tools_revision == ''


def test_locked_credential_store_keeps_the_cache_for_a_later_read(connection):
    connection.use_configured()
    connection.catalog()
    keyring = connection.keyring
    later = restart(connection, keyring, clock=lambda: 1000)
    real_get = keyring.get_password
    keyring.get_password = lambda *args: (_ for _ in ()).throw(RuntimeError('locked'))
    assert later.tools_revision == ''
    keyring.get_password = real_get
    assert later.tools_revision == later.load()['revision']


def test_rejected_refresh_is_not_reported_as_connected(connection):
    connection.use_configured()
    connection.save({**connection.load(), 'refresh_rejected': True})
    assert not connection.status().connected


def test_old_unsalted_cache_files_are_ignored(connection):
    import hashlib
    connection.use_configured()
    connection.catalog()
    revision = connection.load()['revision']
    legacy = {'format': 'vellum-tool-catalog-v1', 'revision_sha256': hashlib.sha256(revision.encode()).hexdigest(),
              'tools': [{'name': 'planted'}]}
    connection._catalog_path().write_text(json.dumps(legacy), encoding='utf-8')
    later = restart(connection, connection.keyring, clock=lambda: 1000)
    assert later.cached_tools() == []
