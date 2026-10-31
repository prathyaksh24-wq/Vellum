from starlette.requests import Request
from fastapi import HTTPException
import pytest
from agent.plugins.local_music_api import trusted


def request(origin,site='cross-site'):
    return Request({'type':'http','method':'POST','scheme':'http','path':'/api/music/local/files','query_string':b'',
        'server':('127.0.0.1',8000),'client':('127.0.0.1',4000),
        'headers':[(b'host',b'127.0.0.1:8000'),(b'origin',origin.encode()),(b'sec-fetch-site',site.encode()),(b'x-vellum-music',b'1')]})


def test_localhost_workspace_can_upload_to_loopback_api():
    trusted(request('http://localhost:5173'))


@pytest.mark.parametrize('origin',['https://evil.example','http://localhost:9999','http://127.0.0.1.evil.example:5173'])
def test_other_origins_are_rejected(origin):
    with pytest.raises(HTTPException) as error:trusted(request(origin))
    assert error.value.status_code==403


def test_opaque_cross_site_request_is_rejected():
    with pytest.raises(HTTPException) as error:trusted(request(''))
    assert error.value.status_code==403
