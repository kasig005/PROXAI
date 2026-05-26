from LLM.LLM_activities_descriptor import LLM_activities_descriptor
from LLM.LLM_formatter import LLM_formatter
from LLM.LLM_activities_used_columns import LLM_activities_used_columns
from graph.neo4j import Neo4jConnector, Neo4jFactory
from graph.structure import *
from tracking.column_entity_approach import column_entitiy_vision
from tracking.column_approach import column_vision
from tracking.tracking import ProvenanceTracker
import argparse
from KEY import MY_KEY

import ast
import textwrap
import re


def wrapper_run_pipeline(arguments, tracker):
    try:
        # Execute run_pipeline
        run_pipeline(arguments, tracker)
    except Exception as e:
        exception_type = type(e).__name__  # exception type name
        exception_message = str(e)
        print(f"Captured Exception: {exception_type} - {exception_message}")
        return f"{exception_type} - {exception_message}"

    return " "

def get_args() -> argparse.Namespace:
    """
    Parses command line arguments
    """
    parser = argparse.ArgumentParser(description="Pipeline")
    parser.add_argument("--dataset", type=str, default="datasets/car_data.csv",
                        help="Relative path to the dataset file")
    parser.add_argument("--pipeline", type=str, default="pipelines/car_pipeline.py",
                        help="Relative path to the dataset file")
    parser.add_argument("--frac", type=float, default=0.1, help="Sampling fraction [0.0 - 1.0]")
    parser.add_argument("--granularity_level", type=int, default=3, help="Granularity level: 1, 2, 3 or 4")
    parser.add_argument("--use_manual_code", action="store_true",
                        help="Usa extracted_code.py manuale invece del codice standardizzato dall'LLM")
    args, unknown = parser.parse_known_args()

    return parser.parse_args()

#Standardize the structure of the file in a way that provenance is tracked
formatter = LLM_formatter(get_args().pipeline, api_key = MY_KEY)
#Standardized file given by the LLM
#extracted_file = formatter.standardize()
if get_args().use_manual_code:
    print("[PROLIT] Using manual extracted_code.py")
    extracted_file = "extracted_code.py"
else:
    print("[PROLIT] Using LLM-standardized code")
    extracted_file = formatter.standardize()
descriptor = LLM_activities_descriptor(extracted_file, api_key = MY_KEY)
used_columns_giver = LLM_activities_used_columns(api_key = MY_KEY)

from extracted_code import run_pipeline

#description of each activity. A list of dictionaries like { "act_name" : ("description of the operation", "code of the operation")}
activities_description = descriptor.descript()
print(activities_description)

# Pulisce il testo
cleaned = activities_description.replace("pipeline_operations = ", "")

# Rimuove blocchi markdown (```python ... ```) o singola parola 'python'
cleaned = re.sub(r"```python\s*", "", cleaned, flags=re.IGNORECASE)
cleaned = re.sub(r"```", "", cleaned)
cleaned = re.sub(r"^python\s*", "", cleaned, flags=re.IGNORECASE | re.MULTILINE)

# Normalizza l'indentazione
cleaned = textwrap.dedent(cleaned).strip()

# Debug opzionale:
print("--- Cleaned string ---")
print(cleaned)
print("----------------------")

# Parsing sicuro
activities_description_dict = ast.literal_eval(cleaned)

# print(activities_description_dict)

#Neo4j initialization
neo4j = Neo4jFactory.create_neo4j_queries(uri="bolt://localhost:7687", user="neo4j", pwd="adminadmin")
neo4j.delete_all()
session = Neo4jConnector().create_session()
tracker = ProvenanceTracker(save_on_neo4j=True)

#running the preprocessing pipeline
exception = wrapper_run_pipeline(get_args(), tracker)

#Dictionary of all the df before and after the operations
changes = tracker.changes

current_activities = []
current_entities = {}
current_columns = {}
current_derivations = []
current_entities_column = []
entities_to_keep = []
derivations = []
derivations_column = []
current_relations = []
current_relations_column = []
current_columns_to_entities = {}

loop = True
activity_to_zoom = None
while loop:

    #Create the activities found by the llm
    for act_name in activities_description_dict.keys():
        act_context, act_code = activities_description_dict[act_name]
        activity = create_activity(function_name=act_name, context=act_context, code=act_code, exception_text = exception)
        current_activities.append(activity)

    if get_args().granularity_level != 4:
        current_entities, current_columns, current_relations, current_relations_column, derivations, derivations_column, current_columns_to_entities, entities_to_keep = column_entitiy_vision(changes, current_activities, get_args(), activity_to_zoom)
    else:
        current_relations_column, current_columns, derivations_column = column_vision(changes, current_activities)

    # Create constraints in Neo4j
    neo4j.create_constraint(session=session)

    # Add activities, entities, derivations, and relations to the Neo4j Graph
    neo4j.add_activities(current_activities, session)
    if get_args().granularity_level == 1:
        filtered_list = [entity for entity in current_entities.values() if entity['id'] in entities_to_keep]
        neo4j.add_entities(filtered_list)
    else:
        neo4j.add_entities(list(current_entities.values()))
    neo4j.add_columns(list(current_columns.values()))
    neo4j.add_derivations(derivations)
    neo4j.add_relations(current_relations)
    neo4j.add_relations_columns(current_relations_column)
    neo4j.add_derivations_columns(derivations_column)

    relations = []
    for act in current_columns_to_entities.keys():
        relation = []
        relation.append(act)
        relation.append(current_columns_to_entities[act])
        relations.append(relation)
    neo4j.add_relation_entities_to_column(relations)

    pairs = []
    for i in range(len(current_activities)-1):
        pairs.append({'act_in_id': current_activities[i]['id'], 'act_out_id': current_activities[i+1]['id']})

    neo4j.add_next_operations(pairs)

    del current_activities[:]
    del current_entities
    del current_columns
    del derivations[:]
    del derivations_column[:]
    del current_relations[:]
    del current_relations_column[:]
    del current_columns_to_entities
    # print("if you want to zoom on one activity select the succession number of the desired activity, otherwise type 'N' ")
    # answer = input(">")
    # if answer == 'N':
    loop = False
        # neo4j.delete_all()
    # else:
    #     neo4j.delete_all()
    #     activity_to_zoom = int(answer)

session.close()


