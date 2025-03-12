import requests
import json
import pandas as pd
import os
from datetime import datetime

def fetch_trakt_data(path, json_filename, apikey, username):
    url = f"https://api.trakt.tv/users/{username}/{path}"
    headers = {
        "Content-Type": "application/json",
        "trakt-api-key": apikey,
        "trakt-api-version": "2"
    }
    
    response = requests.get(url, headers=headers)
    
    if response.status_code == 404:
        print("Wrong username!")
        return
    
    if response.status_code != 200:
        print(f"Error fetching data: {response.status_code}")
        return
    
    data = response.json()
    
    os.makedirs("files", exist_ok=True)
    json_filepath = os.path.join("files", json_filename)
    with open(json_filepath, "w") as f:
        json.dump(data, f, indent=4)
    
    print(f"Saved data to {json_filepath}")
    return json_filepath

def rename_dict_keys(dict_obj, pairs):
    for pair in pairs:
        dict_obj[pair[1]] = dict_obj[pair[0]]
        del dict_obj[pair[0]]
    return dict_obj

def convert_to_csv(trakt_file, output_csv):
    with open(trakt_file, encoding='utf-8') as f:
        print("Opening the file...")
        input_json = json.load(f)
        
        print("Parsing JSON...")
        processed_data = []
        
        for item in input_json:
            record = {}
            raw_keys = ["watched_at"]
            sub_keys = ["title", "year"]
            id_keys = ["imdb", "tmdb"]
            
            for index, key in enumerate(sub_keys):
                if 'movie' in item:
                    record[sub_keys[index]] = item['movie'][sub_keys[index]]
            
            for index, key in enumerate(id_keys):
                if 'movie' in item:
                    record[id_keys[index]] = item['movie']['ids'].get(id_keys[index], "")
            
            for index, key in enumerate(raw_keys):
                record[raw_keys[index]] = item[raw_keys[index]]
            
            pairs = [["title", "Title"], ["year", "Year"], ["imdb", "imdbID"], ["tmdb", "tmdbID"],
                     ["watched_at", "WatchedDate"]]
            record = rename_dict_keys(record, pairs)
            processed_data.append(record)
        
        df = pd.DataFrame(processed_data)
        csv_filepath = os.path.join("files", output_csv)
        df.to_csv(csv_filepath, index=False)
        print(f"Converted and saved to {csv_filepath}")
        return csv_filepath

def push_to_github():
    os.system("git config --global user.name 'github-actions'")
    os.system("git config --global user.email 'github-actions@github.com'")
    os.system("git add files/watched_movies.json files/letterboxd.csv")
    os.system("git commit -m 'Update watched movies and letterboxd CSV' || echo 'No changes to commit'")
    os.system("git push")

def main():
    API_KEY = os.getenv("TRAKT_API_KEY")
    USERNAME = os.getenv("TRAKT_USERNAME")
    JSON_FILENAME = "watched_movies.json"
    CSV_FILENAME = "letterboxd.csv"
    
    json_filepath = fetch_trakt_data("history/movies", JSON_FILENAME, API_KEY, USERNAME)
    if json_filepath:
        csv_filepath = convert_to_csv(json_filepath, CSV_FILENAME)
        if csv_filepath:
            push_to_github()

if __name__ == "__main__":
    main()
