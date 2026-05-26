from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re
import os


class LLM_activities_descriptor:

    def __init__(self, file_pipeline, api_key: str, temperature: float = 0, model_name: str = "llama-3.3-70b-versatile"):
        self.chat = ChatGroq(temperature=temperature, groq_api_key=api_key, model_name=model_name)

        # cleaning pipeline in text format
        self.pipeline_content = self.file_to_text(file_pipeline)

        # Template to describe activities
        PIPELINE_DESCRIPTOR_TEMPLATE = """
You are an expert in data preprocessing pipelines. Return a list of name + (description of the single operations in the pipeline, python code of the operation), consider just the content of the run_pipeline function. Do not include sampling subscription and column name assignment and identification of the objects of the columns activities. Consider just the code after the subscription of the dataframe (df.subscribe()). Be the most detailed as possible.

Return the result as a python dictionary with the operation name as key and the description as value. Do not refer to comments. Do not include sampling operations. Consider just the operations appearing after the tracker.subscribe line and with a tracker.analyze_changes(df) in their block. All the operations followed by tracker.analyze_changes have to appear in the map. Do not consider the sampling as an operation.

Give me the result as a map between triple backticks (```), and make sure it is a valid Python dictionary parsable with ast.literal_eval.

Example:
pipeline:
import pandas as pd
from sklearn.model_selection import train_test_split
from sklearn.impute import SimpleImputer
from sklearn.preprocessing import StandardScaler, OneHotEncoder
from sklearn.compose import ColumnTransformer
from sklearn.pipeline import Pipeline
from sklearn.ensemble import RandomForestRegressor
from sklearn.feature_selection import RFE
from sklearn.metrics import mean_squared_error

data = pd.read_csv('data.csv')
X = data.drop('target', axis=1)
y = data['target']
df = tracker.subscribe(data)
tracker.analyze_changes(df)

num_features = X.select_dtypes(include=['int64', 'float64']).columns
cat_features = X.select_dtypes(include=['object']).columns

response:
```
{{"Identification of numerical and categorical columns": ("Determine which columns are numerical and which are categorical using select_dtypes", "num_features = X.select_dtypes(include=['int64', 'float64']).columns\\ncat_features = X.select_dtypes(include=['object']).columns")}}
```

Cleaning Pipeline: {pipeline_content}
"""

        self.prompt = PromptTemplate(
            template=PIPELINE_DESCRIPTOR_TEMPLATE,
            input_variables=["pipeline_content"]
        )

        self.chat_chain = self.prompt | self.chat | StrOutputParser()

    def file_to_text(self, file):
        try:
            with open(file, 'r') as file:
                content = file.read()
        except Exception as e:
            print(f"An error occurred: {e}")
            content = ""
        return content

    def descript(self) -> str:
        response = self.chat_chain.invoke({"pipeline_content": self.pipeline_content})
        extracted_text = re.search(r"```(.*?)```", response, re.DOTALL)

        if extracted_text:
            return extracted_text.group(1).replace("python\n", "").strip()
