#python
import pandas as pd
from sklearn.preprocessing import LabelEncoder
from keras.utils import to_categorical
from sklearn.model_selection import train_test_split
import numpy as np
import tensorflow as tf


def run_pipeline(args, tracker=None) -> None:

    # Load the dataset from the specified input path
    input_path = args.dataset

    # Read the dataset into a pandas DataFrame
    df = pd.read_csv(input_path, header=0)

    # If a fraction is specified, sample the dataset
    if hasattr(args, 'frac') and args.frac != 0.0:
        # Sample the dataset to the specified fraction
        df = df.sample(frac=args.frac)

    # If a tracker is provided, subscribe the DataFrame to it
    if(tracker is not None):
        # Subscribe the DataFrame to the tracker
        df = tracker.subscribe(df)
        tracker.analyze_changes(df)

    # Assign names to the columns of the DataFrame
    names = ['age', 'workclass', 'fnlwgt', 'education', 'education-num', 'marital-status', 'occupation', 'relationship',
                'race', 'sex', 'capital-gain', 'capital-loss', 'hours-per-week', 'native-country', 'label']
    df.columns = names
    tracker.analyze_changes(df)

    # Specify the columns to apply the strip operation to
    columns = ['workclass', 'education', 'marital-status', 'occupation', 'relationship', 'race', 'sex', 'native-country',
            'label']
    # Apply the strip operation to the specified columns
    df[columns] = df[columns].apply(lambda col: col.map(str.strip))
    # Replace '?' with 0 in the DataFrame
    df = df.replace('?', 0)
    tracker.analyze_changes(df)

    # Replace 'Male' with 1 and 'Female' with 0 in the 'sex' column, and '<=50K' with 0 and '>50K' with 1 in the 'label' column
    df = df.replace({'sex': {'Male': 1, 'Female': 0}, 'label': {'<=50K': 0, '>50K': 1}})
    tracker.analyze_changes(df)

    # Drop the 'fnlwgt' column from the DataFrame
    df = df.drop(['fnlwgt'], axis=1)
    tracker.analyze_changes(df)

    # Rename the 'hours-per-week' column to 'hw'
    df.rename(columns={'hours-per-week': 'hw'}, inplace=True)
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'workclass' column
    workclass_trans = LabelEncoder()
    # Fit and transform the 'workclass' column using the LabelEncoder
    df["workclass"] = workclass_trans.fit_transform(df["workclass"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'education' column
    education_trans = LabelEncoder()
    # Fit and transform the 'education' column using the LabelEncoder
    df["education"] = education_trans.fit_transform(df["education"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'marital-status' column
    marital_status_trans = LabelEncoder()
    # Fit and transform the 'marital-status' column using the LabelEncoder
    df["marital-status"] = marital_status_trans.fit_transform(df["marital-status"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'occupation' column
    occupation_trans = LabelEncoder()
    # Fit and transform the 'occupation' column using the LabelEncoder
    df["occupation"] = occupation_trans.fit_transform(df["occupation"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'relationship' column
    relationship_trans = LabelEncoder()
    # Fit and transform the 'relationship' column using the LabelEncoder
    df["relationship"] = relationship_trans.fit_transform(df["label"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'race' column
    race_trans = LabelEncoder()
    # Fit and transform the 'race' column using the LabelEncoder
    df["race"] = race_trans.fit_transform(df["race"].values.astype(str))
    tracker.analyze_changes(df)

    # Create a LabelEncoder for the 'native-country' column
    native_country_trans = LabelEncoder()
    # Fit and transform the 'native-country' column using the LabelEncoder
    df["native-country"] = native_country_trans.fit_transform(df["native-country"].values.astype(str))
    tracker.analyze_changes(df)

    # Split the DataFrame into features (X) and target (y)
    y = df["label"]
    # Drop the 'label' column from the DataFrame
    df = df.drop(columns=["label"])
    tracker.analyze_changes(df)

    # One-hot encode the target variable
    y = to_categorical(y.values, num_classes=2)
    tracker.analyze_changes(df)

    # Split the data into training and testing sets
    X_train, X_test, y_train, y_test = train_test_split(df, y, test_size=0.2, random_state=42)
    tracker.analyze_changes(df)

    # Return the training and testing sets
    return(X_train, X_test, y_train, y_test)