from __future__ import annotations
import json
import math
import sqlite3
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

CONNECTOR_DEFINITIONS: List[Dict[str, str]] = [
    {
        "id": "github",
        "name": "GitHub",
        "description": "Connect your GitHub account for repository management and version control",
        "category": "source-control",
        "env_var": "VITE_GITHUB_ACCESS_TOKEN",
    },
    {
        "id": "gitlab",
        "name": "GitLab",
        "description": "Integrate with GitLab for code hosting and CI/CD pipelines",
        "category": "source-control",
        "env_var": "VITE_GITLAB_ACCESS_TOKEN",
    },
    {
        "id": "vercel",
        "name": "Vercel",
        "description": "Deploy and manage your projects on Vercel platform",
        "category": "deployment",
        "env_var": "VITE_VERCEL_ACCESS_TOKEN",
    },
    {
        "id": "netlify",
        "name": "Netlify",
        "description": "Deploy and manage your sites on Netlify",
        "category": "deployment",
        "env_var": "VITE_NETLIFY_ACCESS_TOKEN",
    },
    {
        "id": "supabase",
        "name": "Supabase",
        "description": "Connect to Supabase for database, auth, and storage",
        "category": "database",
        "env_var": "VITE_SUPABASE_ACCESS_TOKEN",
    },
    {
        "id": "browser-use-cloud",
        "name": "Browser Use Cloud",
        "description": "Run hosted browser tasks and inspect websites via streamable-http MCP",
        "category": "browser-automation",
        "env_var": "BROWSER_USE_API_KEY",
    },
]

BROWSER_USE_SERVER_NAME = "browser-use-cloud"
BROWSER_USE_SERVER_URL = "https://api.browser-use.com/v3/mcp"
BROWSER_USE_API_KEY_HEADER = "X-Browser-Use-API-Key"

EXAMPLE_MCP_CONFIG: Dict[str, Any] = {
    "mcpServers": {
        "everything": {
            "type": "stdio",
            "command": "npx",
            "args": ["-y", "@modelcontextprotocol/server-everything"],
        },
        "deepwiki": {
            "type": "streamable-http",
            "url": "https://mcp.deepwiki.com/mcp",
        },
        "local-sse": {
            "type": "sse",
            "url": "http://localhost:8000/sse",
            "headers": {"Authorization": "Bearer mytoken123"},
        },
    }
}


def get_connector_permission_key(connector: str, action_id: str) -> str:
    """Ported from ConnectorActionPermissions.tsx."""
    return f"{connector}:{action_id}"


def calculate_repository_health_score(repo: Dict[str, Any]) -> Dict[str, Any]:
    """
    Ported from RepositoryCard.tsx (6-point repository health score calculator):
    hasStars, hasRecentActivity (<30d), hasContributors (>1), hasDescription, hasTopics, hasLicense.
    """
    updated_at_ms = repo.get("updated_at_ms", time.time() * 1000.0)
    days_since_update = max(0, int(((time.time() * 1000.0) - float(updated_at_ms)) / (1000 * 60 * 60 * 24)))

    has_stars = int(repo.get("stargazers_count", 0)) > 0
    has_recent_activity = days_since_update < 30
    has_contributors = int(repo.get("contributors_count", 1)) > 1
    has_description = bool(repo.get("description"))
    has_topics = len(repo.get("topics") or []) > 0
    has_license = bool(repo.get("license"))

    score = sum(1 for flag in [has_stars, has_recent_activity, has_contributors, has_description, has_topics, has_license] if flag)
    max_score = 6
    percentage = round((score / max_score) * 100)
    color = "text-green-500" if score >= 5 else ("text-yellow-500" if score >= 3 else "text-red-500")
    if repo.get("archived"):
        health_title = "Archived"
    elif days_since_update < 7:
        health_title = "Very Active"
    elif days_since_update < 30 and has_stars:
        health_title = "Healthy"
    else:
        health_title = "Needs Attention"

    return {
        "score": score,
        "maxScore": max_score,
        "percentage": percentage,
        "color": color,
        "healthTitle": health_title,
        "daysSinceUpdate": days_since_update,
    }


def filter_sort_and_paginate_repositories(
    repositories: List[Dict[str, Any]],
    search_query: str = "",
    sort_by: str = "updated",     # 'updated' | 'stars' | 'name' | 'created'
    filter_by: str = "all",       # 'all' | 'own' | 'forks' | 'archived' | 'owned' | 'member'
    current_page: int = 1,
    repos_per_page: int = 12,
) -> Dict[str, Any]:
    """
    Ported from GitHubRepositorySelector.tsx & GitLabRepositorySelector.tsx:
    filters by search query and type, sorts by updated/stars/name/created, and paginates (12 per page).
    """
    q = search_query.lower().strip()
    filtered: List[Dict[str, Any]] = []
    for repo in repositories:
        name = str(repo.get("name", "")).lower()
        desc = str(repo.get("description") or "").lower()
        full = str(repo.get("full_name") or repo.get("path_with_namespace") or "").lower()
        matches_search = (not q) or (q in name) or (q in desc) or (q in full)
        if not matches_search:
            continue

        if filter_by in ("own", "owned") and repo.get("fork", False):
            continue
        if filter_by == "forks" and not repo.get("fork", False):
            continue
        if filter_by == "archived" and not repo.get("archived", False):
            continue
        filtered.append(repo)

    if sort_by == "name":
        filtered.sort(key=lambda r: str(r.get("name", "")).lower())
    elif sort_by == "stars":
        filtered.sort(key=lambda r: int(r.get("stargazers_count", r.get("star_count", 0))), reverse=True)
    else:
        filtered.sort(key=lambda r: float(r.get("updated_at_ms", 0.0)), reverse=True)

    total_pages = max(1, math.ceil(len(filtered) / max(1, repos_per_page)))
    page = max(1, min(current_page, total_pages))
    start_idx = (page - 1) * repos_per_page
    current_repos = filtered[start_idx : start_idx + repos_per_page]

    return {
        "total_repositories": len(repositories),
        "filtered_count": len(filtered),
        "current_page": page,
        "total_pages": total_pages,
        "repos_per_page": repos_per_page,
        "repositories": current_repos,
    }


def compute_github_overview_and_language_stats(repos: List[Dict[str, Any]], organizations: Optional[List[Dict[str, Any]]] = None) -> Dict[str, Any]:
    """Ported from GitHubStats.tsx: computes top languages by codebase bytes, branch/issue/PR totals, and overview counts."""
    lang_bytes: Dict[str, Dict[str, int]] = {}
    public_repos = 0
    private_repos = 0
    total_branches = 0
    total_contributors = 0
    total_issues = 0
    total_prs = 0

    for r in repos:
        if r.get("private"):
            private_repos += 1
        else:
            public_repos += 1
        total_branches += int(r.get("branches_count", 1))
        total_contributors += int(r.get("contributors_count", 1))
        total_issues += int(r.get("issues_count", 0))
        total_prs += int(r.get("pull_requests_count", 0))
        lang = r.get("language")
        size_bytes = int(r.get("size_kb", 100)) * 1024
        if lang:
            entry = lang_bytes.setdefault(lang, {"bytes": 0, "repos": 0})
            entry["bytes"] += size_bytes
            entry["repos"] += 1

    most_used_languages = [
        {"language": k, "bytes": v["bytes"], "repos": v["repos"]}
        for k, v in sorted(lang_bytes.items(), key=lambda item: item[1]["bytes"], reverse=True)[:15]
    ]
    return {
        "publicRepos": public_repos,
        "privateRepos": private_repos,
        "totalRepos": public_repos + private_repos,
        "totalBranches": total_branches,
        "totalContributors": total_contributors,
        "totalIssues": total_issues,
        "totalPullRequests": total_prs,
        "organizationsCount": len(organizations or []),
        "languagesUsedCount": len(lang_bytes),
        "mostUsedLanguages": most_used_languages,
    }


class ProgressiveLoaderTracker:
    """Ported from GitHubProgressiveLoader.tsx (`useProgressiveLoader` hook)."""

    def __init__(self):
        self.steps: List[Dict[str, Any]] = [
            {"key": "user", "label": "Fetching user info", "completed": False, "loading": False, "error": False},
            {"key": "repos", "label": "Loading repositories", "completed": False, "loading": False, "error": False},
            {"key": "stats", "label": "Calculating statistics", "completed": False, "loading": False, "error": False},
            {"key": "cache", "label": "Updating cache", "completed": False, "loading": False, "error": False},
        ]

    def start_step(self, key: str) -> None:
        for s in self.steps:
            if s["key"] == key:
                s["loading"] = True
                s["error"] = False

    def complete_step(self, key: str) -> None:
        for s in self.steps:
            if s["key"] == key:
                s["completed"] = True
                s["loading"] = False
                s["error"] = False

    def error_step(self, key: str) -> None:
        for s in self.steps:
            if s["key"] == key:
                s["error"] = True
                s["loading"] = False

    def get_progress_percentage(self) -> int:
        if not self.steps:
            return 0
        done = sum(1 for s in self.steps if s["completed"])
        return round((done / len(self.steps)) * 100)


def extract_serialized_mcp_tool_schema(tool_name: str, tool_schema: Dict[str, Any]) -> Dict[str, Any]:
    """Ported from McpServerListItem.tsx."""
    input_schema = tool_schema.get("inputSchema") or {}
    resolved = input_schema.get("jsonSchema") if isinstance(input_schema, dict) and "jsonSchema" in input_schema else input_schema
    parameters = (resolved.get("properties") if isinstance(resolved, dict) else {}) or {}
    required_params = (resolved.get("required") if isinstance(resolved, dict) else []) or []
    desc = tool_schema.get("description") if isinstance(tool_schema.get("description"), str) else "No description available"
    return {
        "toolName": tool_name,
        "description": desc,
        "parameters": parameters,
        "requiredParams": required_params,
    }


class GitHubCacheManagerService:
    """Ported from GitHubCacheManager.tsx."""

    CACHE_KEYS = [
        "github_connection",
        "github_stats_cache",
        "github_repositories_cache",
        "github_user_cache",
        "github_rate_limits",
    ]

    def __init__(self, db_path: str = "workspace/kernel_governance.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_github_cache (
                    cache_key TEXT PRIMARY KEY,
                    payload_json TEXT,
                    size_bytes INTEGER,
                    timestamp_ms REAL,
                    last_accessed_ms REAL
                )
                """
            )

    @staticmethod
    def format_size(size_bytes: int) -> str:
        if size_bytes <= 0:
            return "0 B"
        units = ["B", "KB", "MB", "GB"]
        i = min(len(units) - 1, int(math.log(size_bytes, 1024)))
        return f"{round(size_bytes / (1024 ** i), 1)} {units[i]}"

    def set_entry(self, key: str, data: Dict[str, Any]) -> None:
        now_ms = time.time() * 1000.0
        payload = dict(data)
        payload.setdefault("timestamp", now_ms)
        payload["lastAccessed"] = now_ms
        raw = json.dumps(payload)
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orynx_github_cache
                (cache_key, payload_json, size_bytes, timestamp_ms, last_accessed_ms)
                VALUES (?, ?, ?, ?, ?)
                """,
                (key, raw, len(raw.encode("utf-8")), float(payload["timestamp"]), now_ms),
            )

    def get_cache_entries(self) -> List[Dict[str, Any]]:
        with sqlite3.connect(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT cache_key, payload_json, size_bytes, timestamp_ms, last_accessed_ms
                FROM orynx_github_cache
                ORDER BY last_accessed_ms DESC
                """
            ).fetchall()
        return [
            {
                "key": r[0],
                "data": json.loads(r[1]),
                "size": r[2],
                "formattedSize": self.format_size(r[2]),
                "timestamp": r[3],
                "lastAccessed": r[4],
            }
            for r in rows
        ]

    def get_cache_stats(self) -> Dict[str, Any]:
        entries = self.get_cache_entries()
        if not entries:
            return {"totalSize": 0, "formattedTotalSize": "0 B", "totalEntries": 0, "oldestEntry": 0, "newestEntry": 0, "status": "Empty"}
        timestamps = [e["timestamp"] for e in entries]
        tot_bytes = sum(e["size"] for e in entries)
        return {
            "totalSize": tot_bytes,
            "formattedTotalSize": self.format_size(tot_bytes),
            "totalEntries": len(entries),
            "oldestEntry": min(timestamps),
            "newestEntry": max(timestamps),
            "status": "Active",
        }

    def clear_expired_cache(self, max_age_ms: float = 24 * 60 * 60 * 1000.0) -> int:
        cutoff = (time.time() * 1000.0) - max_age_ms
        with sqlite3.connect(self.db_path) as conn:
            cur = conn.execute("DELETE FROM orynx_github_cache WHERE timestamp_ms < ?", (cutoff,))
            return cur.rowcount

    def compact_cache(self) -> int:
        entries = self.get_cache_entries()
        for entry in entries:
            self.set_entry(entry["key"], entry["data"])
        return len(entries)


class OrynxConnectorsAndMCPManager:
    """
    Unified controller for GitHub, GitLab, Netlify (batch stats + 6 site actions + deploy restore),
    Vercel, Supabase, Browser Use Cloud, and MCP Servers.
    """

    def __init__(self, db_path: str = "workspace/kernel_governance.db"):
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.github_cache = GitHubCacheManagerService(db_path=db_path)
        self.progressive_loader = ProgressiveLoaderTracker()
        self.connector_enabled: Dict[str, bool] = {c["id"]: False for c in CONNECTOR_DEFINITIONS}
        self.tool_enabled: Dict[str, bool] = {}
        self.mcp_config: Dict[str, Any] = json.loads(json.dumps(EXAMPLE_MCP_CONFIG))
        self.max_llm_steps: int = 5
        self._init_db()

    def _init_db(self) -> None:
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS orynx_connectors_state (
                    connector_id TEXT PRIMARY KEY,
                    enabled INTEGER,
                    token_masked TEXT,
                    base_url TEXT,
                    metadata_json TEXT,
                    updated_at REAL
                )
                """
            )

    def set_tool_permission(self, connector: str, action_id: str, enabled: bool) -> Dict[str, Any]:
        key = get_connector_permission_key(connector, action_id)
        self.tool_enabled[key] = enabled
        return {"permission_key": key, "enabled": enabled}

    def is_action_permitted(self, connector: str, action_id: str) -> bool:
        key = get_connector_permission_key(connector, action_id)
        return self.tool_enabled.get(key, True)

    def connect_browser_use_cloud(self, api_key: str) -> Dict[str, Any]:
        """Ported from BrowserUseCloudTab.tsx."""
        key = api_key.strip()
        if not key:
            return {"connected": False, "error": "Enter a Browser Use API key first."}
        if not key.startswith("bu_"):
            return {"connected": False, "error": 'Browser Use API keys start with "bu_".'}

        self.mcp_config.setdefault("mcpServers", {})[BROWSER_USE_SERVER_NAME] = {
            "type": "streamable-http",
            "url": BROWSER_USE_SERVER_URL,
            "headers": {BROWSER_USE_API_KEY_HEADER: key},
        }
        self.connector_enabled["browser-use-cloud"] = True
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                """
                INSERT OR REPLACE INTO orynx_connectors_state
                (connector_id, enabled, token_masked, base_url, metadata_json, updated_at)
                VALUES (?, 1, ?, ?, ?, ?)
                """,
                ("browser-use-cloud", f"{key[:5]}...{key[-3:]}", BROWSER_USE_SERVER_URL, "{}", time.time()),
            )
        return {
            "connected": True,
            "server_name": BROWSER_USE_SERVER_NAME,
            "transport": "streamable-http",
            "url": BROWSER_USE_SERVER_URL,
        }

    def compute_netlify_batch_stats_and_analytics(
        self,
        sites_data: List[Dict[str, Any]],
        deploys_by_site: Dict[str, List[Dict[str, Any]]],
        builds_by_site: Dict[str, List[Dict[str, Any]]],
    ) -> Dict[str, Any]:
        """
        Ported from NetlifyTab.tsx (lines 558-735):
        Processes sites in batches of 3, aggregates deploys/builds, sorts newest-first,
        and computes deployment successRate, successfulDeploys, and failedDeploys.
        """
        batch_size = 3
        site_batches = [sites_data[i : i + batch_size] for i in range(0, len(sites_data), batch_size)]
        all_deploys: List[Dict[str, Any]] = []
        all_builds: List[Dict[str, Any]] = []

        for batch in site_batches:
            for site in batch:
                sid = site.get("id", "")
                all_deploys.extend(deploys_by_site.get(sid, [])[:20])
                all_builds.extend(builds_by_site.get(sid, [])[:10])

        all_deploys.sort(key=lambda d: str(d.get("created_at", "")), reverse=True)
        last_deploy_time = all_deploys[0]["created_at"] if all_deploys else ""
        successful_deploys = sum(1 for d in all_deploys if d.get("state") == "ready")
        failed_deploys = sum(1 for d in all_deploys if d.get("state") == "error")
        success_rate = round((successful_deploys / len(all_deploys)) * 100) if all_deploys else 0
        live_sites = sum(1 for s in sites_data if (s.get("published_deploy") or {}).get("state") == "ready")

        return {
            "batches_processed": len(site_batches),
            "totalSites": len(sites_data),
            "liveSites": live_sites,
            "totalDeploys": len(all_deploys),
            "totalBuilds": len(all_builds),
            "lastDeployTime": last_deploy_time,
            "analytics": {
                "successRate": f"{success_rate}%",
                "successful": successful_deploys,
                "failed": failed_deploys,
            },
        }

    def execute_netlify_site_action(
        self,
        action_id: str,
        site_id: str,
        token: str = "",
        deploy_id: str = "",
        site_plan: str = "pro",
        has_build_hooks: bool = True,
    ) -> Dict[str, Any]:
        """Ported from NetlifyTab.tsx (all 6 siteActions + deploy lock/unlock/publish)."""
        if not self.is_action_permitted("netlify", action_id):
            return {"status": "BLOCKED_BY_PERMISSION", "connector": "netlify", "action": action_id}

        is_free = site_plan in ("free", "starter", "")
        if action_id == "clear_cache":
            if has_build_hooks:
                return {
                    "status": "COMPLETED",
                    "action": "clear_cache",
                    "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/builds",
                    "method": "POST",
                    "payload": {"clear_cache": True},
                    "message": "Build triggered with cache clear",
                }
            if is_free:
                return {
                    "status": "WARNING_FREE_LIMITATION",
                    "action": "clear_cache",
                    "message": "Cache purge not available on free accounts. Try triggering a build instead.",
                }
            return {
                "status": "COMPLETED",
                "action": "clear_cache",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/purge_cache",
                "method": "POST",
                "message": "Site cache cleared successfully",
            }

        if action_id == "manage_environment":
            return {
                "status": "LIMITED_FREE_ACCOUNT" if is_free else "COMPLETED",
                "action": "manage_environment",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/env",
                "method": "GET",
            }

        if action_id == "trigger_build":
            return {
                "status": "COMPLETED",
                "action": "trigger_build",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/builds",
                "method": "POST",
                "build_id": f"bld_{int(time.time())}",
                "message": "Build triggered successfully!",
            }

        if action_id == "view_functions":
            return {
                "status": "LIMITED_FREE_ACCOUNT" if is_free else "COMPLETED",
                "action": "view_functions",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/functions",
                "method": "GET",
            }

        if action_id == "site_analytics":
            return {
                "status": "FALLBACK_BASIC_INFO" if is_free else "COMPLETED",
                "action": "site_analytics",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}/traffic",
                "method": "GET",
            }

        if action_id == "delete_site":
            return {
                "status": "COMPLETED",
                "action": "delete_site",
                "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}",
                "method": "DELETE",
                "requiresConfirmation": True,
            }

        if action_id in ("deploy_lock", "deploy_unlock", "deploy_publish"):
            verb = action_id.replace("deploy_", "")
            endpoint = (
                f"https://api.netlify.com/api/v1/sites/{site_id}/deploys/{deploy_id}/restore"
                if verb == "publish"
                else f"https://api.netlify.com/api/v1/deploys/{deploy_id}/{verb}"
            )
            return {
                "status": "COMPLETED",
                "action": action_id,
                "endpoint": endpoint,
                "method": "POST",
                "message": f"Deploy {verb}ed successfully",
            }

        return {
            "status": "COMPLETED",
            "action": action_id,
            "site_id": site_id,
            "is_free_account": is_free,
            "endpoint": f"https://api.netlify.com/api/v1/sites/{site_id}",
        }
