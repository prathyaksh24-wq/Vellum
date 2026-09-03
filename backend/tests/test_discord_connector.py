from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import pytest

from agent.agents.discord import DiscordAgent
from agent.agents.base import SpecialistResponse, SpecialistSource
from agent.knowledge.models import ExternalPolicy, Sensitivity
from agent.knowledge.store import KnowledgeStore
from agent.knowledge.tool_observer import KnowledgeToolObserver
from agent.plugins.portable import PortablePluginContext, load_portable_plugin
from agent.profiles import AgentCatalog
from agent.tools.capabilities.discord_service import DiscordCapabilityService
from agent.tools.discord import _external_response_json
from agent.tools.registry import CapabilityAccess, ToolInvocation, ToolPermissionError


pytestmark = pytest.mark.usefixtures("repo_root_cwd")


class FakeResponse:
    def __init__(self, payload, status_code: int = 200) -> None:
        self.payload = payload
        self.status_code = status_code

    def json(self):
        return self.payload


def discord_module():
    return load_portable_plugin(Path("plugins/connectors/discord")).module


def test_discord_manifest_registers_bot_capabilities() -> None:
    plugin = load_portable_plugin(Path("plugins/connectors/discord"))
    context = PortablePluginContext()

    plugin.register(context)

    assert plugin.manifest.capabilities == [
        "discord.account",
        "discord.guilds",
        "discord.channels",
        "discord.messages",
        "discord.send_message",
    ]
    assert context.connectors["discord"]["capabilities"] == plugin.manifest.capabilities


def test_discord_install_url_requests_only_current_bot_permissions() -> None:
    module = discord_module()

    query = parse_qs(urlparse(module.auth.bot_install_url(application_id="123456789012345678")).query)

    assert query["scope"] == ["bot"]
    assert query["permissions"] == [str((1 << 10) | (1 << 11) | (1 << 16))]


def test_discord_client_sends_bot_auth_and_bounds_message_history() -> None:
    module = discord_module()
    calls: list[dict] = []

    def request(method: str, url: str, **kwargs):
        calls.append({"method": method, "url": url, **kwargs})
        return FakeResponse([
            {
                "id": "message-1",
                "channel_id": "222222222222222222",
                "content": "Hello from Discord",
                "timestamp": "2026-09-01T10:00:00+00:00",
                "author": {"id": "user-1", "username": "Example"},
                "attachments": [],
            }
        ])

    policy = module.policy.DiscordAccessPolicy(
        allowed_guild_ids={"111111111111111111"},
        allowed_channel_ids={"222222222222222222"},
    )
    client = module.client.DiscordClient(
        bot_token="bot-secret",
        policy=policy,
        request_backend=request,
    )

    messages = client.list_messages("222222222222222222", limit=999)

    assert messages[0]["content"] == "Hello from Discord"
    assert calls[0]["params"]["limit"] == 100
    assert calls[0]["headers"]["Authorization"] == "Bot bot-secret"


def test_discord_client_fails_closed_outside_channel_allowlist() -> None:
    module = discord_module()
    client = module.client.DiscordClient(
        bot_token="bot-secret",
        policy=module.policy.DiscordAccessPolicy(
            allowed_guild_ids=set(),
            allowed_channel_ids={"222222222222222222"},
        ),
        request_backend=lambda *_args, **_kwargs: FakeResponse([]),
    )

    with pytest.raises(module.errors.DiscordPermissionError, match="not allowlisted"):
        client.list_messages("333333333333333333")


def test_discord_client_sends_only_after_confirmation_or_standing_authorization() -> None:
    module = discord_module()
    sent: list[dict] = []

    def request(method: str, url: str, **kwargs):
        sent.append({"method": method, "url": url, **kwargs})
        return FakeResponse({"id": "sent-1", "channel_id": "222222222222222222", "content": "Hello"})

    policy = module.policy.DiscordAccessPolicy(
        allowed_guild_ids=set(),
        allowed_channel_ids={"222222222222222222", "333333333333333333"},
        autonomous_channel_ids={"333333333333333333"},
    )
    client = module.client.DiscordClient(bot_token="bot-secret", policy=policy, request_backend=request)

    with pytest.raises(module.errors.DiscordPermissionError, match="confirmation"):
        client.send_message("222222222222222222", "Hello")

    confirmed = client.send_message("222222222222222222", "Hello", confirmed=True)
    autonomous = client.send_message("333333333333333333", "Hello")

    assert confirmed["id"] == "sent-1"
    assert autonomous["id"] == "sent-1"
    assert all(call["json"]["allowed_mentions"] == {"parse": []} for call in sent)


def _service(*, autonomous: bool = False) -> DiscordCapabilityService:
    channel_id = "222222222222222222"
    return DiscordCapabilityService(
        account_backend=lambda: {"id": "bot-1", "username": "Vellum"},
        guilds_backend=lambda: [{"id": "111111111111111111", "name": "Test Guild"}],
        channels_backend=lambda guild_id: [{"id": channel_id, "guild_id": guild_id, "name": "general", "type": 0}],
        messages_backend=lambda requested_channel, limit, before: [
            {
                "id": "message-1",
                "channel_id": requested_channel,
                "content": "Current project status",
                "timestamp": "2026-09-01T10:00:00+00:00",
                "author": {"id": "user-1", "username": "Example"},
            }
        ][:limit],
        send_backend=lambda requested_channel, content, confirmed: {
            "id": "sent-1",
            "channel_id": requested_channel,
            "content": content,
        },
        allowed_guild_ids={"111111111111111111"},
        allowed_channel_ids={channel_id},
        autonomous_channel_ids={channel_id} if autonomous else set(),
    )


def test_discord_capabilities_keep_external_writes_confirmation_gated() -> None:
    service = _service()
    registry = service.build_registry()

    assert registry.invoke("discord.messages", {"channel_id": "222222222222222222"}, agent_name="DiscordAgent")["items"]
    with pytest.raises(ToolPermissionError, match="requires explicit confirmation"):
        registry.invoke(
            "discord.send_message",
            {"channel_id": "222222222222222222", "content": "Hello"},
            agent_name="DiscordAgent",
        )


def test_discord_agent_prepares_write_then_executes_confirmed_action() -> None:
    service = _service()
    registry = service.build_registry()
    agent = DiscordAgent(tool_registry=registry, discord_service=service)

    prepared = agent.answer('Send "Hello team" to Discord channel 222222222222222222')
    completed = agent.execute_action_request(prepared.action_request)

    assert prepared.status == "blocked"
    assert prepared.action_request["action"] == "discord.send_message"
    assert "Hello team" in prepared.summary
    assert completed.status == "answered"
    assert completed.structured_payload["message"]["id"] == "sent-1"


def test_discord_agent_uses_standing_authorization_for_autonomous_channel() -> None:
    service = _service(autonomous=True)
    agent = DiscordAgent(tool_registry=service.build_registry(), discord_service=service)

    response = agent.answer('Send "Daily update" to Discord channel 222222222222222222')

    assert response.status == "answered"
    assert response.action_request == {}
    assert response.structured_payload["message"]["content"] == "Daily update"


def test_discord_agent_reads_recent_channel_messages() -> None:
    service = _service()
    agent = DiscordAgent(tool_registry=service.build_registry(), discord_service=service)

    response = agent.answer("Show recent Discord messages in channel 222222222222222222")

    assert response.status == "answered"
    assert "Current project status" in response.summary
    assert response.sources[0].kind == "api"


def test_discord_client_errors_never_include_provider_payload_or_token() -> None:
    module = discord_module()
    client = module.client.DiscordClient(
        bot_token="bot-secret",
        policy=module.policy.DiscordAccessPolicy(),
        request_backend=lambda *_args, **_kwargs: FakeResponse(
            {"message": "token bot-secret was rejected"}, status_code=401
        ),
    )

    with pytest.raises(module.errors.DiscordAuthError) as error:
        client.get_current_user()

    assert "bot-secret" not in str(error.value)
    assert "rejected" not in str(error.value)


def test_discord_client_retries_one_rate_limit_with_bounded_delay() -> None:
    module = discord_module()
    responses = iter([
        FakeResponse({"retry_after": 12}, status_code=429),
        FakeResponse({"id": "bot-1", "username": "Vellum"}),
    ])
    delays: list[float] = []
    client = module.client.DiscordClient(
        bot_token="bot-secret",
        policy=module.policy.DiscordAccessPolicy(),
        request_backend=lambda *_args, **_kwargs: next(responses),
        sleep_backend=delays.append,
    )

    assert client.get_current_user()["id"] == "bot-1"
    assert delays == [5.0]


def test_discord_read_request_is_not_misclassified_as_send() -> None:
    service = _service()
    agent = DiscordAgent(tool_registry=service.build_registry(), discord_service=service)

    response = agent.answer("Show the latest Discord message in channel 222222222222222222")

    assert response.status == "answered"
    assert response.action_request == {}


def test_discord_profile_owns_scoped_tools_and_memory() -> None:
    profile = AgentCatalog(profile_dir=Path("__missing_profiles__")).get("DiscordAgent")

    assert profile.tools.allow == [
        "discord.account",
        "discord.guilds",
        "discord.channels",
        "discord.messages",
        "discord.send_message",
    ]
    assert profile.tools.require_confirmation == ["discord.send_message"]
    assert profile.memory.read_scopes == ["user_profile", "shared", "agent:DiscordAgent"]
    assert profile.memory.write_scope == "agent:DiscordAgent"


def test_discord_message_observation_is_local_only_and_not_preference_evidence(tmp_path: Path) -> None:
    store = KnowledgeStore(tmp_path / "knowledge.db", tmp_path / "blobs")
    core = SimpleNamespace(store=store, record_tool_result=lambda **_kwargs: None)
    observer = KnowledgeToolObserver(core)
    observer(
        ToolInvocation(
            name="discord.messages",
            namespace="discord",
            access=CapabilityAccess.READ,
            agent_name="DiscordAgent",
            payload={"channel_id": "222222222222222222", "limit": 20},
            result={
                "channel_id": "222222222222222222",
                "items": [
                    {
                        "id": "message-1",
                        "channel_id": "222222222222222222",
                        "content": "A private Discord message",
                        "author": {"id": "user-1", "username": "Example"},
                    }
                ],
            },
        )
    )

    source = store.list_sources(kind="discord_message")[0]
    assert source["sensitivity"] == Sensitivity.PRIVATE_LOCAL_ONLY.value
    assert source["external_policy"] == ExternalPolicy.DENY_RAW.value


def test_main_model_discord_tool_receives_only_scrubbed_derivatives() -> None:
    response = SpecialistResponse(
        agent="DiscordAgent",
        status="answered",
        summary="Alex can be reached at alex@example.com",
        sources=[
            SpecialistSource(
                kind="api",
                title="Discord message from Alex",
                path_or_url="discord://channels/222/messages/333",
                snippet="Email alex@example.com",
            )
        ],
        structured_payload={
            "message": {"id": "333", "channel_id": "222", "content": "Email alex@example.com"},
            "authorization": "standing",
        },
    )

    payload = _external_response_json(response)

    assert "alex@example.com" not in payload
    assert "discord://" not in payload
    assert '"sent": true' in payload
    assert '"privacy": "local_only_content_withheld"' in payload
