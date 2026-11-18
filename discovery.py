"""
discovery.py – Discovers publicly accessible HackerOne bug-bounty programs.

Two data sources are supported in priority order:

  1. HackerOne public GraphQL endpoint (https://hackerone.com/graphql)
     – Powers the public program directory at hackerone.com/directory/programs
     – Works WITHOUT API credentials
     – Returns publicly listed programs and public statistics

  2. HackerOne v1 REST API (https://api.hackerone.com/v1/hackers/programs)
     – Requires HTTP Basic Auth (H1_API_USERNAME + H1_API_TOKEN)
     – Used as fallback if GraphQL is unavailable

No private programs, private reports, or restricted information is accessed.
Queries mirror the public HackerOne directory. Authentication, CAPTCHAs, and
access controls are never bypassed.
"""

from __future__ import annotations

import json
import os
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

import config
from logger import get_logger

log = get_logger("discovery")

# Current public directory query. Argument names match HackerOne's live schema:
# teams(first, after, secure_order_by, where) — not product_type / orderBy.
_GQL_DIRECTORY_QUERY = """
query DirectoryPrograms($after: String) {
  teams(
    first: 50
    after: $after
    secure_order_by: {started_accepting_at: {_direction: DESC}}
    where: {
      _and: [
        {_or: [
          {submission_state: {_eq: open}},
          {external_program: {}}
        ]}
        {_not: {external_program: {}}}
        {_or: [
          {_and: [
            {state: {_neq: sandboxed}},
            {state: {_neq: soft_launched}}
          ]}
          {external_program: {}}
        ]}
      ]
    }
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      handle
      name
      started_accepting_at
      website
      url
      state
      submission_state
      offers_bounties
      offers_swag
      response_efficiency_percentage
      reports_received_last_90_days
      most_recent_sla_snapshot {
        average_time_to_first_program_response
        average_time_to_report_triage
        average_time_to_report_resolved
        average_time_to_bounty_awarded
      }
    }
  }
}
"""

# Fallback if reports_received_last_90_days is not selectable on Team.
_GQL_DIRECTORY_QUERY_NO_VOLUME = """
query DirectoryPrograms($after: String) {
  teams(
    first: 50
    after: $after
    secure_order_by: {started_accepting_at: {_direction: DESC}}
    where: {
      _and: [
        {_or: [
          {submission_state: {_eq: open}},
          {external_program: {}}
        ]}
        {_not: {external_program: {}}}
        {_or: [
          {_and: [
            {state: {_neq: sandboxed}},
            {state: {_neq: soft_launched}}
          ]}
          {external_program: {}}
        ]}
      ]
    }
  ) {
    pageInfo {
      hasNextPage
      endCursor
    }
    nodes {
      handle
      name
      started_accepting_at
      website
      url
      state
      submission_state
      offers_bounties
      offers_swag
      response_efficiency_percentage
      most_recent_sla_snapshot {
        average_time_to_first_program_response
        average_time_to_report_triage
        average_time_to_report_resolved
        average_time_to_bounty_awarded
      }
    }
  }
}
"""

_GQL_TEAM_DETAIL = """
query TeamPublicMetrics($handle: String!) {
  team(handle: $handle) {
    handle
    name
    started_accepting_at
    website
    url
    state
    submission_state
    offers_bounties
    response_efficiency_percentage
    reports_received_last_90_days
    most_recent_sla_snapshot {
      average_time_to_first_program_response
      average_time_to_report_triage
      average_time_to_report_resolved
      average_time_to_bounty_awarded
    }
  }
}
"""


def _retry_adapter() -> HTTPAdapter:
    # Retry transient connection/read failures here. HTTP status retries are
    # handled explicitly below so 429 Retry-After is bounded and predictable.
    retry = Retry(
        total=config.MAX_RETRIES,
        connect=config.MAX_RETRIES,
        read=config.MAX_RETRIES,
        status=0,
        backoff_factor=config.RETRY_BACKOFF_FACTOR,
        allowed_methods=frozenset({"GET", "POST"}),
        raise_on_status=False,
    )
    return HTTPAdapter(max_retries=retry)


def _build_graphql_session() -> requests.Session:
    """Session for the public GraphQL endpoint, including directory CSRF cookie."""
    session = requests.Session()
    session.headers.update({
        **config.DEFAULT_HEADERS,
        "Content-Type": "application/json",
        "Origin": "https://hackerone.com",
        "Referer": config.HACKERONE_DIRECTORY_URL,
    })
    session.mount("https://", _retry_adapter())

    try:
        resp = session.get(
            config.HACKERONE_DIRECTORY_URL,
            timeout=30,
            headers={"Accept": "text/html,application/xhtml+xml"},
        )
        resp.raise_for_status()
    except requests.RequestException as exc:
        log.warning("Could not load public directory page for CSRF bootstrap: %s", exc)
        return session

    csrf = None
    match = re.search(
        r'<meta[^>]+name=["\']csrf-token["\'][^>]+content=["\']([^"\']+)["\']',
        resp.text,
        re.IGNORECASE,
    )
    if not match:
        match = re.search(
            r'name=["\']csrf-token["\']\s+content=["\']([^"\']+)["\']',
            resp.text,
            re.IGNORECASE,
        )
    if match:
        csrf = match.group(1)
        session.headers["X-Csrf-Token"] = csrf
        log.debug("Public directory CSRF token acquired.")
    else:
        log.warning("No csrf-token meta tag on directory page; continuing without it.")
    return session


def _build_api_session() -> requests.Session:
    session = requests.Session()
    session.headers.update(config.DEFAULT_HEADERS)
    if config.H1_API_USERNAME and config.H1_API_TOKEN:
        session.auth = (config.H1_API_USERNAME, config.H1_API_TOKEN)
    session.mount("https://", _retry_adapter())
    return session


def _graphql_post(
    session: requests.Session,
    query: str,
    variables: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """POST a public GraphQL query with bounded handling for rate limits."""
    for attempt in range(config.MAX_RETRIES + 1):
        try:
            resp = session.post(
                config.HACKERONE_GRAPHQL_URL,
                json={"query": query, "variables": variables},
                timeout=30,
            )
        except requests.RequestException as exc:
            log.error("GraphQL request failed: %s", exc)
            return None

        if resp.status_code == 429:
            if attempt >= config.MAX_RETRIES:
                log.error("GraphQL rate limit persisted after %d retries.", config.MAX_RETRIES)
                return None
            retry_after = resp.headers.get("Retry-After", "")
            try:
                wait_seconds = max(1, min(int(retry_after), 120))
            except (TypeError, ValueError):
                wait_seconds = min(
                    config.RETRY_BACKOFF_FACTOR ** attempt * 5,
                    60,
                )
            log.warning(
                "GraphQL rate-limited (attempt %d/%d); waiting %d seconds.",
                attempt + 1, config.MAX_RETRIES, wait_seconds,
            )
            time.sleep(wait_seconds)
            continue

        if not resp.ok:
            log.error("GraphQL HTTP error %d: %s", resp.status_code, resp.text[:300])
            return None

        try:
            data = resp.json()
        except ValueError as exc:
            log.error("GraphQL JSON decode error: %s", exc)
            return None

        if not isinstance(data, dict):
            log.error("GraphQL returned an unexpected JSON structure.")
            return None

        if data.get("errors"):
            for err in data["errors"]:
                log.warning("GraphQL error: %s", err.get("message", err))
            if not data.get("data"):
                return None
        return data

    return None


def normalize_graphql_node(node: Dict[str, Any]) -> Dict[str, Any]:
    """
    Convert a GraphQL team node into the REST-like envelope used by program_parser.
    """
    sla = node.get("most_recent_sla_snapshot") or {}
    attrs: Dict[str, Any] = {
        "handle": node.get("handle", ""),
        "name": node.get("name", ""),
        "started_accepting_at": node.get("started_accepting_at"),
        "offers_bounties": node.get("offers_bounties", False),
        "state": node.get("state", ""),
        "submission_state": node.get("submission_state", ""),
        "website": node.get("website", ""),
        "url": node.get("url", ""),
        "reports_received_last_90_days": node.get("reports_received_last_90_days"),
        "reports_received_in_last_90_days": node.get("reports_received_last_90_days"),
        "average_time_to_first_program_response": sla.get(
            "average_time_to_first_program_response"
        ),
        "average_time_to_triage": sla.get("average_time_to_report_triage"),
        "average_time_to_report_resolved": sla.get("average_time_to_report_resolved"),
        "average_time_to_bounty_awarded": sla.get("average_time_to_bounty_awarded"),
        "response_efficiency_percentage": node.get("response_efficiency_percentage"),
        "data_source": "HackerOne Public GraphQL",
    }
    return {"id": node.get("handle") or node.get("id") or "", "attributes": attrs}


def _cache_path() -> str:
    os.makedirs(config.OUTPUT_DIR, exist_ok=True)
    return os.path.join(config.OUTPUT_DIR, config.CACHE_FILENAME)


def load_cached_programs(force_refresh: bool = False) -> Optional[List[Dict[str, Any]]]:
    if force_refresh:
        return None
    path = _cache_path()
    if not os.path.isfile(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as fh:
            payload = json.load(fh)
    except (OSError, ValueError) as exc:
        log.warning("Could not read program cache: %s", exc)
        return None

    fetched_at = payload.get("fetched_at")
    programs = payload.get("programs")
    if not fetched_at or not isinstance(programs, list):
        log.warning("Program cache has an invalid structure; ignoring it.")
        return None
    try:
        cached_time = datetime.fromisoformat(fetched_at)
        if cached_time.tzinfo is None:
            cached_time = cached_time.replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    age = datetime.now(timezone.utc) - cached_time
    if age > timedelta(hours=config.CACHE_TTL_HOURS):
        log.info("Program cache is stale (%.1f h old).", age.total_seconds() / 3600)
        return None
    log.info("Using cached discovery (%d programs, %.1f h old).", len(programs), age.total_seconds() / 3600)
    return programs


def save_cached_programs(programs: List[Dict[str, Any]]) -> None:
    path = _cache_path()
    payload = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "programs": programs,
    }
    temp_path = path + ".tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False)
        os.replace(temp_path, path)
        log.debug("Wrote program cache -> %s", path)
    except OSError as exc:
        log.warning("Could not write program cache: %s", exc)
        try:
            if os.path.exists(temp_path):
                os.remove(temp_path)
        except OSError:
            pass


def discover_via_graphql(
    page_size: int = 50,
    max_programs: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Discover publicly listed programs using the unauthenticated GraphQL API."""
    session = _build_graphql_session()
    log.info("Starting GraphQL discovery (page size capped at 50 by the public schema) …")

    query = _GQL_DIRECTORY_QUERY
    programs: List[Dict[str, Any]] = []
    seen_handles: set = set()
    cursor: Optional[str] = None
    page_num = 1
    switched_query = False

    while True:
        log.debug("Fetching GraphQL page %d (cursor=%s) …", page_num, cursor or "start")
        variables: Dict[str, Any] = {}
        if cursor:
            variables["after"] = cursor

        raw = _graphql_post(session, query, variables)
        if raw is None:
            if query == _GQL_DIRECTORY_QUERY and not switched_query and page_num == 1:
                log.warning(
                    "Directory query with 90-day volume failed. "
                    "Retrying without reports_received_last_90_days."
                )
                query = _GQL_DIRECTORY_QUERY_NO_VOLUME
                switched_query = True
                continue
            log.error("GraphQL page %d returned no data – stopping.", page_num)
            break

        teams_data = (raw.get("data") or {}).get("teams") or {}
        nodes = teams_data.get("nodes") or []
        # Older schema variants used edges { node }
        if not nodes and teams_data.get("edges"):
            nodes = [edge.get("node") or {} for edge in teams_data["edges"]]

        page_info = teams_data.get("pageInfo") or {}
        if not nodes:
            log.debug("Empty GraphQL page – stopping pagination.")
            break

        for node in nodes:
            handle = (node.get("handle") or "").strip()
            if not handle or handle in seen_handles:
                continue
            seen_handles.add(handle)
            programs.append(normalize_graphql_node(node))
            if max_programs and len(programs) >= max_programs:
                log.info("Program limit (%d) reached.", max_programs)
                session.close()
                return programs

        has_next = page_info.get("hasNextPage", False)
        cursor = page_info.get("endCursor")
        log.info(
            "Page %d: +%d programs (total: %d, hasNextPage: %s)",
            page_num, len(nodes), len(programs), has_next,
        )
        if not has_next or not cursor:
            break

        page_num += 1
        time.sleep(config.REQUEST_DELAY_SECONDS)

    session.close()
    log.info("GraphQL discovery complete – %d unique programs.", len(programs))
    return programs


def discover_via_rest_api(
    page_size: int = config.DEFAULT_PAGE_SIZE,
    max_programs: Optional[int] = config.MAX_PROGRAMS,
) -> List[Dict[str, Any]]:
    """Fetch programs via the authenticated HackerOne v1 REST API.

    The HackerOne hackers endpoint requires HTTP Basic authentication.
    Pagination links are restricted to api.hackerone.com to avoid forwarding
    credentials to an unexpected host.
    """
    if not (config.H1_API_USERNAME and config.H1_API_TOKEN):
        log.error(
            "REST API requires credentials. Set H1_API_USERNAME and "
            "H1_API_TOKEN in the environment or .env file."
        )
        return []

    from urllib.parse import urlparse

    session = _build_api_session()
    log.info("Using authenticated REST API …")
    programs: List[Dict[str, Any]] = []
    seen: set = set()
    url = config.HACKERONE_PROGRAMS_ENDPOINT
    params: Dict[str, Any] = {"page[size]": min(max(1, page_size), 100)}
    page_num = 1

    try:
        while url:
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.hostname != "api.hackerone.com":
                log.error("Refusing unexpected REST pagination URL: %s", url)
                break

            response = None
            for attempt in range(config.MAX_RETRIES + 1):
                try:
                    response = session.get(url, params=params, timeout=30)
                except requests.RequestException as exc:
                    log.error("REST request failed: %s", exc)
                    response = None
                    break

                if response.status_code != 429:
                    break
                if attempt >= config.MAX_RETRIES:
                    log.error("REST rate limit persisted after %d retries; stopping.", config.MAX_RETRIES)
                    break
                retry_after = response.headers.get("Retry-After", "")
                try:
                    wait = max(1, min(int(retry_after), 120))
                except (TypeError, ValueError):
                    wait = min(config.RETRY_BACKOFF_FACTOR ** attempt * 5, 60)
                log.warning("REST rate-limited (attempt %d/%d). Waiting %d seconds.",
                            attempt + 1, config.MAX_RETRIES, wait)
                time.sleep(wait)

            if response is None:
                break
            if response.status_code == 401:
                log.error(
                    "REST API returned 401 Unauthorized. Verify the API username "
                    "and token; public discovery should use GraphQL instead."
                )
                break
            if not response.ok:
                log.error("REST API error %d: %s", response.status_code, response.text[:200])
                break

            try:
                payload = response.json()
            except ValueError:
                log.error("Failed to decode REST API response as JSON.")
                break
            if not isinstance(payload, dict):
                log.error("REST API returned an unexpected response structure.")
                break

            for program in payload.get("data", []) or []:
                if not isinstance(program, dict):
                    continue
                attrs = program.get("attributes") or {}
                attrs["data_source"] = "HackerOne REST API v1"
                handle = attrs.get("handle") or program.get("id", "")
                if handle and handle not in seen:
                    seen.add(handle)
                    programs.append(program)
                    if max_programs and len(programs) >= max_programs:
                        log.info("Program limit (%d) reached.", max_programs)
                        return programs

            next_url = (payload.get("links") or {}).get("next")
            if not next_url:
                break
            url = next_url
            params = {}
            page_num += 1
            time.sleep(config.REQUEST_DELAY_SECONDS)
    finally:
        session.close()

    log.info("REST API discovery complete – %d programs.", len(programs))
    return programs

def discover_programs(
    page_size: int = config.DEFAULT_PAGE_SIZE,
    max_programs: Optional[int] = config.MAX_PROGRAMS,
    refresh: bool = False,
) -> List[Dict[str, Any]]:
    """
    Discover publicly listed HackerOne programs.

    Strategy:
      1. Reuse a fresh local cache unless --refresh is set.
      2. Query the public GraphQL directory (no credentials).
      3. Fall back to the authenticated v1 REST API when GraphQL fails
         and credentials are available.
    """
    log.info("=== Program Discovery ===")

    cached = load_cached_programs(force_refresh=refresh)
    if cached:
        return cached[:max_programs] if max_programs else cached

    log.info("Trying public GraphQL endpoint (no credentials required) …")
    # Cache the complete directory, not a --limit-truncated subset.
    programs = discover_via_graphql(page_size=page_size, max_programs=None)
    if programs:
        log.info("GraphQL discovery succeeded: %d programs found.", len(programs))
        save_cached_programs(programs)
        return programs[:max_programs] if max_programs else programs

    log.warning("GraphQL returned 0 programs. Trying REST API fallback …")
    if config.H1_API_USERNAME and config.H1_API_TOKEN:
        programs = discover_via_rest_api(page_size=page_size, max_programs=None)
        if programs:
            log.info("REST API fallback succeeded: %d programs.", len(programs))
            save_cached_programs(programs)
            return programs[:max_programs] if max_programs else programs
    else:
        log.error(
            "GraphQL discovery returned no results and no API credentials are set.\n"
            "  Optional REST fallback:\n"
            "    Create a .env file with H1_API_USERNAME and H1_API_TOKEN\n"
            "    Token page: https://hackerone.com/settings/api_token/edit"
        )
    return []


def fetch_program_detail_graphql(handle: str, session: Optional[requests.Session] = None) -> Optional[Dict[str, Any]]:
    """Fetch public metrics for one program via GraphQL. Returns normalised attrs or None."""
    own_session = session is None
    session = session or _build_graphql_session()
    raw = _graphql_post(session, _GQL_TEAM_DETAIL, {"handle": handle})
    if own_session:
        session.close()
    if not raw:
        return None
    node = (raw.get("data") or {}).get("team")
    if not node:
        return None
    return normalize_graphql_node(node).get("attributes")


def fetch_program_detail(handle: str) -> Optional[Dict[str, Any]]:
    """
    Fetch full public profile for a single program.
    Prefers GraphQL; REST is used only when credentials exist and GraphQL fails.
    """
    gql = fetch_program_detail_graphql(handle)
    if gql:
        return {"attributes": gql}

    if not (config.H1_API_USERNAME and config.H1_API_TOKEN):
        return None

    session = _build_api_session()
    url = config.HACKERONE_PROGRAM_DETAIL_ENDPOINT.format(handle=handle)
    try:
        resp = session.get(url, timeout=30)
        if not resp.ok:
            log.error("Detail fetch failed for '%s': HTTP %d", handle, resp.status_code)
            return None
        return resp.json().get("data")
    except requests.RequestException as exc:
        log.error("Network error fetching '%s': %s", handle, exc)
        return None
    finally:
        time.sleep(config.REQUEST_DELAY_SECONDS)
        session.close()
