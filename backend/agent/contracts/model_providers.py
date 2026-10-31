"""Public model-provider connection metadata. Credentials never enter this contract."""
from pydantic import BaseModel, ConfigDict


class ProviderConnection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str
    name: str
    description: str
    icon: str
    key_url: str
    requires_key: bool
    configured: bool
    model_selection_supported: bool
