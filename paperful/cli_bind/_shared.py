"""Shared option objects and enums for the command signatures."""

from __future__ import annotations

from enum import Enum

import typer


def _cfg(path=None):
    """Resolve config at call time so tests can patch ``cli_runtime._cfg``."""
    from paperful import cli_runtime as rt

    return rt._cfg(path)


ConfigOpt = typer.Option(
    None, "--config", "-c", help="Path to config.toml", exists=True, dir_okay=False
)
AgentFormatOpt = typer.Option(
    "text",
    "--format",
    help="text (default) or json for agents. JSON is paperful.agent.json.v1.",
)
FetchPdfsOpt = typer.Option(
    None,
    "--fetch-pdfs",
    help="PDF mode after create: off, fast, or full. true means fast. Default: config, else off.",
)
MaxCandidatesOpt = typer.Option(
    None,
    "--max-candidates",
    help="Stop after this many new+exists rows. Use all for every row.",
)
PerHopLimitOpt = typer.Option(
    None,
    "--per-hop-limit",
    help="Neighbours per seed per hop. Use all for every neighbour.",
)
PerHopRankOpt = typer.Option(
    None,
    "--per-hop-rank",
    help="Which neighbours a numeric limit keeps: most-cited, least-cited, or random.",
)
PrioritizeOpt = typer.Option(
    None,
    "--prioritize",
    help=(
        "Hop-0 search order: recency, popular (citation count, default), or historical. "
        "Not topical relevance. Neighbour hops still use overlap rank."
    ),
)
KeywordLimitOpt = typer.Option(
    None,
    "--keyword-limit",
    help="How many of a work's OpenAlex keywords to expand (1–5). 5 uses every stored keyword. all is refused.",
)
KeywordHopLimitOpt = typer.Option(
    None,
    "--keyword-hop-limit",
    help="Works kept per seed on the keyword side. A positive integer. all is refused.",
)
KeywordMinScoreOpt = typer.Option(
    None,
    "--keyword-min-score",
    help="Drop seed keywords below this similarity. 0 keeps whatever OpenAlex assigned.",
)
SearchKeywordsOpt = typer.Option(
    None,
    "--search-keywords/--no-search-keywords",
    help=(
        "On keyword search/hybrid, also pull works tagged with matching OpenAlex keywords "
        "(union with full-text hits). Default: config, else on."
    ),
)
CitesQueryOpt = typer.Option(
    None,
    "--cites-query",
    help=(
        "Only references and citing works that match this OpenAlex search "
        "(title, abstract, or full text). Needs refs or cites in the direction, and depth of at least 1."
    ),
)
StudyDesignOpt = typer.Option(
    [],
    "--study-design",
    help=(
        "OpenAlex study design filter (repeatable or comma-separated). "
        "Ids: randomized-controlled-trial, clinical-trial, observational-study, "
        "case-report, systematic-review, meta-analysis, study-protocol. "
        "Aliases: rct, meta, sr, observational, protocol, case, trial."
    ),
)
ListedInOpt = typer.Option(
    [],
    "--listed-in",
    help=(
        "OpenAlex trusted journal list filter (repeatable or comma-separated). "
        "Ids: doaj, medline, jufo-3, latindex, scielo, … "
        "Family aliases: cwts, jufo, norway, ki-jl, jpps, abdc. "
        "Membership is the maintainer’s list, not a quality score."
    ),
)
CreateTagOpt = typer.Option(
    [],
    "--tag",
    help="Extra tags on created parents (repeatable). Combined with config default_tags and from-<seed-slug>.",
)
DedupeScopeOpt = typer.Option(
    None,
    "--dedupe-scope",
    help="library, collection, or none. Crawl default: config/profile. apply defaults to library unless this flag is set.",
)
DedupeAfterOpt = typer.Option(
    None,
    "--dedupe-after",
    help="After create: off (default), classify, or apply. classify writes state/dedupe-packs/.",
)
AuthorSitePreflightOpt = typer.Option(
    None,
    "--author-site-preflight/--no-author-site-preflight",
    help="Opt-in co-author graph and proposed field pack. Default: config.",
)
StopRuleOpt = typer.Option(
    None,
    "--stop-rule",
    help=(
        "off, marginal_yield, asymptotic_coverage, budget, or any. "
        "Off walks every hop in one shot. A rule pauses after each hop for Keep/Skip. "
        "Default: config, else off."
    ),
)
StopEpsOpt = typer.Option(
    None,
    "--stop-eps",
    help="marginal_yield: Keep rate below this. Default 0.01.",
)
StopKOpt = typer.Option(
    None,
    "--stop-k",
    help="Consecutive low-yield iterations. The rule cannot fire before iteration k+1. Default 2.",
)
StopMaxScreenedOpt = typer.Option(
    None,
    "--stop-max-screened",
    help="budget: stop after this many screened new rows. 0 means no cap.",
)
TwentyWritebackOpt = typer.Option(
    None,
    "--twenty-writeback/--no-twenty-writeback",
    help=(
        "Append SearXNG or author-site personal pages onto a unique Twenty Person. "
        "Does not create People. Default: \\[twenty].writeback_listings (off)."
    ),
)
RequestRgOpt = typer.Option(
    None,
    "--request-rg/--no-request-rg",
    help=(
        "Open existing ResearchGate publication URLs in the system browser "
        "so you can click Request full-text. Paperful never clicks. Default: \\[request].channels."
    ),
)
ReRequestOpt = typer.Option(
    False,
    "--re-request",
    help="Open ResearchGate handoff tabs even if state/author-requests.jsonl already recorded them.",
)
SeedsFileOpt = typer.Option(
    None,
    "--seeds-file",
    help="One DOI or ORCID per line (# comments). Use - to read stdin.",
)
DIRECTION_HELP = (
    "refs, cites, both, keywords, similar, refs+keywords, cites+keywords, "
    "refs+similar, or refs+cites+keywords. both stays references plus cited-by."
)
ProfileOpt = typer.Option(
    None,
    "--profile",
    help="Named run config from \\[profiles.*] or profiles/<name>.toml beside config.toml.",
)
RunConfigFileOpt = typer.Option(
    None,
    "--run-config",
    "-f",
    help="Run-config TOML file. Overlays --profile when both are set.",
    exists=True,
    dir_okay=False,
)
LibraryOpt = typer.Option(
    None,
    "--library/--no-library",
    help="Whole library instead of --collection. --no-library clears library = true on a profile.",
)
YearFromOpt = typer.Option(
    None,
    "--year-from",
    help="Only items dated this year or later (inclusive). Undated items excluded.",
)
YearToOpt = typer.Option(
    None,
    "--year-to",
    help="Only items dated this year or earlier (inclusive). Undated items excluded.",
)
ItemTypeOpt = typer.Option(
    [],
    "--type",
    "-T",
    help=(
        "Only these Zotero item types (repeatable or comma-separated; "
        "e.g. journalArticle, 'Journal Article', report)."
    ),
)
TryAllOpt = typer.Option(
    None,
    "--try-all/--no-try-all",
    help=(
        "Try every configured source even when item metadata looks inapplicable. "
        "--no-try-all turns a profile default off."
    ),
)
RetryFailedOpt = typer.Option(
    None,
    "--retry-failed/--no-retry-failed",
    help="Retry items previously marked not_found. --no-retry-failed turns a profile default off.",
)
UpgradeLinkedOpt = typer.Option(
    None,
    "--upgrade-linked/--no-upgrade-linked",
    help=(
        "Also fetch items that only have a linked PDF URL. "
        "--no-upgrade-linked turns a profile default off."
    ),
)
UpgradeSnapshotOpt = typer.Option(
    None,
    "--upgrade-snapshot/--no-upgrade-snapshot",
    help=(
        "Re-fetch items whose only PDF is an HTML page snapshot. "
        "A native PDF replaces the snapshot unless --keep-snapshot."
    ),
)
NoAttachOpt = typer.Option(
    None,
    "--no-attach/--attach",
    help="Do not attach PDFs into Zotero. --attach turns a profile's no_attach off.",
)
StrictPdfDoiOpt = typer.Option(
    None,
    "--strict-pdf-doi/--no-strict-pdf-doi",
    help=(
        "Save a PDF whose DOI differs from the library item, but do not attach it. "
        "--no-strict-pdf-doi turns a profile default off."
    ),
)
EzproxyReloginOpt = typer.Option(
    None,
    "--ezproxy-relogin/--no-ezproxy-relogin",
    help=(
        "After a run, pause to re-login when the EZProxy session expired, "
        "then retry those items. Default follows ezproxy_relogin in config (on)."
    ),
)
SciHubOpt = typer.Option(
    None,
    "--scihub/--no-scihub",
    help=(
        "Opt in to Sci-Hub for this run (off by default; legal grey zone in some jurisdictions). "
        "--no-scihub turns a profile default off."
    ),
)
BrowserAgentOpt = typer.Option(
    None,
    "--browser-agent/--no-browser-agent",
    help=(
        "Auto-append the browser-agent recover lane when llm.enabled "
        "(default: \\[browser_agent].during_run). "
        "--no-browser-agent skips it for this run so other PDF lanes can be tested alone."
    ),
)
CamofoxOpt = typer.Option(
    None,
    "--camofox/--no-camofox",
    help=(
        "Auto-append the camofox recover lane when \\[camofox].enabled "
        "(default: \\[camofox].during_run). "
        "Needs an external camofox-browser server at \\[camofox].base_url. "
        "See docs/camofox.md."
    ),
)
ApplyOpt = typer.Option(
    None,
    "--apply/--no-apply",
    help="Write changes (metadata, summaries, or optional steps). --no-apply keeps the dry-run.",
)
OverwriteOpt = typer.Option(
    None,
    "--overwrite/--no-overwrite",
    help="Replace title/date/venue even when already set.",
)
StepsOpt = typer.Option(
    None,
    "--steps",
    help="Comma-separated commands, replacing the profile step list.",
)
SkipOpt = typer.Option(
    [],
    "--skip",
    help="Omit this step (repeatable or comma-separated).",
)


class WriteDest(str, Enum):
    disk = "disk"
    zotero = "zotero"
    both = "both"


class SummarizeOrder(str, Enum):
    newest = "newest"
    oldest = "oldest"
    library = "library"
