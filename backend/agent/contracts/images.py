"""Arguments bound to Vellum's image generation review."""
from typing import Literal
from pydantic import BaseModel, ConfigDict, Field, model_validator


class ImageGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["generate", "edit"] = "generate"
    prompt: str = Field(min_length=1, max_length=16000)
    image_path: str = Field(default="", max_length=1024)
    size: Literal["1024x1024", "1536x1024", "1024x1536", "auto"] = "1024x1024"
    background: Literal["auto", "opaque", "transparent"] = "auto"

    @model_validator(mode="after")
    def edit_target(self):
        if not self.prompt.strip() or bool(self.image_path) != (self.action == "edit"):
            raise ValueError("Provide a prompt and an image path only for an edit.")
        return self
