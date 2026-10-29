"""Bounded user requests for the canonical plugin setup owner."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator
from urllib.parse import urlsplit
import re


class PluginSetup(BaseModel):
    model_config=ConfigDict(extra='forbid')
    name: str = Field(min_length=1,max_length=80)
    description: str = Field(default='',max_length=500)
    kind: Literal['create','mcp','archive'] = 'create'
    transport: Literal['http','stdio'] = 'http'
    url: str = Field(default='',max_length=1000)
    command: str = Field(default='',max_length=200)
    args: list[str] = Field(default_factory=list,max_length=40)
    env: dict[str,str] = Field(default_factory=dict,max_length=20)
    headers: dict[str,str] = Field(default_factory=dict,max_length=20)
    archive_b64: str = Field(default='',max_length=2800000)

    @model_validator(mode='after')
    def valid(self):
        if not self.name.strip() or any(ord(c)<32 for c in self.name):
            raise ValueError('Enter a plugin name.')
        if any(len(arg)>1000 or '\x00' in arg for arg in self.args):
            raise ValueError('MCP arguments are too large.')
        for key,value in [*self.env.items(),*self.headers.items()]:
            if not re.fullmatch(r'[A-Za-z_][A-Za-z0-9_-]{0,79}',key) or not re.fullmatch(r'\$\{[A-Z][A-Z0-9_]*\}',value):
                raise ValueError('Use environment variable references such as ${MY_MCP_TOKEN}; do not paste secrets.')
        if self.kind=='mcp':
            if self.transport=='http':
                url=urlsplit(self.url)
                if url.scheme not in {'https','http'} or not url.hostname or url.username or url.password or url.query or url.fragment:
                    raise ValueError('Use an MCP endpoint URL without credentials or query tokens.')
                if url.scheme=='http' and url.hostname not in {'localhost','127.0.0.1','::1'}:
                    raise ValueError('Remote MCP endpoints require HTTPS.')
            elif not self.command.strip() or any(ord(c)<32 for c in self.command):
                raise ValueError('Enter the executable and its separate argument list.')
        return self


class MarketplaceSetup(BaseModel):
    model_config=ConfigDict(extra='forbid')
    repo: str = Field(min_length=3,max_length=160)
    path: str = Field(default='skills/',max_length=200)

    @model_validator(mode='after')
    def valid(self):
        if not re.fullmatch(r'[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+',self.repo) or any(part in {'.','..'} for part in self.repo.split('/')):
            raise ValueError('Use a GitHub owner/repository name.')
        from pathlib import PurePosixPath
        path=PurePosixPath(self.path.replace('\\','/'))
        if path.is_absolute() or '..' in path.parts or ':' in self.path or '?' in self.path or '#' in self.path:
            raise ValueError('Use a relative skills directory inside the repository.')
        return self
