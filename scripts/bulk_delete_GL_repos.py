import requests

# GitLab Personal Access Token
TOKEN = "YOUR_ACCESS_TOKEN"

# Base URL for GitLab API
GITLAB_URL = "https://gitlab.com/api/v4"

# Repositories to keep (replace with your actual repo names)
KEEP_REPOS = ["repo-to-keep-1", "repo-to-keep-2"]

# Headers for authentication
HEADERS = {"PRIVATE-TOKEN": TOKEN}


def get_all_projects():
    """Fetch all projects owned by the user."""
    projects = []
    page = 1

    while True:
        response = requests.get(
            f"{GITLAB_URL}/projects?owned=true&per_page=100&page={page}",
            headers=HEADERS,
        )
        if response.status_code != 200:
            print("Error fetching repositories:", response.text)
            return []

        data = response.json()
        if not data:
            break  # No more pages

        projects.extend(data)
        page += 1

    return projects


def delete_project(project_id, name):
    """Delete a given project by ID."""
    url = f"{GITLAB_URL}/projects/{project_id}"
    response = requests.delete(url, headers=HEADERS)

    if response.status_code == 202:
        print(f"✅ Deleted: {name}")
    else:
        print(f"❌ Failed to delete {name}: {response.text}")


def main():
    projects = get_all_projects()

    if not projects:
        print("No repositories found or failed to fetch.")
        return

    print(f"Found {len(projects)} repositories.")

    for project in projects:
        name = project["name"]
        project_id = project["id"]

        if name in KEEP_REPOS:
            print(f"Skipping {name} (kept)")
        else:
            delete_project(project_id, name)

    print("✅ Finished deleting repositories (except the ones you kept)!")


if __name__ == "__main__":
    main()
