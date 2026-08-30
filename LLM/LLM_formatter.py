from langchain_groq import ChatGroq
from langchain_core.prompts import PromptTemplate
from langchain_core.output_parsers import StrOutputParser
import re
import os
import textwrap  # necessario per rimuovere indentazioni errate


class LLM_formatter:

    def __init__(self, file_pipeline, api_key: str, temperature: float = 0, model_name: str = "openai/gpt-oss-120b"):
        self.chat = ChatGroq(temperature=temperature, groq_api_key=api_key, model_name=model_name)

        # cleaning pipeline in text format
        self.pipeline_content = self.file_to_text(file_pipeline)

        #  Template to standardize the preprocessing pipeline
        PIPELINE_STANDARDIZER_TEMPLATE = """
        Add python comments describing the single existing operations in the pipeline, be the most detailed as possible.Return your response as a complete python file, including both changed and not changed functions and import...
        Do not write new lines of code, just add python comments and empty lines related to the code that you read.

        Instructions:
        1. Each cleaning operation on the data frame should be conatined in the same block of code without empty lines.
        2. Do not write new lines of code, just add comments and empty lines. 
        3. Each operation on the data frame should be separated by a single empty line.
        4. Consider just the code contained in the run_pipeline function.
        5. Exclusively after the blocks after the subscribe dataframe block for each identified block add at the end, after leaving an empty line a line containing "tracker.analyze_changes(df)"
        6. Do not comment "tracker.analyze_changes(df)" lines

        Output format (strict):
        - Return ONLY raw Python source code.
        - DO NOT use Markdown fences (no triple backticks).
        - DO NOT include a leading language tag such as 'python'.
        - The very first line MUST be either an import statement or a Python comment starting with '#'.
        - Do not add any explanations before or after the code.

        example: 
        pipeline:
        X_train, X_test, y_train, y_test = train_test_split(df[['latitude', 'longitude']], df[['median_house_value']], test_size=0.33, random_state=0)
        #normalize the training and test data using the preprocessing.normalize() method from sklearn
        X_train_norm = preprocessing.normalize(X_train)
        X_test_norm = preprocessing.normalize(X_test)
    
        kmeans = KMeans(n_clusters = 3, random_state = 0)
        kmeans.fit(X_train_norm)
                
        response:
         # Split data into training and testing sets
            X_train, X_test, y_train, y_test = train_test_split(df[['latitude', 'longitude']], df[['median_house_value']], test_size=0.33, random_state=0)
            tracker.analyze_changes(df)
        
            # Normalize the training and test data
            X_train_norm = preprocessing.normalize(X_train)
            X_test_norm = preprocessing.normalize(X_test)
            tracker.analyze_changes(df)
            
            # Fit KMeans clustering model to the normalized training data
            kmeans = KMeans(n_clusters = 3, random_state = 0)
            kmeans.fit(X_train_norm)
            tracker.analyze_changes(df)
            
            # One-hot encode categorical columns: 'checking', 'credit_history', 'housing', 'job'
            columns = ['checking', 'credit_history', 'housing', 'job']
            for i, col in enumerate(columns):
                dummies = pd.get_dummies(df[col])
                df_dummies = dummies.add_prefix(col + '_')
                df = df.join(df_dummies)
                df = df.drop([col], axis=1)
            tracker.analyze_changes(df)

        Cleaning Pipeline:{pipeline_content}

        Question: {question}
        """

        self.prompt = PromptTemplate(
            template=PIPELINE_STANDARDIZER_TEMPLATE,
            input_variables=["pipeline_content", "question"],
        )

        self.chat_chain = self.prompt | self.chat | StrOutputParser()

    def file_to_text(self, file):
        # Leggi il contenuto del file e convertilo in testo
        content = None
        try:
            with open(file, 'r') as file:
                content = file.read()

        except Exception as e:
            print(f"An error occurred: {e}")
        return content

    def standardize(self) -> str:
        response = self.chat_chain.invoke(
            {"pipeline_content": self.pipeline_content, "question": "Description and Suggestions:"}
        )

        # Extract code block between triple backticks
        extracted_text = re.search("```(.*?)```", response, re.DOTALL)

        if extracted_text:
            code_to_write = extracted_text.group(1)

            # Normalize indentation manually:
            lines = code_to_write.splitlines()
            cleaned_lines = [
                line.lstrip() if line.lstrip().startswith(("import", "def", "class")) else line
                for line in lines
            ]
            code_to_write = "\n".join(cleaned_lines).strip()

            # Write to file
            filename = 'extracted_code.py'
            with open(filename, 'w') as file:
                file.write(code_to_write)

            print(f"Code has been successfully written to {filename}")
            print(os.path.abspath(filename))
            return str(os.path.abspath(filename))
        else:
            print("No triple-quoted text found.")