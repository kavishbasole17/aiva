import hashlib
from pathlib import Path

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"


class Prompt:
    def __init__(self, prompt_id: str, template: str) -> None:
        self.prompt_id = prompt_id
        self.template = template
        self.version = hashlib.sha256(template.encode("utf-8")).hexdigest()[:16]

    def render(self, inputs: dict[str, str]) -> str:
        rendered = self.template
        for key, value in inputs.items():
            rendered = rendered.replace("{{" + key + "}}", value)
        return rendered


class PromptRegistry:
    def __init__(self, directory: Path = PROMPTS_DIR) -> None:
        self.directory = directory
        self._cache: dict[str, Prompt] | None = None

    def _load(self) -> dict[str, Prompt]:
        if self._cache is None:
            prompts: dict[str, Prompt] = {}
            for path in sorted(self.directory.glob("*.txt")):
                prompt = Prompt(path.stem, path.read_text(encoding="utf-8"))
                prompts[prompt.prompt_id] = prompt
            self._cache = prompts
        return self._cache

    def get(self, prompt_id: str) -> Prompt:
        prompts = self._load()
        try:
            return prompts[prompt_id]
        except KeyError as exc:
            raise ValueError(f"Unknown prompt: {prompt_id}") from exc

    def list_ids(self) -> list[str]:
        return sorted(self._load().keys())
