from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser

class ChatBot:
    def __init__(self, api_key: str, temperature: float = 0.2, model_name: str = "llama3-70b-8192"):
        self.chat = ChatGroq(temperature=temperature, groq_api_key=api_key, model_name=model_name)

    def generate_prompt(self, element: str) -> PromptTemplate:
        if element == "column":
            template = """
            Use three sentences maximum and keep the answer concise.
            Do not respond in a negative way like the code doesn't.
            The input is a dictionary that rappresent a column, 'feature_name' is the name of the column, 'value' are the values of the element in the column and 'index' are the indexes of the values of the column.
            Look at the 'feature_name', 'value' and 'index' of the dictionary and use the code to expalain what appened.
            If the output column is present in the question look at the difference of the 'feature_name', 'value' and 'index' of the two dictionary and use the code given trough the context to give an explenation.

            Context: {context}
            Question: {question}
            """
        else:
            template = """
            Use three sentences maximum and keep the answer concise.
            Do not respond in a negative way like the code doesn't.
            The input is a dictionary that rappresent an entity of the dataFrame, 'feature_name' is the name of the column, 'value' are the value of the element in the dataframe and 'index' are the index of the value in the dataframe.
            Look at the 'feature_name', 'value' and 'index' of the dictionary and use the code to expalain what appened.
            If the output entity is present in the question look at the difference of the 'feature_name', 'value' and 'index' of the two dictionary and use the code given trough the context to give an explenation.

            Context: {context}
            Question: {question}
            """
        return PromptTemplate(template=template, input_variables=["context", "question"])
    

    def ask_question(self, context: str, input, type, output="optional", element="column") -> str:

        prompt = self.generate_prompt(element)
        self.chat_chain = prompt | self.chat | StrOutputParser()

        if type=="WAS_INVALIDATED_BY":
            question = f"Why this code invalidate this {input}?"
        elif type=="WAS_GENERATED_BY":
            question = f"Why this code get {output} from {input}?"
        elif type=="USED":
            question = f"Why this code use this {input}?"
        
        response = self.chat_chain.invoke({"context": context, "question": question})
        return response

































































































# from langchain_groq import ChatGroq
# from langchain.chains import LLMChain
# from langchain.prompts import PromptTemplate

# class ChatBot:
#     def __init__(self, api_key: str, temperature: float = 0.2, model_name: str = "llama3-70b-8192"):
#         self.chat = ChatGroq(temperature=temperature, groq_api_key=api_key, model_name=model_name)
        
#         self.prompt = PromptTemplate(
#             template="""
#             Use three sentences maximum and keep the answer concise.
#             Do not respond in a negative way like the code doesn't.
#             The input and output are dictionary that rappresent the columns, 'feture_name' is the name of the column, 'value' are the values of the element in the column and 'index' are the indexes of the values of the column.
#             Look at the difference of the 'feature_name', 'value' and 'index' of the two dictionary and use the code given trough the context to give and explenation.
            
#             Context: {context}
#             Question: {question}

#             """
#         )
        
#         self.chat_chain = LLMChain(llm=self.chat, prompt=self.prompt, verbose=False)

#     def ask_question(self, context: str, input="optional", output="optional", type="optional") -> str:
#         if type=="WAS_INVALIDATED_BY":
#             question = f"Why this code invalidate this column {input}?"
#         elif type=="WAS_GENERATED_BY":
#             question = f"Why this code generate this column {input}?"
#         elif type=="USED":
#             question = f"Why this code use this column {input}?"
#         else:
#             question = f"Why this code get {output} from {input}?"
#         response = self.chat_chain.invoke({"context": context, "question": question})
#         return response["text"]