from agent.app_actions.models import AppActionContext, AppActionRequest
from agent.app_actions.petdex import (
    PETDEX_ACTIVE_SET_ACTION_ID,
    PETDEX_INSTALL_ACTION_ID,
    PETDEX_POSITION_SET_ACTION_ID,
    PETDEX_REMOVE_ACTION_ID,
    PETDEX_SIZE_SET_ACTION_ID,
    PETDEX_VISIBILITY_SET_ACTION_ID,
)
from agent.app_actions.runtime import AppActionRuntime


def context(**overrides) -> AppActionContext:
    petdex = {
        "revision": 3,
        "installed": ["boba"],
        "available": ["boba", "zoro"],
        "active": "boba",
        "hidden": False,
        "size": "md",
        "position": {},
        **overrides,
    }
    return AppActionContext(source="nlp", petdex=petdex)


def dispatch(action_id, arguments, **state):
    return AppActionRuntime().dispatch(
        AppActionRequest(action_id=action_id, arguments=arguments),
        context(**state),
    )


def test_petdex_actions_return_versioned_device_local_patches() -> None:
    installed = dispatch(PETDEX_INSTALL_ACTION_ID, {"slug": "zoro"})
    selected = dispatch(PETDEX_ACTIVE_SET_ACTION_ID, {"slug": "zoro"}, installed=["boba", "zoro"], hidden=True)
    hidden = dispatch(PETDEX_VISIBILITY_SET_ACTION_ID, {"visible": False})
    sized = dispatch(PETDEX_SIZE_SET_ACTION_ID, {"size": "large"})
    moved = dispatch(PETDEX_POSITION_SET_ACTION_ID, {"anchor": "bottom-left"})
    removed = dispatch(PETDEX_REMOVE_ACTION_ID, {"slug": "boba"}, installed=["boba", "zoro"])

    assert installed.result["petdex_patch"]["state"]["installed"] == ["boba", "zoro"]
    assert installed.result["petdex_patch"]["base_revision"] == 3
    assert installed.result["petdex_patch"]["revision"] == 4
    assert selected.result["petdex_patch"]["state"]["active"] == "zoro"
    assert selected.result["petdex_patch"]["state"]["hidden"] is False
    assert hidden.result["petdex_patch"]["state"]["hidden"] is True
    assert sized.result["petdex_patch"]["state"]["size"] == "lg"
    assert moved.result["petdex_patch"]["state"]["position"] == {"anchor": "bottom-left"}
    assert removed.result["petdex_patch"]["state"]["active"] == "zoro"


def test_petdex_rejects_unavailable_or_uninstalled_pets_truthfully() -> None:
    unavailable = dispatch(PETDEX_INSTALL_ACTION_ID, {"slug": "missing"})
    uninstalled = dispatch(PETDEX_ACTIVE_SET_ACTION_ID, {"slug": "zoro"})

    assert unavailable.status == "unavailable"
    assert unavailable.error_code == "PET_UNAVAILABLE"
    assert uninstalled.status == "unavailable"
    assert uninstalled.error_code == "PET_NOT_INSTALLED"


def test_petdex_recovers_from_a_malformed_client_revision() -> None:
    receipt = dispatch(PETDEX_VISIBILITY_SET_ACTION_ID, {"visible": False}, revision="not-a-number")

    assert receipt.status == "applied"
    assert receipt.result["petdex_patch"]["base_revision"] == 0
    assert receipt.result["petdex_patch"]["revision"] == 1


def test_petdex_nlp_matching_covers_visibility_size_selection_and_position() -> None:
    runtime = AppActionRuntime()

    assert runtime.match_submission("hide my pet").action_id == PETDEX_VISIBILITY_SET_ACTION_ID
    assert runtime.match_submission("make the pet large").arguments == {"size": "large"}
    assert runtime.match_submission("switch to Zoro pet").arguments == {"slug": "zoro"}
    assert runtime.match_submission("move my pet to the bottom left").arguments == {"anchor": "bottom-left"}
    assert runtime.match_submission("What do pets teach us about companionship?") is None
