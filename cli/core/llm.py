import os

from langchain_groq import ChatGroq


def create_main_llm() -> ChatGroq:
  return ChatGroq(
    model="openai/gpt-oss-20b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
  )


def create_sub_llm() -> ChatGroq:
  return ChatGroq(
    model="openai/gpt-oss-120b",
    api_key=os.getenv("GROQ_API_KEY"),
    temperature=0,
  )
