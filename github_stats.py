import os
import getpass
import requests
from datetime import datetime, timezone
from rich.console import Console
from rich.progress import Progress, track
from rich.panel import Panel
from rich.text import Text
from dotenv import load_dotenv
from concurrent.futures import ThreadPoolExecutor
from itertools import repeat

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

GET_USER_SUMMARY_QUERY = """
query GetUserSummary($username: String!) {
  user(login: $username) {
    id
    createdAt
    followers {
      totalCount
    }
    following {
      totalCount
    }
    repositories(ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC) {
      totalCount
    }
    pullRequests {
      totalCount
    }
    issues {
      totalCount
    }
  }
}
"""

GET_REPOSITORIES_QUERY = """
query GetRepositories($username: String!, $cursor: String) {
  user(login: $username) {
    repositories(first: 100, after: $cursor, ownerAffiliations: OWNER, isFork: false, privacy: PUBLIC, orderBy: {field: PUSHED_AT, direction: DESC}) {
      pageInfo {
        endCursor
        hasNextPage
      }
      nodes {
        name
        owner {
          login
        }
        stargazerCount
        forkCount
        languages(first: 10, orderBy: {field: SIZE, direction: DESC}) {
          edges {
            size
            node {
              name
              color
            }
          }
        }
      }
    }
  }
}
"""

GET_COMMITS_QUERY = """
query GetCommits($owner: String!, $name: String!, $cursor: String, $authorId: ID!) {
  repository(owner: $owner, name: $name) {
    defaultBranchRef {
      target {
        ... on Commit {
          history(first: 100, after: $cursor, author: {id: $authorId}) {
            pageInfo {
              endCursor
              hasNextPage
            }
            nodes {
              additions
              deletions
              committedDate
            }
          }
        }
      }
    }
  }
}
"""

def get_user_summary_stats(username, token):
    """Fetches high-level stats for a user that are quick to retrieve."""
    variables = {"username": username}
    data = graphql_request(GET_USER_SUMMARY_QUERY, variables, token)
    user_data = data.get("data", {}).get("user", {})
    return {
        "id": user_data.get("id"),
        "createdAt": user_data.get("createdAt"),
        "followers": user_data.get("followers", {}).get("totalCount", 0),
        "following": user_data.get("following", {}).get("totalCount", 0),
        "repos": user_data.get("repositories", {}).get("totalCount", 0),
        "prs": user_data.get("pullRequests", {}).get("totalCount", 0),
        "issues": user_data.get("issues", {}).get("totalCount", 0),
    }

def get_all_repositories(username, token):
    """Fetches all repository data for a user."""
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

def get_commit_stats(owner, name, token, author_id):
    """Fetches commit statistics for a single repository, filtered by author."""
    total_additions, total_deletions, total_commits = 0, 0, 0
    earliest_date, latest_date = None, None
    cursor = None
    has_next_page = True
    while has_next_page:
        try:
            variables = {"owner": owner, "name": name, "cursor": cursor, "authorId": author_id}
            data = graphql_request(GET_COMMITS_QUERY, variables, token)
            
            repo = data.get("data", {}).get("repository")
            if not repo or not repo.get("defaultBranchRef") or not repo["defaultBranchRef"].get("target"):
                break 
                
            history = repo["defaultBranchRef"]["target"]["history"]
            commits = history.get("nodes", [])
            if not commits:
                break

            total_commits += len(commits)
            
            for commit in commits:
                total_additions += commit.get("additions", 0)
                total_deletions += commit.get("deletions", 0)
                commit_date = datetime.fromisoformat(commit["committedDate"].replace("Z", "+00:00"))
                
                if earliest_date is None or commit_date < earliest_date:
                    earliest_date = commit_date
                if latest_date is None or commit_date > latest_date:
                    latest_date = commit_date

            page_info = history.get("pageInfo", {})
            cursor = page_info.get("endCursor")
            has_next_page = page_info.get("hasNextPage", False)
        except Exception:
            # Ignore errors for single repo analysis (e.g., empty repo)
            has_next_page = False
        
    return total_additions, total_deletions, total_commits, earliest_date, latest_date

def main():
    """Main function to run the script."""
    console = Console()
    console.print(Panel("[bold cyan]GitHub User Stats[/bold cyan]", expand=False, border_style="blue"))

    username = os.getenv("GITHUB_USERNAME")
    if not username:
        username = console.input("Enter your GitHub username: ")

    token = os.getenv("GITHUB_TOKEN")
    if not token:
        console.print("[yellow]Note: A GitHub Personal Access Token is required to avoid rate limiting and access private repository data.[/yellow]")
        token = getpass.getpass("Enter your GitHub Personal Access Token: ")

    try:
        with console.status("[bold green]Fetching quick summary stats...[/]"):
            summary_stats = get_user_summary_stats(username, token)
            author_id = summary_stats.get("id")

        created_at_str = summary_stats.get("createdAt")
        created_at_dt = datetime.fromisoformat(created_at_str.replace("Z", "+00:00"))
        time_on_github = datetime.now(timezone.utc) - created_at_dt
        
        summary_text = Text.assemble(
            Text(f"User Since: {created_at_dt.strftime('%B %d, %Y')}", style="bold"),
            f" (~{time_on_github.days // 365} years, { (time_on_github.days % 365) // 30} months)\n",
            Text(f"Followers: {summary_stats['followers']}", style="bold"), " | ",
            Text(f"Following: {summary_stats['following']}\n", style="bold"),
            Text(f"Total Public Repositories: {summary_stats['repos']}", style="bold"),
            "\n",
            Text(f"Total Pull Requests: {summary_stats['prs']}", style="bold"),
            "\n",
            Text(f"Total Issues: {summary_stats['issues']}", style="bold"),
        )
        console.print(Panel(summary_text, title="[bold]Quick Summary[/bold]", border_style="green"))
        
        console.print("\n[cyan]Now starting detailed analysis (this may take a while)...[/cyan]")

        with console.status("[bold green]Fetching repositories & languages...[/]"):
            repositories = get_all_repositories(username, token)
        console.print(f"[green]Found {len(repositories)} public repositories to analyze.[/green]")
        
        language_stats = {}
        total_lang_size = 0
        for repo in repositories:
            if not repo or not repo.get('languages'): continue
            for lang_edge in repo['languages']['edges']:
                node = lang_edge['node']
                if not node: continue
                lang_name = node['name']
                lang_color = node.get('color', 'white')
                lang_size = lang_edge['size']
                total_lang_size += lang_size
                if lang_name in language_stats:
                    language_stats[lang_name]['size'] += lang_size
                else:
                    language_stats[lang_name] = {'size': lang_size, 'color': lang_color}
        
        most_popular_repo = max(repositories, key=lambda r: r['stargazerCount']) if repositories else None

        total_additions, total_deletions, total_commits = 0, 0, 0
        first_commit_date, latest_commit_date = None, None
        
        owners = [repo["owner"]["login"] for repo in repositories]
        names = [repo["name"] for repo in repositories]

        with ThreadPoolExecutor(max_workers=10) as executor:
            results = executor.map(get_commit_stats, owners, names, repeat(token), repeat(author_id))
            
            for result in track(results, console=console, total=len(repositories), description="[cyan]Analyzing your commits...    "):
                add, dele, com, earliest, latest = result
                total_additions += add
                total_deletions += dele
                total_commits += com

                if earliest and (first_commit_date is None or earliest < first_commit_date):
                    first_commit_date = earliest
                if latest and (latest_commit_date is None or latest > latest_commit_date):
                    latest_commit_date = latest

        # Display Language Stats
        sorted_languages = sorted(language_stats.items(), key=lambda item: item[1]['size'], reverse=True)
        lang_text_parts = []
        if sorted_languages:
            for lang, data in sorted_languages[:7]: # Show top 7
                percentage = (data['size'] / total_lang_size) * 100 if total_lang_size > 0 else 0
                lang_text_parts.append(Text(f"● {lang}: {percentage:.2f}%\n", style=data['color']))
            console.print(Panel(Text.assemble(*lang_text_parts), title="[bold]Language Breakdown[/bold]", border_style="magenta"))

        # Display Detailed Code Stats
        coding_lifespan = latest_commit_date - first_commit_date if first_commit_date and latest_commit_date else None
        
        detailed_text_parts = []
        if most_popular_repo:
            detailed_text_parts.extend([
                Text("Most Popular Repo:", style="bold"),
                f" {most_popular_repo['name']} (⭐️ {most_popular_repo['stargazerCount']} / 🔱 {most_popular_repo['forkCount']})\n"
            ])

        detailed_text_parts.extend([
            Text(f"First Commit: {first_commit_date.strftime('%B %d, %Y') if first_commit_date else 'N/A'}", style="bold"),
            "\n",
            Text(f"Latest Commit: {latest_commit_date.strftime('%B %d, %Y') if latest_commit_date else 'N/A'}", style="bold"),
            "\n",
        ])
        if coding_lifespan and coding_lifespan.days > 0:
            detailed_text_parts.append(f"Coding Lifespan: {coding_lifespan.days // 365} years, {(coding_lifespan.days % 365) // 30} months\n")

        detailed_text_parts.extend([
            Text(f"Your Total Commits: {total_commits}", style="bold yellow"),
            "\n",
            Text(f"Your Total Lines Added: {total_additions}", style="bold green"),
            "\n",
            Text(f"Your Total Lines Deleted: {total_deletions}", style="bold red"),
        ])
        
        console.print(Panel(Text.assemble(*detailed_text_parts), title="[bold]Detailed Code Stats[/bold]", border_style="blue"))

    except requests.exceptions.HTTPError as e:
        console.print(f"[bold red]Error:[/bold red] Failed to fetch data from GitHub. Status code: {e.response.status_code}")
        if e.response.status_code == 401:
            console.print("[yellow]Please check that your Personal Access Token is correct and has the necessary 'repo' scopes.[/yellow]")
    except Exception as e:
        console.print(f"[bold red]An unexpected error occurred:[/bold red] {e}")

if __name__ == "__main__":
    main()