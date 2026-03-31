from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    # App
    debug: bool = False
    reset_db_on_start: bool = False

    # Database
    database_url: str = "sqlite:///./app.db"

    # Gmail OAuth + API
    google_client_secret_file: str = "./client_secret.json"
    google_token_file: str = "./gmail_token.json"
    gmail_user_id: str = "me"

    # Gmail query/polling
    gmail_search_query: str = "in:inbox category:primary newer_than:10d"
    gmail_max_results_per_poll: int = 50

    # Local LLM (Ollama)
    use_llm: bool = True
    ollama_base_url: str = "http://127.0.0.1:11434"
    ollama_model: str = "llama3:latest"


settings = Settings()

