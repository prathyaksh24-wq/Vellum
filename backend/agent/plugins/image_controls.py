"""Operation-bound image disclosure and cost review through existing App Actions."""
import json
from agent.app_actions.models import AppActionDefinition
from agent.contracts.images import ImageGenerationRequest
from agent.plugins.contributions import PluginActionContribution, PluginContribution, PluginContributionActionError


def image_contribution():
    def execute(payload):
        if payload.get("confirmed") is not True:
            raise PluginContributionActionError("CONFIRMATION_REQUIRED", "Review sending this prompt and selected image to OpenAI first.")
        request = ImageGenerationRequest.model_validate(payload.get("arguments") or {})
        from agent.tools.images import _execute_image
        result = json.loads(_execute_image(**request.model_dump(), confirm=True))
        if not result.get("ok"):
            raise PluginContributionActionError("IMAGE_GENERATION_FAILED", result.get("error") or "Image generation failed.")
        return {**result, "changed": True, "_message": "OpenAI returned an image, saved locally. Visual quality has not been verified."}

    owner = "openai-system-skills"
    definition = AppActionDefinition(
        id="image.generate", version="1", owner=owner, plugin_id=owner,
        title="Generate or edit an image with OpenAI",
        description="Send only the reviewed prompt and explicitly selected edit image to OpenAI. API usage charges may apply. Save a new image locally without overwriting the source.",
        scope="user", access_class="external_write", confirmation_rule="operation_bound",
        executor_location="server", supports_undo=False, idempotent=False,
        argument_schema=ImageGenerationRequest.model_json_schema(), result_schema={"type": "object"},
        ui_reference="plugin-manage", audit_label="image.generate", required_permissions=["image.generate"],
    )
    return PluginContribution(owner=owner, actions=(PluginActionContribution(definition=definition, adapter=execute),))
