# llm/models.py
from config.settings import settings

class Models:
    CODING = settings.OPENROUTER_CODING_MODEL
    REVIEW = settings.OPENROUTER_REVIEW_MODEL
    ANALYSIS = settings.OPENROUTER_ANALYSIS_MODEL
