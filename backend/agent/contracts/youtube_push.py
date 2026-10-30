"""Local push-delivery status. Callback credentials never cross this contract."""
from typing import Literal
from pydantic import BaseModel, Field


class YouTubePushStatus(BaseModel):
    contract_version: int = 1
    status: str = 'endpoint_required'
    endpoint_configured: bool = False
    authorization_required: bool = False
    transport: Literal['local', 'hosted'] = 'local'
    saved_subscriptions: int = 0
    eligible_subscriptions: int = 0
    last_relay_sync_at: str = ''
    relay_retention_days: int = 0
    desired_channels: int = 0
    active_channels: int = 0
    pending_channels: int = 0
    expired_channels: int = 0
    queued_uploads: int = 0
    last_received_at: str = ''
    warnings: list[str] = Field(default_factory=list)
    coverage: str = ('Public upload events for eligible saved subscriptions and tracked creators. '
                     'Private history stays local. Delivery requires the callback receiver, tunnel, '
                     'and backend to be running; reconciliation uses bounded RSS checks.')


class RelayChannelLease(BaseModel):
    channel_id: str = Field(pattern=r'^UC[A-Za-z0-9_-]{22}$')
    lease_expires: int = Field(ge=0)


class HostedRelayStatus(BaseModel):
    contract_version: Literal[1]
    epoch: str = Field(min_length=1, max_length=128)
    revision: str = Field(max_length=128)
    desired_channels: int = Field(ge=0, le=1000)
    active_channels: int = Field(ge=0, le=1000)
    last_received_at: int = Field(ge=0)
    last_maintenance: int = Field(ge=0)
    buffered_events: int = Field(ge=0, le=20000)
    stored_bytes: int = Field(ge=0, le=67108864)
    retention_days: Literal[7]
    warnings: list[str] = Field(default_factory=list, max_length=20)
    channels: list[RelayChannelLease] = Field(max_length=1000)


class HostedRelayEvent(BaseModel):
    id: int = Field(ge=1)
    channel_id: str = Field(pattern=r'^UC[A-Za-z0-9_-]{22}$')
    body: str = Field(max_length=262144)
    received_at: int = Field(ge=0)
    bytes: int = Field(ge=0, le=262144)


class HostedRelayEvents(BaseModel):
    contract_version: Literal[1]
    epoch: str = Field(min_length=1, max_length=128)
    retention_floor: int = Field(ge=0)
    gap: bool
    events: list[HostedRelayEvent] = Field(max_length=100)
    next_after: int = Field(ge=0)
    has_more: bool


class HostedRelayAck(BaseModel):
    contract_version: Literal[1]
    epoch: str = Field(min_length=1, max_length=128)
    after: int = Field(ge=0)
    pruned: int = Field(ge=0, le=500)
