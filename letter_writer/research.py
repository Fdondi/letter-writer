from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

from langsmith import traceable

from .client import get_client
from .clients.base import ModelVendor, ModelSize, BaseClient
from .firestore_store import (
    get_company_info,
    save_company_info,
    get_collection,
    get_poc_info,
    save_poc_info,
    save_company_alias,
    search_similar_companies,
)
from .generation import company_research
from .retrieval import retrieve_similar_job_offers, select_top_documents

logger = logging.getLogger(__name__)


def _parse_model_str(model_str: str) -> Tuple[ModelVendor, str | ModelSize]:
    """Parse 'vendor/model' or 'vendor' string."""
    parts = model_str.split("/", 1)
    try:
        vendor = ModelVendor(parts[0])
    except ValueError:
        raise ValueError(
            f"Unknown vendor '{parts[0]}' in model string '{model_str}'. "
            f"Valid vendors: {[v.value for v in ModelVendor]}"
        )
        
    if len(parts) > 1:
        return vendor, parts[1]
    return vendor, ModelSize.LARGE


def _norm_company(s: str) -> str:
    return " ".join((s or "").strip().lower().split())


def _looks_like_same_company(query: str, candidate: str) -> bool:
    """Heuristic decision for aliasing query company to an existing cached company."""
    q = _norm_company(query)
    c = _norm_company(candidate)
    if not q or not c:
        return False
    if q == c:
        return True
    if len(q) >= 5 and (q in c or c in q):
        return True
    ratio = SequenceMatcher(a=q, b=c).ratio()
    if ratio >= 0.86:
        return True
    q_tokens = set(q.replace("-", " ").split())
    c_tokens = set(c.replace("-", " ").split())
    if q_tokens and c_tokens:
        jaccard = len(q_tokens & c_tokens) / len(q_tokens | c_tokens)
        if jaccard >= 0.8:
            return True
    return False


@traceable(run_type="chain", name="perform_web_search")
def perform_web_search(query: str) -> str:
    """Perform a web search using a capable model (OpenAI for now)."""
    try:
        # Use an explicit search-capable OpenAI model.
        client = get_client(ModelVendor.OPENAI)
        system = "You are a research assistant. Perform a comprehensive web search for the user's query and return a detailed summary of the findings, including key facts, recent news, and relevant context."
        return client.call("gpt-5-search-api", system, [query], search=True)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return ""


@traceable(run_type="chain", name="perform_company_research")
def perform_company_research(
    company_name: str,
    models: List[str],
    job_text: str,
    additional_company_info: str = "",
) -> Dict[str, Any]:
    """
    Perform company research using one or more models.
    Checks for cached data (< 6 months old) and reuses it if available.
    
    Returns:
        {"results": Dict[model_id, {...}], "source": "cache"|"similar"|"new",
         "resolved_name": str}
    """
    if not company_name:
        return {"results": {}, "source": "new", "resolved_name": company_name}

    # 1. Check exact cache first.
    cached_info = get_company_info(company_name)
    matched_company_name = company_name
    matched_doc_id = None
    previous_context = ""
    found_via_search = False
    logger.debug(
        "[RESEARCH] Exact cache lookup for '%s': %s",
        company_name,
        "HIT" if cached_info else "MISS",
    )

    # 1b. If exact is missing, try vector-similar companies and decide if one matches.
    if not cached_info:
        try:
            candidates = search_similar_companies(company_name, limit=5)
        except Exception as e:
            logger.warning("Company vector lookup failed for '%s': %s", company_name, e)
            candidates = []
        chosen = None
        for c in candidates:
            candidate_name = c.get("company_name") or ""
            if _looks_like_same_company(company_name, candidate_name):
                chosen = c
                break
        logger.debug("[RESEARCH] Vector search for '%s': %s candidates", company_name, len(candidates))
        for c in candidates:
            cname = c.get("company_name", "?")
            logger.debug(
                "[RESEARCH]   candidate: '%s' - match=%s",
                cname,
                _looks_like_same_company(company_name, cname),
            )
        if chosen is not None:
            matched_company_name = chosen.get("company_name") or company_name
            matched_doc_id = chosen.get("id")
            cached_info = chosen
            found_via_search = True
            logger.info(
                "[RESEARCH] Matched '%s' -> '%s' (doc_id=%s)",
                company_name,
                matched_company_name,
                matched_doc_id,
            )
            if matched_doc_id:
                try:
                    save_company_alias(
                        alias_company_name=company_name,
                        canonical_doc_id=str(matched_doc_id),
                        canonical_company_name=matched_company_name,
                    )
                except Exception as e:
                    logger.warning("Failed to save company alias '%s' -> '%s': %s", company_name, matched_doc_id, e)
    
    if cached_info:
        updated_at = cached_info.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None
        
        if updated_at:
            cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            cached_reports = cached_info.get("reports", {})
            requested_set = set(models)
            cached_set = set(cached_reports.keys())
            cache_covers_request = requested_set.issubset(cached_set)
            
            if updated_at > cutoff and cache_covers_request:
                source = "similar" if found_via_search else "cache"
                logger.info(
                    "Using cached company research for '%s' (resolved to '%s', source=%s)",
                    company_name, matched_company_name, source,
                )
                return {
                    "results": {k: v for k, v in cached_reports.items() if k in requested_set},
                    "source": source,
                    "resolved_name": matched_company_name,
                }
            else:
                if not cache_covers_request:
                    logger.info(
                        "Cached research for '%s' (resolved to '%s') doesn't cover requested models "
                        "(cached: %s, requested: %s). Re-running.",
                        company_name, matched_company_name, cached_set, requested_set,
                    )
                else:
                    logger.info(
                        "Cached research for '%s' (resolved to '%s') is older than 6 months. Using as context.",
                        company_name, matched_company_name,
                    )
                if cached_reports:
                    best_report = max(cached_reports.values(), key=lambda x: len(x.get("report", "")), default={})
                    previous_context = best_report.get("report", "")

    # 2. Perform new consolidated research (once)
    logger.info(f"Performing new research for {company_name}")
    
    # Retrieval (Vector Search)
    collection = get_collection()
    from openai import OpenAI
    try:
        openai_client = OpenAI()
    except Exception:
        logger.warning("Could not instantiate OpenAI client for retrieval. Research might be limited.")
        openai_client = None

    search_result = []
    if openai_client:
        try:
            search_result = retrieve_similar_job_offers(job_text, collection, openai_client)
        except Exception as e:
            logger.error(f"Retrieval failed: {e}")

    # Web Search (once)
    web_search_query = f"Research company {company_name}"
    
    web_context = perform_web_search(web_search_query)
    
    # Combine context
    combined_context = additional_company_info
    if previous_context:
        combined_context += f"\n\n[Previous Research Context (older than 6 months)]:\n{previous_context}"
    if web_context:
        combined_context += f"\n\n[Web Search Findings]:\n{web_context}"

    results = {}

    def process_model(model_str: str):
        try:
            vendor, model_id = _parse_model_str(model_str)
            client = get_client(vendor)
            trace_dir = Path("trace", f"{company_name}.{vendor.value}.research")
            trace_dir.mkdir(parents=True, exist_ok=True)
            
            # Select top docs (reranking) - might differ slightly per vendor model but usually similar
            # Reranking is cheap/fast enough to do per model, or we could do it once.
            # `select_top_documents` uses the client to rerank/select.
            result = select_top_documents(search_result, job_text, client, trace_dir)
            top_docs = result["top_docs"]
            
            # Generate report using consolidated context (search=False)
            report = company_research(
                company_name, 
                job_text, 
                client, 
                trace_dir, 
                additional_company_info=combined_context,
                search=False,  # Disable individual model search, rely on context
                model=model_id
            )
            
            return model_str, {
                "report": report,
                "top_docs": top_docs,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"Research failed for {model_str}: {e}")
            return model_str, {"error": str(e)}

    # Run in parallel
    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_model, m) for m in models]
        for future in futures:
            m_str, data = future.result()
            results[m_str] = data

    # 3. Save to cache
    save_company_info(company_name, {"reports": results})
    
    return {"results": results, "source": "new", "resolved_name": company_name}


@traceable(run_type="chain", name="perform_poc_research")
def perform_poc_research(
    poc_name: str,
    models: List[str],
    company_name: str,
    job_text: str = "",
) -> Dict[str, dict]:
    """
    Perform POC research using one or more models.
    Checks for cached data (< 6 months old) and reuses it if available.
    """
    if not poc_name or not company_name:
        return {}

    # 1. Check cache
    cached_info = get_poc_info(company_name, poc_name)
    previous_context = ""
    
    if cached_info:
        updated_at = cached_info.get("updated_at")
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None
        
        if updated_at:
            cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            cached_reports = cached_info.get("reports", {})
            requested_set = set(models)
            cached_set = set(cached_reports.keys())
            cache_covers_request = requested_set.issubset(cached_set)
            
            if updated_at > cutoff and cache_covers_request:
                logger.info(f"Using cached POC research for {poc_name} (covers requested models)")
                return {k: v for k, v in cached_reports.items() if k in requested_set}
            else:
                if not cache_covers_request:
                    logger.info(f"Cached POC research for {poc_name} doesn't cover requested models. Re-running.")
                else:
                    logger.info(f"Cached research for {poc_name} is older than 6 months. Using as context.")
                if cached_reports:
                    best_report = max(cached_reports.values(), key=lambda x: len(x.get("report", "")), default={})
                    previous_context = best_report.get("report", "")

    # 2. Perform new research
    logger.info(f"Performing new research for {poc_name}")
    
    # Consolidated Web Search (once)
    web_search_query = f"Research {poc_name} at {company_name}"
    if job_text:
        web_search_query += f"\nContext from job offer: {job_text[:200]}..."
        
    web_context = perform_web_search(web_search_query)
    
    combined_context = ""
    if previous_context:
        combined_context += f"\n\n[Previous Research Context (older than 6 months)]:\n{previous_context}"
    if web_context:
        combined_context += f"\n\n[Web Search Findings]:\n{web_context}"

    results = {}

    def process_model(model_str):
        try:
            vendor, model_id = _parse_model_str(model_str)
            client = get_client(vendor)
            trace_dir = Path("trace", f"{poc_name}.{vendor.value}.research_poc")
            trace_dir.mkdir(parents=True, exist_ok=True)
            
            prompt = f"Research the following person: {poc_name} at {company_name}"
            if job_text:
                prompt += f"\n\nContext from job offer:\n{job_text[:500]}..."
            
            if combined_context:
                prompt += f"\n\nResearch Findings:\n{combined_context}"
                
            prompt += "\n\nProvide a professional summary about this person, their role, and any public information relevant for a job application."
            
            # Simple generation
            messages = [{"role": "user", "content": prompt}]
            # We assume client.call supports simple generation via BaseClient.call if we implemented it, 
            # but BaseClient.call is the standard way now.
            # BaseClient.call(model_size, system, messages, search=False)
            
            report = client.call(model_id, "You are a professional research assistant.", [prompt], search=False)
            
            return model_str, {
                "report": report,
                "updated_at": datetime.now(timezone.utc).isoformat()
            }
        except Exception as e:
            logger.error(f"POC research failed for {model_str}: {e}")
            return model_str, {"error": str(e)}

    with ThreadPoolExecutor() as executor:
        futures = [executor.submit(process_model, m) for m in models]
        for future in futures:
            m_str, data = future.result()
            results[m_str] = data

    # 3. Save to cache
    save_poc_info(company_name, poc_name, {"reports": results})
    
    return results
