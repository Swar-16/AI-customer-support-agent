class LLMProviderError(RuntimeError):
    def __init__(
        self,
        *,
        provider: str,
        message: str,
    ) -> None:
        self.provider = provider
        self.message = message

        super().__init__(f"[{provider}] {message}")


class LLMProviderTimeoutError(LLMProviderError):
    pass


class LLMProviderResponseError(LLMProviderError):
    pass