from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    debug: bool = False

    # Database
    database_url: str = "sqlite:///./app.db"

    # Gmail OAuth + API
    google_client_secret_file: str = "./client_secret.json"
    google_token_file: str = "./gmail_token.json"
    gmail_user_id: str = "me"

    # Gmail query/polling
    # This is the Gmail search query used when polling for new messages.
    # Strict-ish defaults reduce ads/noise; you can tune later.
    gmail_search_query: str = "in:inbox newer_than:3m"
    gmail_max_results_per_poll: int = 25

    # Noise reduction
    # Legacy keyword scoring thresholds (only used for fallback when LLM is disabled/unavailable).
    job_detector_min_score: int = 12
    job_classifier_min_confidence: float = 0.35
    sender_domain_blacklist: str = "spotify.com,mailchimp.com,mailerlite.com,newsletter"
    subject_noise_keywords: str = "unsubscribe,newsletter,deal,discount,promo"

    # Local LLM (Ollama)
    use_llm: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3.1:8b"

    # Automation
    followup_after_days_no_response: int = 10


settings = Settings()

