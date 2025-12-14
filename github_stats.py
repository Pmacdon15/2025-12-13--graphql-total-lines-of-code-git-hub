import os
import getpass
import requests
from rich.console import Console
from rich.progress import Progress
from rich.panel import Panel
from rich.text import Text
from dotenv import load_dotenv

load_dotenv()

GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

def graphql_request(query, variables, token):
    """Executes a GraphQL query to the GitHub API."""
    headers = {"Authorization": f"Bearer {token}"}
    response = requests.post(
        GITHUB_GRAPHQL_URL,
        json={"query": query, "variables": variables},
        headers=headers,
    )
    response.raise_for_status()
    return response.json()

GET_REPOSITORIES_QUERY = """
query GetRepositories($username: String!, $cursor: String) {
  user(login: $username) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false, orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo {
        endCursor
        hasNextPage
      }
      nodes {
        name
        owner {
          login
        }
      }
    }
  }
}
"""

GET_COMMITS_QUERY = """
query GetCommits($owner: String!, $name: String!, $cursor: String, $since: GitTimestamp) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, since: $since) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
              additions
              deletions
            }
          }
        }
      }
    }
  }
}
"""

def get_all_repositories(username, token):
    """Fetches all repository names for a user."""
    repos = []
    cursor = None
    has_next_page = True
    while has_next_page:
        variables = {"username": username, "cursor": cursor}
        data = graphql_request(GET_REPOSITORIES_QUERY, variables, token)
        repo_data = data.get("data", {}).get("user", {}).get("repositories", {})
        repos.extend(repo_data.get("nodes", []))
        page_info = repo_data.get("pageInfo", {})
        cursor = page_info.get("endCursor")
        has_next_page = page_info.get("hasNextPage", False)
    return repos

def get_commit_stats(owner, name, token):
    """Fetches commit statistics for a single repository."""
    total_additions = 0
    total_deletions = 0
    cursor = None
    has_next_page = True
    while has_next_page:
        variables = {"owner": owner, "name": name, "cursor": cursor}
        data = graphql_request(GET_COMMITS_QUERY, variables, token)
        
        repo = data.get("data", {}).get("repository")
        if not repo or not repo.get("defaultBranchRef") or not repo["defaultBranchRef"].get("target"):
            break 
            
        history = repo["defaultBranchRef"]["target"]["history"]
        for commit in history.get("nodes", []):
            total_additions += commit.get("additions", 0)
            total_deletions += commit.get("deletions", 0)
            
        page_info = history.get("pageInfo", {})
        cursor = page_info.get("endCursor")
        has_next_page = page_info.get("hasNextPage", False)
        
    return total_additions, total_deletions

def main():
    """Main function to run the script."""
    console = Console()
    console.print(Panel("[bold cyan]GitHub Repository Stats[/bold cyan]", expand=False))

    username = os.getenv("GITHUB_USERNAME")
    if not username:
        username = console.input("Enter your GitHub username: ")

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        token = getpass.getpass("Enter your GitHub Personal Access Token: ")

    try:
        with Progress(console=console) as progress:
            repo_task = progress.add_task("[cyan]Fetching repositories...", total=None)
            repositories = get_all_repositories(username, token)
            progress.update(repo_task, completed=len(repositories), total=len(repositories), description=f"[green]Found {len(repositories)} repositories.")

            total_additions = 0
            total_deletions = 0

            commit_task = progress.add_task("[cyan]Analyzing commits...", total=len(repositories))
            for repo in repositories:
                if not repo: continue
                owner = repo["owner"]["login"]
                name = repo["name"]
                
                additions, deletions = get_commit_stats(owner, name, token)
                total_additions += additions
                total_deletions += deletions
                progress.update(commit_task, advance=1, description=f"[cyan]Analyzing [bold]{owner}/{name}[/bold]")

        additions_text = Text(f"Total Additions: {total_additions}", style="bold green")
        deletions_text = Text(f"Total Deletions: {total_deletions}", style="bold red")
        
        summary_panel = Panel(
            Text.assemble(additions_text, "\n", deletions_text),
            title="[bold]Overall Stats[/bold]",
            border_style="blue"
        )
        console.print(summary_panel)

    except requests.exceptions.HTTPError as e:
        console.print(f"[bold red]Error:[/bold red] Failed to fetch data from GitHub. Status code: {e.response.status_code}")
        if e.response.status_code == 401:
            console.print("[yellow]Please check that your Personal Access Token is correct and has the necessary 'repo' scopes.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")

if __name__ == "__main__":
    main()