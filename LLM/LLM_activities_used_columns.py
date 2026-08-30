from langchain_groq import ChatGroq  # noqa: F401 (kept for --backend groq)
from LLM.llm_client import make_chat
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re
import os

from LLM.llm_extract import extract_block


class LLM_activities_used_columns:

    def __init__(self, api_key: str, temperature: float = 0, model_name: str = "openai/gpt-oss-120b"):
        self.chat = make_chat(api_key=api_key, temperature=temperature, max_tokens=256)

        # Template to identify used columns
        PIPELINE_STANDARDIZER_TEMPLATE = """
            You are receiving the dataframe before and after the operation, the code and the description of the operation.
            Return me a python list with the name of the columns in the dataframe before used by the operation. Limit your observations just to this inputs and the code of the operation. Do not make assumptions.
            Return the python list between `[]`.
            
            
            For example if a column is dropped only the dropped column is used.
            Example of answer: ```["column1", "column2", "column3"]```
            Write the list inside ``` ```
            
            dataframe before:{df_before}
            dataframe after:{df_after}
            
            code:{code}
            description:{description}
        """


        self.prompt = PromptTemplate(
            template=PIPELINE_STANDARDIZER_TEMPLATE,
            input_variables=["df_before", "df_after", "code", "description"],
        )

        self.chat_chain = self.prompt | self.chat | StrOutputParser()


    def give_columns(self, df_before, df_after, code, description) -> str:

        response = self.chat_chain.invoke(
            {"df_before": df_before, "df_after": df_after, "code": code, "description": description})
        # Tolerant: fenced block, else the outermost [...], else raw text.
        # (Previously returned None when unfenced -> eval(None) in the caller.)
        return extract_block(response, "[", "]")

