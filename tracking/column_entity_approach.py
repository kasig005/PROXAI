from graph.neo4j import Neo4jFactory, Neo4jQueries
from graph.structure import *
from graph.constants import *
from graph.structure import *
from utils import *
from graph.constants import *
from LLM.LLM_activities_used_columns import LLM_activities_used_columns
import math
from KEY import MY_KEY


def is_number(value):
    try:
        float(value)
        return True
    except ValueError:
        return False


def column_entitiy_vision(changes, current_activities, args, activity_to_zoom):
    #keeping current elements on the graph supporting the creation on neo4j
    current_entities = {}
    current_columns = {}

    used_columns_giver = LLM_activities_used_columns(api_key = MY_KEY)
    #keeping current elements on the graph supporting the creation on neo4j
    entities_to_keep = []

    # find the differnce of the df and create the entities
    derivations = []
    derivations_column = []
    current_relations = []
    current_relations_column = []
    current_columns_to_entities = {}
    for act in changes.keys():
        used_cols = None
        generated_entities = []
        used_entities = []
        invalidated_entities = []
        generated_columns = []
        used_columns = []
        invalidated_columns = []
        if act == 0:
            continue
        # The LLM activity extraction (descript()) is non-deterministic and may
        # return fewer activities than there are tracker.analyze_changes()
        # snapshots. Without this guard the positional index below throws
        # IndexError and the whole run is lost.
        if act - 1 >= len(current_activities):
            print(f"[column_entitiy_vision] no activity for snapshot {act} "
                  f"(have {len(current_activities)} activities) -- skipping")
            continue
        activity = current_activities[act-1]
        df1 = changes[act]['before']
        df2 = changes[act]['after']
        activity['runtime_exceptions'] = "No exceptions occurred"

        activity_description, activity_code = activity['context'], activity['code']
        used_cols = eval(used_columns_giver.give_columns(df1, df2, activity_code, activity_description))

        # Approach working when the number of rows is the same and the number of columns increase or is the same
        unique_col_in_df1 = set(df1.columns)-set(df2.columns)
        unique_col_in_df2 = set(df2.columns)-set(df1.columns)
        #if the column is exclusively in the "before" dataframe
        unique_df1_col = []
        for col in unique_col_in_df1:
            #control il the column already exist or create it
            val_col = str(df1[col].tolist())
            idx_col = str(df1.index.tolist())
            new_column = None
            if (val_col, idx_col, col) not in current_columns.keys():
                new_column = create_column(val_col, idx_col, col)
                current_columns[(val_col,idx_col, col)] = new_column
                current_columns_to_entities[new_column['id']] = []
            else:
                new_column = current_columns[(val_col,idx_col, col)]
            unique_df1_col.append(new_column)
            used_columns.append(new_column['id'])
            invalidated_columns.append(new_column['id'])
            for idx in df1.index:
                old_value = df1.at[idx, col]
                old_entity = None
                if (old_value, col, idx) in current_entities.keys():
                    old_entity = current_entities[(old_value, col, idx)]
                else:
                    old_entity = create_entity(old_value, col, idx)
                    current_entities[(old_value, col, idx)] = old_entity
                invalidated_entities.append(old_entity['id'])
                used_entities.append(old_entity['id'])
                current_columns_to_entities[new_column['id']].append(old_entity['id'])
        # if the column is exclusively in the "after" dataframe
        for col in unique_col_in_df2:
            #control il the column already exist or create it
            val_col = str(df2[col].tolist())
            idx_col = str(df2.index.tolist())
            old_col = None
            if (val_col, idx_col, col) not in current_columns.keys():
                new_column = create_column(val_col, idx_col, col)
                generated_columns.append(new_column['id'])
                current_columns[(val_col, idx_col, col)] = new_column
                current_columns_to_entities[new_column['id']] = []
                for column in unique_df1_col:
                    if new_column['index']==column['index'] and new_column['value']==column['value']:
                        derivations_column.append({'gen': str(new_column['id']), 'used': str(column['id'])})
                        old_col = column['name']
                        break
            for idx in df2.index:
                new_value = df2.at[idx, col]
                new_entity = create_entity(new_value, col, idx)
                if old_col and df1.at[idx, old_col]:
                    old_value = df1.at[idx, old_col]
                    old_entity = current_entities[(old_value, old_col, idx)]
                    derivations.append({'gen': str(new_entity['id']), 'used': str(old_entity['id'])})
                current_entities[(new_value, col, idx)] = new_entity
                generated_entities.append(new_entity['id'])
                current_columns_to_entities[new_column['id']].append(new_entity['id'])

        common_col = set(df1.columns).intersection(set(df2.columns))
        for col in common_col:
            new_column = None
           
            #verify if a column is used and in that case add it to used columns
            used_column = None
            if col in used_cols:
                val_col = str(df1[col].tolist())
                idx_col = str(df1.index.tolist())
                if (val_col, idx_col, col) not in current_columns.keys():
                        used_column = create_column(val_col, idx_col, col)
                        current_columns[(val_col,idx_col, col)] = used_column
                        current_columns_to_entities[used_column['id']] = []
                else: 
                    used_column = current_columns[(val_col, idx_col, col)]
                if used_column:
                    used_columns.append(used_column['id'])


            for idx in df2.index:
                if idx in df1.index:
                    old_value = df1.at[idx, col]
                else:
                    old_value = 'Not exist'
                new_value = df2.at[idx, col]
                
                if old_value != new_value:
                    if is_number(old_value) and is_number(new_value):
                        old_val = float(old_value)
                        new_val = float(new_value)
                        if math.isnan(new_val) and math.isnan(old_val): 
                            continue
                    if (new_value, col, idx) in current_entities: continue
                    #control il the column already exist or create it
                    val_col = str(df2[col].tolist())
                    idx_col = str(df2.index.tolist())
                    if (val_col, idx_col, col) not in current_columns.keys():
                        new_column = create_column(val_col, idx_col, col)
                        generated_columns.append(new_column['id'])
                        current_columns[(val_col,idx_col, col)] = new_column
                        current_columns_to_entities[new_column['id']] = []
                    else: 
                        new_column = current_columns[(val_col, idx_col, col)]

                    entity = create_entity(new_value, col, idx)
                    if old_value != 'Not exist':
                        #same control but for the before df, to get the used columns
                        old_column = None
                        val_old_col = str(df1[col].tolist())
                        idx_old_col = str(df1.index.tolist())
                        if (val_old_col, idx_old_col, col) not in current_columns.keys():
                            old_column = create_column(val_old_col, idx_old_col, col)
                            current_columns[(val_old_col, idx_old_col, col)] = old_column
                            current_columns_to_entities[old_column['id']] = []
                        else:
                            old_column = current_columns[(val_old_col,idx_old_col, col)]
                        if new_column and new_column['id']!=old_column['id']: derivations_column.append({'gen': str(new_column['id']), 'used': str(old_column['id'])})
                        used_columns.append(old_column['id'])
                        invalidated_columns.append(old_column['id'])
                        old_entity = None
                        if (old_value, col, idx) in current_entities.keys():
                            old_entity = current_entities[(old_value, col, idx)]
                        else:
                            old_entity = create_entity(old_value, col, idx)
                            current_entities[(old_value, col, idx)] = old_entity
                        derivations.append({'gen': str(entity['id']), 'used': str(old_entity['id'])})
                        used_entities.append(old_entity['id'])
                        invalidated_entities.append(old_entity['id'])
                        current_columns_to_entities[old_column['id']].append(old_entity['id'])
                    generated_entities.append(entity['id'])
                    current_entities[(new_value, col, idx)] = entity
                    current_columns_to_entities[new_column['id']].append(entity['id'])
        # # Iterate over the columns and rows to find differences
        unique_rows_in_df1 = set(df1.index) - set(df2.index)
        if len(unique_rows_in_df1) > 0:
            for col in df2.columns:
                #control if the column already exist or create it
                val_col = str(df2[col].tolist())
                idx_col = str(df2.index.tolist())
                new_column = None
                if (val_col, idx_col, col) not in current_columns.keys():
                    new_column = create_column(val_col, idx_col, col)
                    current_columns[(val_col,idx_col, col)] = new_column
                    current_columns_to_entities[new_column['id']] = []
                    generated_columns.append(new_column['id'])
                else:
                    new_column = current_columns[(val_col,idx_col, col)]
                
                for idx in unique_rows_in_df1:
                    if idx in df1.index and col in df1.columns :
                        val_col = str(df1[col].tolist())
                        idx_col = str(df1.index.tolist())
                        old_column = None
                        if (val_col, idx_col, col) not in current_columns.keys():
                            old_column = create_column(val_col, idx_col, col)
                            current_columns[(val_col, idx_col, col)] = old_column
                            current_columns_to_entities[old_column['id']] = []
                        else:
                            old_column = current_columns[(val_col, idx_col, col)]
                        old_value = df1.at[idx, col]
                        old_entity = create_entity(old_value, df1.columns[df2.columns.get_loc(col)], idx)
                        current_entities[(old_value, df1.columns[df2.columns.get_loc(col)], idx)] = old_entity
                        current_columns[(val_col, idx_col, col)] = old_column
                        used_columns.append(old_column['id'])
                        invalidated_columns.append(old_column['id'])
                        if new_column and new_column['id']!=old_column['id']: 
                            derivations_column.append({'gen': str(new_column['id']), 'used': str(old_column['id'])})
                        used_entities.append(old_entity['id'])
                        invalidated_entities.append(old_entity['id'])
                        current_columns_to_entities[old_column['id']].append(old_entity['id'])

        if activity_to_zoom == act:
            pass
        else:
            if args.granularity_level == 1 or args.granularity_level == 2 :
                gen_element = keep_random_element_in_place(generated_entities)
                inv_elem = None
                if gen_element:
                    entities_to_keep.append(gen_element)
                used_elem = keep_random_element_in_place(used_entities)
                if used_elem:
                    if used_elem in invalidated_entities:
                        invalidated_entities.clear()
                        invalidated_entities.append(used_elem)
                    entities_to_keep.append(used_elem)
                else:
                    inv_elem = keep_random_element_in_place(invalidated_entities)

                if inv_elem:
                    entities_to_keep.append(inv_elem)

        current_relations_column.append(create_relation_column(activity['id'], generated_columns, used_columns, invalidated_columns, same=False))
        current_relations.append(create_relation(activity['id'], generated_entities, used_entities, invalidated_entities, same=False))

    return current_entities, current_columns,current_relations, current_relations_column, derivations, derivations_column, current_columns_to_entities, entities_to_keep