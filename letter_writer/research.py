from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any
from concurrent.futures import ThreadPoolExecutor

from .client import get_client
from .clients.base import ModelVendor, ModelSize, BaseClient
from .firestore_store import get_company_info, save_company_info, get_collection, get_poc_info, save_poc_info
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


def perform_web_search(query: str) -> str:
    """Perform a web search using a capable model (OpenAI for now)."""
    try:
        # Use OpenAI for reliable web search
        client = get_client(ModelVendor.OPENAI)
        system = "You are a research assistant. Perform a comprehensive web search for the user's query and return a detailed summary of the findings, including key facts, recent news, and relevant context."
        return client.call(ModelSize.LARGE, system, [query], search=True)
    except Exception as e:
        logger.error(f"Web search failed: {e}")
        return ""


def perform_company_research(
    company_name: str,
    user_id: str,
    models: List[str],
    job_text: str,
    point_of_contact: Optional[dict] = None,
    additional_company_info: str = "",
) -> Dict[str, dict]:
    """
    Perform company research using one or more models.
    Checks for cached data (< 6 months old) and reuses it if available.
    
    Returns:
        Dict[str, dict]: Map of model_id -> { "report": str, "top_docs": list }
    """
    if not company_name:
        return {}

    # 1. Check cache
    cached_info = get_company_info(company_name, user_id)
    previous_context = ""
    
    # If we have valid cache for requested models, we might return it?
    # But usually we want fresh research if cache is old.
    # Also, we need to return results for ALL requested models.
    # If cache has some models but not others, or old data...
    
    # Simplified logic:
    # - If cache is fresh (< 6 months), return it (all available reports).
    # - If cache is old, use it as context for new research.
    
    if cached_info:
        updated_at = cached_info.get("updated_at")
        # Ensure updated_at is timezone-aware
        if isinstance(updated_at, str):
            try:
                updated_at = datetime.fromisoformat(updated_at.replace("Z", "+00:00"))
            except ValueError:
                updated_at = None
        
        if updated_at:
            # Check if fresh (less than 6 months old)
            cutoff = datetime.now(timezone.utc) - timedelta(days=180)
            cached_reports = cached_info.get("reports", {})
            # Only use cache if it covers ALL requested models
            requested_set = set(models)
            cached_set = set(cached_reports.keys())
            cache_covers_request = requested_set.issubset(cached_set)
            
            if updated_at > cutoff and cache_covers_request:
                logger.info(f"Using cached company research for {company_name} (covers requested models)")
                # Return only the requested model results from cache
                return {k: v for k, v in cached_reports.items() if k in requested_set}
            else:
                if not cache_covers_request:
                    logger.info(f"Cached research for {company_name} doesn't cover requested models "
                                f"(cached: {cached_set}, requested: {requested_set}). Re-running.")
                else:
                    logger.info(f"Cached research for {company_name} is older than 6 months. Using as context.")
                # Use the most recent report as context (pick first available)
                if cached_reports:
                    # Pick a report, preferably a long one
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
    if point_of_contact:
        poc_name = point_of_contact.get("name")
        if poc_name:
            web_search_query += f" and point of contact {poc_name}"
    
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
            top_docs = select_top_documents(search_result, job_text, client, trace_dir)
            
            # Generate report using consolidated context (search=False)
            report = company_research(
                company_name, 
                job_text, 
                client, 
                trace_dir, 
                point_of_contact=point_of_contact, 
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
    save_company_info(company_name, {"reports": results}, user_id)
    
    return results


def perform_poc_research(
    poc_name: str,
    user_id: str,
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
    cached_info = get_poc_info(company_name, poc_name, user_id)
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
    save_poc_info(company_name, poc_name, {"reports": results}, user_id)
    
    return results
