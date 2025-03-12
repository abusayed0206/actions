import requests
import json
import pandas as pd
import os
from datetime import datetime

def fetch_trakt_data(apikey, username):
    """Fetches watched movies data from Trakt API."""
    url = f"https://api.trakt.tv/users/{username}/watched/movies?limit=1000"
    headers = {
        "Content-Type": "application/json",
        "trakt-api-key": apikey,
        "trakt-api-version": "2"
    }

    response = requests.get(url, headers=headers)

    if response.status_code == 404:
        print("Wrong username!")
        return None

    if response.status_code != 200:
        print(f"Error fetching data: {response.status_code}")
        return None

    data = response.json()

    os.makedirs("files", exist_ok=True)
    json_filepath = os.path.join("files", "watched_movies.json")
    with open(json_filepath, "w") as f:
        json.dump(data, f, indent=4)

    print(f"Saved data to {json_filepath}")
    return json_filepath

def rename_dict_keys(dict_obj, pairs):
    """Renames keys in a dictionary based on provided pairs."""
    for pair in pairs:
        if pair[0] in dict_obj: # add check for existing keys.
            dict_obj[pair[1]] = dict_obj[pair[0]]
            del dict_obj[pair[0]]
    return dict_obj

def convert_to_csv(trakt_file, output_csv):
    """Converts Trakt JSON data to CSV format."""
    try:
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

                if 'movie' in item:
                    for key in sub_keys:
                        if key in item['movie']:
                            record[key] = item['movie'][key]

                    for key in id_keys:
                        record[key] = item['movie']['ids'].get(key, "")

                    for key in raw_keys:
                        if key in item:
                            record[key] = item[key]

                    pairs = [["title", "Title"], ["year", "Year"], ["imdb", "imdbID"], ["tmdb", "tmdbID"],
                             ["watched_at", "WatchedDate"]]
                    record = rename_dict_keys(record, pairs)
                    processed_data.append(record)

            df = pd.DataFrame(processed_data)
            csv_filepath = os.path.join("files", output_csv)
            df.to_csv(csv_filepath, index=False)
            print(f"Converted and saved to {csv_filepath}")
            return csv_filepath
    except FileNotFoundError:
        print(f"Error: File not found at {trakt_file}")
        return None
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON in {trakt_file}")
        return None
    except Exception as e:
        print(f"An unexpected error occurred: {e}")
        return None

def push_to_github():
    """Commits and pushes changes to GitHub."""
    os.system("git config --global user.name 'github-actions'")
    os.system("git config --global user.email 'github-actions@github.com'")
    os.system("git add files/watched_movies.json files/letterboxd.csv")
    os.system("git commit -m 'Update watched movies and letterboxd CSV' || echo 'No changes to commit'")
    os.system("git push")

def main():
    """Main function to orchestrate the data fetching, conversion, and push."""
    API_KEY = os.getenv("TRAKT_API_KEY")
    USERNAME = os.getenv("TRAKT_USERNAME")

    if not API_KEY or not USERNAME:
        print("Error: TRAKT_API_KEY and TRAKT_USERNAME environment variables must be set.")
        return

    json_filepath = fetch_trakt_data(API_KEY, USERNAME)
    if json_filepath:
        csv_filepath = convert_to_csv(json_filepath, "letterboxd.csv")
        if csv_filepath:
            push_to_github()

if __name__ == "__main__":
    main()