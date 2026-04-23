import logging
from pydantic import BaseModel
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain_core.prompts import ChatPromptTemplate
from tenacity import retry, wait_exponential, stop_after_attempt

logger = logging.getLogger(__name__)

class RefinedQuery(BaseModel):
    Search_Keywords: str
    Refined_Question: str

class QueryRefiner:
    """
    Lightweight model (Gemini 2.5 Flash) to preprocess raw user inputs or regulatory text
    into optimized vector search keywords and a refined technical question.
    """
    def __init__(self, api_key: str, model_name: str = "gemini-2.5-flash"):
        self.llm = ChatGoogleGenerativeAI(
            model=model_name,
            temperature=0.0,
            google_api_key=api_key
        ).with_structured_output(RefinedQuery)
        
        self.prompt = ChatPromptTemplate.from_messages([
            ("system", """You are an expert Aviation Compliance Assistant.
Your task is to take a raw input (which could be a user query or a raw EASA regulatory requirement) and output two things:
1. "Search_Keywords": A highly optimized list of terms for FAISS vector retrieval. Align the language with EASA legal terminology (e.g., if the user says 'fire extinguisher', use 'portable fire extinguisher', 'safety equipment'). 
2. "Refined_Question": A professional, technical version of the user request suitable for a large language model to perform a strict compliance audit."""
            ),
            ("user", "Raw Input: {raw_input}")
        ])

    @retry(wait=wait_exponential(multiplier=1, min=1, max=5), stop=stop_after_attempt(3))
    def refine(self, raw_input: str) -> dict:
        chain = self.prompt | self.llm
        try:
            result = chain.invoke({"raw_input": raw_input})
            return {
                "Search_Keywords": result.Search_Keywords,
                "Refined_Question": result.Refined_Question
            }
        except Exception as e:
            logger.warning(f"QueryRefiner failed for input '{raw_input[:80]}...': {e}. Using raw input as fallback.")
            return {
                "Search_Keywords": raw_input,
                "Refined_Question": raw_input
            }

