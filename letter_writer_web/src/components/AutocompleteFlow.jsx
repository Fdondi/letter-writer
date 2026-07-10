/**
 * Standalone autocomplete flow: Tab completes, Space accepts.
 * Letter is split into sections (title + description for LLM; body for final copy).
 */

import React, { useCallback, useEffect, useMemo, useRef, useState } from "react";
import JobDescriptionColumn from "./JobDescriptionColumn";
import AutocompleteModelPanel from "./AutocompleteModelPanel";
import AutocompleteSectionsEditor from "./AutocompleteSectionsEditor";
import SaveAndCopyButton, {
  SaveCopyErrorBanner,
  useSaveAndCopy,
} from "./SaveAndCopyButton";
import { fetchWithHeartbeat } from "../utils/apiHelpers";
import { useTranslation } from "../utils/useTranslation";
import {
  acceptSuggestion,
  defaultCycleModels,
  normalizeStoredModels,
  parseModelKey,
  readSessionCycleModels,
  readSessionPlanModel,
  buildAutocompleteDraftScope,
  buildAutocompleteDraftPrefix,
  readStoredAutocompleteSections,
  sectionsToBodyText,
  sectionsToProposalText,
  shouldAcceptOnSpace,
  resolveCompletionModel,
  suggestionAlreadyAtCursor,
  writeSessionCycleModels,
  writeSessionPlanModel,
  writeStoredAutocompleteSections,
  cloneDefaultAutocompleteSections,
  createAutocompleteSuggestionHistory,
  createEmptyCompletionCache,
  isSectionProposalStale,
  canUseProposalAutocompleteBuffer,
  shouldUseCompletionModelForSection,
  buildSectionProposalAutocompleteBuffer,
  isProposalAutocompleteCache,
  PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE,
  sliceNextAutocompleteChunk,
  shouldExtendAutocompleteCache,
} from "../utils/autocompleteEditor";

export default function AutocompleteFlow({
  jobText,
  additionalUserInfo = "",
  additionalCompanyInfo = "",
  structureInstructions = "",
  companyReport = "",
  topDocs = [],
  companyName = "",
  jobTitle = "",
  location = "",
  language = "",
  salary = "",
  requirements = [],
  competences = {},
  competenceScaleConfig,
  competenceOverrides = {},
  languages = [],
  pointOfContact = null,
  onSaveAndCopy,
  savingFinal = false,
}) {
  const draftScope = useMemo(
    () => buildAutocompleteDraftScope({ companyName, jobTitle, jobText }),
    [companyName, jobTitle, jobText]
  );
  const draftScopeRef = useRef(draftScope);
  const [sections, setSections] = useState(() => readStoredAutocompleteSections(draftScope));
  const [activeSectionIndex, setActiveSectionIndex] = useState(0);
  const [cursorInSection, setCursorInSection] = useState(0);
  const [suggestion, setSuggestion] = useState("");
  const [modelUsed, setModelUsed] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState(null);
  const [statusMeta, setStatusMeta] = useState(null);
  const [settings, setSettings] = useState({
    autocomplete_max_words: 20,
    autocomplete_stop_on_period: true,
    autocomplete_models: [],
    autocomplete_role_defaults: {},
    autocomplete_plan_role_defaults: {},
    autocomplete_plan_model: "",
  });
  const [settingsFetched, setSettingsFetched] = useState(false);
  const [cycleModels, setCycleModels] = useState([]);
  const [completionModel, setCompletionModel] = useState("");
  const [planModel, setPlanModel] = useState("");
  const [planningSectionIndices, setPlanningSectionIndices] = useState(() => new Set());
  const [planError, setPlanError] = useState(null);
  const [contextSummary, setContextSummary] = useState("");
  const [contextSummaryWarnings, setContextSummaryWarnings] = useState([]);
  const totalCostRef = useRef(0);
  const planCostRef = useRef(0);
  const suggestionHistoryRef = useRef(null);
  if (!suggestionHistoryRef.current) {
    suggestionHistoryRef.current = createAutocompleteSuggestionHistory();
  }
  const cycleInitializedRef = useRef(false);
  const planInitializedRef = useRef(false);
  const planRequestIdsRef = useRef({});
  const planBatchRequestIdRef = useRef(0);
  const lastAutoPlannedScopeRef = useRef(null);
  const completionCacheRef = useRef(createEmptyCompletionCache());
  const extendCacheInFlightRef = useRef(false);

  const textareaRefs = useRef({});
  const requestIdRef = useRef(0);
  const translation = useTranslation();

  const bodyText = useMemo(() => sectionsToBodyText(sections), [sections]);

  useEffect(() => {
    writeStoredAutocompleteSections(sections, draftScope);
  }, [sections, draftScope]);

  useEffect(() => {
    if (draftScopeRef.current === draftScope) return;
    draftScopeRef.current = draftScope;
    setSections(readStoredAutocompleteSections(draftScope));
    setActiveSectionIndex(0);
    setCursorInSection(0);
    setSuggestion("");
    suggestionHistoryRef.current = createAutocompleteSuggestionHistory();
    completionCacheRef.current = createEmptyCompletionCache();
    extendCacheInFlightRef.current = false;
    totalCostRef.current = 0;
    planCostRef.current = 0;
    lastAutoPlannedScopeRef.current = null;
    setPlanningSectionIndices(new Set());
    setContextSummary("");
    setContextSummaryWarnings([]);
  }, [draftScope]);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await fetch("/api/personal-data/", { credentials: "include" });
        if (!res.ok) return;
        const data = await res.json();
        if (cancelled) return;
        setSettings((prev) => ({
          ...prev,
          autocomplete_max_words: data.autocomplete_max_words ?? prev.autocomplete_max_words,
          autocomplete_stop_on_period:
            data.autocomplete_stop_on_period ?? prev.autocomplete_stop_on_period,
          autocomplete_models: data.autocomplete_models ?? prev.autocomplete_models,
          autocomplete_role_defaults:
            data.autocomplete_role_defaults ?? prev.autocomplete_role_defaults,
          autocomplete_plan_role_defaults:
            data.autocomplete_plan_role_defaults ?? prev.autocomplete_plan_role_defaults,
          autocomplete_plan_model: data.autocomplete_plan_model ?? prev.autocomplete_plan_model,
        }));
        setSettingsFetched(true);
      } catch (e) {
        console.warn("Failed to load autocomplete settings", e);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  useEffect(() => {
    if (!settingsFetched || cycleInitializedRef.current) return;
    cycleInitializedRef.current = true;
    const defaults = settings.autocomplete_role_defaults || {};
    const persisted = normalizeStoredModels(settings.autocomplete_models, defaults);
    const baseline = persisted.length ? persisted : defaultCycleModels(defaults);
    const fromSession = readSessionCycleModels();
    const sessionNorm = fromSession?.length ? normalizeStoredModels(fromSession, defaults) : null;
    const nextCycle = sessionNorm?.length ? sessionNorm : baseline;
    setCycleModels(nextCycle);
    setCompletionModel((prev) => prev || nextCycle[0] || "");
  }, [settingsFetched, settings.autocomplete_models, settings.autocomplete_role_defaults]);

  useEffect(() => {
    if (!settingsFetched || planInitializedRef.current) return;
    planInitializedRef.current = true;
    const defaults = settings.autocomplete_plan_role_defaults || {};
    const persisted = settings.autocomplete_plan_model || "";
    const parsed = parseModelKey(persisted.includes("/") ? persisted : defaults[persisted] || persisted);
    const baseline = parsed.modelId ? parsed.composite : Object.values(defaults)[0] || "";
    const fromSession = readSessionPlanModel();
    const sessionNorm = fromSession
      ? normalizeStoredModels([fromSession], defaults)[0]
      : null;
    setPlanModel(sessionNorm || baseline);
  }, [
    settingsFetched,
    settings.autocomplete_plan_model,
    settings.autocomplete_plan_role_defaults,
  ]);

  const persistedModels = useMemo(() => {
    const defaults = settings.autocomplete_role_defaults || {};
    const persisted = normalizeStoredModels(settings.autocomplete_models, defaults);
    return persisted.length ? persisted : defaultCycleModels(defaults);
  }, [settings.autocomplete_models, settings.autocomplete_role_defaults]);

  const handleSettingsChange = useCallback((patch) => {
    setSettings((prev) => ({ ...prev, ...patch }));
  }, []);

  const handlePlanModelChange = useCallback((next) => {
    setPlanModel(next);
    writeSessionPlanModel(next);
  }, []);

  const buildPlanRequestBody = useCallback(
    () => ({
      sections: sections.map(({ title, description, body, plan, proposal }) => ({
        title,
        description,
        body,
        plan: plan || "",
        proposal: proposal || "",
      })),
      plan_model: planModel || undefined,
      job_text: jobText || "",
      additional_user_info: additionalUserInfo || "",
      additional_company_info: additionalCompanyInfo || "",
      structure_instructions: structureInstructions || "",
      company_report: companyReport || "",
      top_docs: topDocs || [],
      company_name: companyName || "",
      job_title: jobTitle || "",
      location: location || "",
      language: language || "",
      salary: salary || "",
      requirements: requirements || [],
      competences: competences || {},
      point_of_contact: pointOfContact || null,
    }),
    [
      sections,
      planModel,
      jobText,
      additionalUserInfo,
      additionalCompanyInfo,
      structureInstructions,
      companyReport,
      topDocs,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      competences,
      pointOfContact,
    ]
  );

  const applyPlanResponse = useCallback((data, sectionIndex) => {
    const plans = data.plans || {};
    const proposals = data.proposals || {};
    if (data.context_summary?.trim()) {
      setContextSummary(String(data.context_summary).trim());
      suggestionHistoryRef.current?.setFixedContext(String(data.context_summary).trim());
    }
    if (Array.isArray(data.context_summary_warnings)) {
      setContextSummaryWarnings(data.context_summary_warnings);
      if (data.context_summary_warnings.length) {
        console.warn("Context summary warnings:", data.context_summary_warnings);
      }
    }
    if (sectionIndex != null) {
      const planText = plans[String(sectionIndex)];
      if (planText == null) return;
      const proposalText = proposals[String(sectionIndex)];
      setSections((prev) =>
        prev.map((s, i) =>
          i === sectionIndex
            ? {
                ...s,
                plan: String(planText),
                ...(proposalText != null
                  ? {
                      proposal: String(proposalText),
                      proposalSourceBody: s.body || "",
                    }
                  : {}),
              }
            : s
        )
      );
      return;
    }
    setSections((prev) =>
      prev.map((s, i) => {
        const nextPlan = plans[String(i)] != null ? String(plans[String(i)]) : s.plan || "";
        const nextProposal =
          proposals[String(i)] != null ? String(proposals[String(i)]) : s.proposal || "";
        return {
          ...s,
          plan: nextPlan,
          ...(proposals[String(i)] != null
            ? { proposal: nextProposal, proposalSourceBody: s.body || "" }
            : {}),
        };
      })
    );
  }, []);

  const refreshSectionPlan = useCallback(
    async (sectionIndex) => {
      if (!planModel || sectionIndex == null) return;
      const reqId = (planRequestIdsRef.current[sectionIndex] || 0) + 1;
      planRequestIdsRef.current[sectionIndex] = reqId;
      setPlanningSectionIndices((prev) => {
        const next = new Set(prev);
        next.add(sectionIndex);
        return next;
      });
      setPlanError(null);
      try {
        const result = await fetchWithHeartbeat("/api/autocomplete/plan/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            ...buildPlanRequestBody(),
            plan_all: false,
            section_index: sectionIndex,
          }),
        });
        if (planRequestIdsRef.current[sectionIndex] !== reqId) return;
        if (result.isHeartbeat) return;
        const data = result.data;
        if (!data || data.status !== "ok") {
          setPlanError(data?.detail || data?.message || "Planning failed");
          return;
        }
        applyPlanResponse(data, sectionIndex);
        if (typeof data.cost === "number" && data.cost > 0) {
          totalCostRef.current += data.cost;
          planCostRef.current += data.cost;
        }
      } catch (e) {
        if (planRequestIdsRef.current[sectionIndex] !== reqId) return;
        setPlanError(e.message || String(e));
      } finally {
        if (planRequestIdsRef.current[sectionIndex] === reqId) {
          setPlanningSectionIndices((prev) => {
            const next = new Set(prev);
            next.delete(sectionIndex);
            return next;
          });
        }
      }
    },
    [planModel, buildPlanRequestBody, applyPlanResponse]
  );

  const refreshAllSectionPlans = useCallback(async () => {
    if (!planModel) return;
    const reqId = ++planBatchRequestIdRef.current;
    const allIndices = sections.map((_, index) => index);
    setPlanningSectionIndices(new Set(allIndices));
    setPlanError(null);
    try {
      const result = await fetchWithHeartbeat("/api/autocomplete/plan/", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ ...buildPlanRequestBody(), plan_all: true }),
      });
      if (reqId !== planBatchRequestIdRef.current) return;
      if (result.isHeartbeat) return;
      const data = result.data;
      if (!data || data.status !== "ok") {
        setPlanError(data?.detail || data?.message || "Planning failed");
        return;
      }
      applyPlanResponse(data, null);
      if (typeof data.cost === "number" && data.cost > 0) {
        totalCostRef.current += data.cost;
        planCostRef.current += data.cost;
      }
    } catch (e) {
      if (reqId !== planBatchRequestIdRef.current) return;
      setPlanError(e.message || String(e));
    } finally {
      if (reqId === planBatchRequestIdRef.current) {
        setPlanningSectionIndices(new Set());
      }
    }
  }, [planModel, sections, buildPlanRequestBody, applyPlanResponse]);

  const plansLoadingAll = planningSectionIndices.size > 0;

  useEffect(() => {
    if (!planModel || !settingsFetched) return;
    if (lastAutoPlannedScopeRef.current === draftScope) return;
    lastAutoPlannedScopeRef.current = draftScope;
    refreshAllSectionPlans();
  }, [planModel, settingsFetched, draftScope, refreshAllSectionPlans]);

  const handleActiveChange = useCallback((sectionIndex, cursor) => {
    setActiveSectionIndex(sectionIndex);
    setCursorInSection(cursor);
  }, []);

  const registerTextareaRef = useCallback((index, el) => {
    textareaRefs.current[index] = el;
  }, []);

  const getCompletionPrefixKey = useCallback(
    (sectionIndex, cursor) => {
      return buildAutocompleteDraftPrefix(sections, sectionIndex, cursor);
    },
    [sections]
  );

  const clearCompletionCache = useCallback(() => {
    completionCacheRef.current = createEmptyCompletionCache();
    extendCacheInFlightRef.current = false;
  }, []);

  const updateCompletionCacheFromResponse = useCallback(
    (data, prefixKey, modelKey) => {
      const raw = (data.raw_suggestion_text || data.suggestion_text || "").trim();
      if (!raw) return;
      completionCacheRef.current = {
        raw,
        offset: data.cache_offset_next ?? data.cache_offset ?? 0,
        prefixKey,
        modelKey: modelKey || data.model_used || "",
      };
    },
    []
  );

  const recordSuggestionAccepted = useCallback((acceptedInsert) => {
    suggestionHistoryRef.current?.acceptPending(acceptedInsert);
  }, []);

  const insertSuggestionAtCursor = useCallback(
    (suggestionText, sectionIndex, { recordHistory = true } = {}) => {
      const text = String(suggestionText || "").trim();
      if (!text) return { ok: false };
      const el = textareaRefs.current[sectionIndex];
      const cur = el ? el.selectionStart ?? cursorInSection : cursorInSection;
      const active = sections[sectionIndex];
      if (!active) return { ok: false };
      const { text: nextBody, cursor: nextCursor, inserted } = acceptSuggestion(
        active.body,
        cur,
        text
      );
      setSections((prev) =>
        prev.map((s, i) =>
          i === sectionIndex
            ? { ...s, body: nextBody, proposalSourceBody: nextBody }
            : s
        )
      );
      setCursorInSection(nextCursor);
      if (recordHistory) {
        recordSuggestionAccepted(inserted);
      }
      requestAnimationFrame(() => {
        const ta = textareaRefs.current[sectionIndex];
        if (ta) {
          ta.focus();
          ta.setSelectionRange(nextCursor, nextCursor);
        }
      });
      return { ok: true, inserted };
    },
    [sections, cursorInSection, recordSuggestionAccepted]
  );

  const handleCycleModelsChange = useCallback((next) => {
    setCycleModels(next);
    setCompletionModel((prev) => {
      if (prev && next.includes(prev)) return prev;
      return next[0] || "";
    });
  }, []);

  const handleActiveCompletionModelChange = useCallback(
    (composite) => {
      if (!composite) return;
      const current = resolveCompletionModel(completionModel, modelUsed, cycleModels);
      if (composite === current) return;
      suggestionHistoryRef.current?.rejectPending();
      clearCompletionCache();
      setSuggestion("");
      setCompletionModel(composite);
    },
    [completionModel, modelUsed, cycleModels, clearCompletionCache]
  );

  const handleCycleModelActivated = useCallback(
    (composite) => {
      if (composite) handleActiveCompletionModelChange(composite);
    },
    [handleActiveCompletionModelChange]
  );

  const applyCompletionPayload = useCallback(
    (
      data,
      {
        letterTextAtRequest,
        sectionIndex,
        curAfter,
        autoInsert,
        prefixKey,
        modelKey,
        silent,
      }
    ) => {
      const suggestionText = (data.suggestion_text || "").trim();
      const truncatedBy = data.truncated_by;

      setModelUsed(data.model_used || "");
      if (data.model_used) {
        setCompletionModel(data.model_used);
      }
      if (!silent) {
        setStatusMeta({
          cost: data.cost,
          cached_tokens: data.cached_tokens,
          truncated_by: truncatedBy,
          cache_hit: data.cache_hit,
          cache_has_more: data.cache_has_more,
        });
      }
      if (typeof data.cost === "number" && data.cost > 0) {
        totalCostRef.current += data.cost;
      }

      if (Array.isArray(data.warnings) && data.warnings.length > 0) {
        const onlyRepeat = data.warnings.includes("continuation_only_repeated_existing_text");
        if (!silent) {
          setError(
            onlyRepeat
              ? "The model repeated text already in your draft; nothing new to insert. Try Tab again or another model."
              : data.warnings.join("; ")
          );
          setSuggestion("");
        }
        suggestionHistoryRef.current?.rejectPending();
        return { ok: false };
      }

      const hist = suggestionHistoryRef.current;
      if (data.cache_prefix) {
        hist?.setFixedContext(data.cache_prefix);
      }
      const fullSuggestion = (data.raw_suggestion_text || suggestionText || "").trim();
      if (fullSuggestion) {
        updateCompletionCacheFromResponse(data, prefixKey, modelKey);
        if (!silent) {
          hist?.startPending({
            text: letterTextAtRequest,
            suggestion: fullSuggestion,
            model: data.model_used,
            cost: data.cost,
          });
        }
      }

      const active = sections[sectionIndex];
      const alreadyInserted =
        active && suggestionAlreadyAtCursor(active.body, curAfter, suggestionText);

      const shouldAutoInsert =
        autoInsert && suggestionText && !alreadyInserted;

      if (shouldAutoInsert || (truncatedBy && suggestionText && !alreadyInserted)) {
        insertSuggestionAtCursor(suggestionText, sectionIndex);
        if (!silent) {
          setSuggestion("");
          setError(null);
        }
        return { ok: true, inserted: true };
      }

      if (truncatedBy && !suggestionText) {
        if (!silent) {
          setError(
            "Completion hit the word limit but produced no new text to insert. Try Tab again or another model."
          );
          setSuggestion("");
        }
        suggestionHistoryRef.current?.rejectPending();
        return { ok: false };
      }

      if (autoInsert && suggestionText && alreadyInserted) {
        suggestionHistoryRef.current?.rejectPending();
        if (!silent) {
          setSuggestion("");
          setError(null);
        }
        return { ok: true, inserted: false };
      }

      if (!silent) {
        setSuggestion(suggestionText);
        setError(null);
      }
      return { ok: true, inserted: false };
    },
    [sections, insertSuggestionAtCursor, updateCompletionCacheFromResponse]
  );

  const requestCompletion = useCallback(
    async ({
      model,
      cycleNext,
      autoInsert = false,
      cacheOffset = 0,
      extendCache = false,
      silent = false,
    } = {}) => {
      const el = textareaRefs.current[activeSectionIndex];
      const cur = el ? el.selectionStart ?? cursorInSection : cursorInSection;
      const activeSec = sections[activeSectionIndex];
      if (!extendCache && !shouldUseCompletionModelForSection(activeSec, cur)) {
        if (!silent) {
          setError(
            "Completion model is used only after you edit a paragraph. Tab streams the hidden proposal until then."
          );
        }
        return;
      }
      const reqId = ++requestIdRef.current;
      const letterTextAtRequest = sectionsToBodyText(sections);
      const prefixKey = getCompletionPrefixKey(activeSectionIndex, cur);
      const modelForRequest = resolveCompletionModel(
        model || completionModel,
        modelUsed,
        cycleModels
      );
      if (!silent) {
        setLoading(true);
        setError(null);
      }

      try {
        const body = {
          sections: sections.map(({ title, description, body: b }) => ({
            title,
            description,
            body: b,
          })),
          active_section_index: activeSectionIndex,
          cursor_in_section: cur,
          cache_offset: cacheOffset,
          extend_cache: extendCache,
          job_text: jobText || "",
          additional_user_info: additionalUserInfo || "",
          additional_company_info: additionalCompanyInfo || "",
          structure_instructions: structureInstructions || "",
          company_report: companyReport || "",
          top_docs: topDocs || [],
          company_name: companyName || "",
          job_title: jobTitle || "",
          location: location || "",
          language: language || "",
          salary: salary || "",
          requirements: requirements || [],
          competences: competences || {},
          point_of_contact: pointOfContact || null,
        };
        if (model) body.model = model;
        if (cycleNext) body.cycle_next = true;
        const activePlan = activeSec?.plan;
        if (activePlan?.trim()) {
          body.active_section_plan = activePlan.trim();
        }
        const activeProposal = activeSec?.proposal;
        if (activeProposal?.trim()) {
          body.active_section_proposal = activeProposal.trim();
          body.section_proposal_stale = isSectionProposalStale(activeSec);
        }
        if (contextSummary?.trim()) {
          body.context_summary = contextSummary.trim();
        }

        const result = await fetchWithHeartbeat("/api/autocomplete/complete/", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify(body),
        });

        if (reqId !== requestIdRef.current) return;
        if (result.isHeartbeat) return;

        const data = result.data;
        if (!data || data.status !== "ok") {
          if (!silent) {
            setError(data?.detail || data?.message || "Completion failed");
          }
          return;
        }

        const elAfter = textareaRefs.current[activeSectionIndex];
        const curAfter = elAfter
          ? elAfter.selectionStart ?? cursorInSection
          : cursorInSection;

        applyCompletionPayload(data, {
          letterTextAtRequest,
          sectionIndex: activeSectionIndex,
          curAfter,
          autoInsert,
          prefixKey,
          modelKey: modelForRequest,
          silent,
        });

        const cache = completionCacheRef.current;
        if (
          cache.raw &&
          cache.prefixKey === prefixKey &&
          !isProposalAutocompleteCache(cache) &&
          shouldExtendAutocompleteCache(cache.offset, cache.raw.length) &&
          !extendCacheInFlightRef.current
        ) {
          extendCacheInFlightRef.current = true;
          requestCompletion({
            model: modelForRequest || undefined,
            extendCache: true,
            cacheOffset: cache.offset,
            silent: true,
          }).finally(() => {
            extendCacheInFlightRef.current = false;
          });
        }
      } catch (e) {
        if (reqId !== requestIdRef.current) return;
        if (!silent) setError(e.message || String(e));
      } finally {
        if (reqId === requestIdRef.current && !silent) setLoading(false);
      }
    },
    [
      sections,
      activeSectionIndex,
      cursorInSection,
      jobText,
      additionalUserInfo,
      additionalCompanyInfo,
      structureInstructions,
      companyReport,
      topDocs,
      companyName,
      jobTitle,
      location,
      language,
      salary,
      requirements,
      competences,
      pointOfContact,
      contextSummary,
      completionModel,
      modelUsed,
      cycleModels,
      getCompletionPrefixKey,
      applyCompletionPayload,
    ]
  );

  const seedProposalCompletionCache = useCallback(
    (sectionIndex, cursor) => {
      const section = sections[sectionIndex];
      if (!canUseProposalAutocompleteBuffer(section)) return false;
      const prefixKey = getCompletionPrefixKey(sectionIndex, cursor);
      const cache = completionCacheRef.current;
      if (
        cache.raw &&
        cache.prefixKey === prefixKey &&
        isProposalAutocompleteCache(cache) &&
        cache.offset < cache.raw.length
      ) {
        return true;
      }
      const raw = buildSectionProposalAutocompleteBuffer(section, cursor);
      if (!raw) return false;
      completionCacheRef.current = {
        raw,
        offset: 0,
        prefixKey,
        modelKey: PROPOSAL_AUTOCOMPLETE_CACHE_SOURCE,
      };
      return true;
    },
    [sections, getCompletionPrefixKey]
  );

  const tryServeNextCacheChunk = useCallback(
    ({ autoInsert = true } = {}) => {
      const el = textareaRefs.current[activeSectionIndex];
      const cur = el ? el.selectionStart ?? cursorInSection : cursorInSection;
      const cache = completionCacheRef.current;
      if (!cache.raw || cache.offset >= cache.raw.length) return false;

      const { chunk, newOffset, truncatedBy, hasMore } = sliceNextAutocompleteChunk(
        cache.raw,
        cache.offset,
        {
          maxWords: settings.autocomplete_max_words,
          stopOnPeriod: settings.autocomplete_stop_on_period,
        }
      );
      if (!chunk) return false;

      cache.offset = newOffset;
      const active = sections[activeSectionIndex];
      const alreadyInserted =
        active && suggestionAlreadyAtCursor(active.body, cur, chunk);

      if (autoInsert && !alreadyInserted) {
        insertSuggestionAtCursor(chunk, activeSectionIndex);
        setSuggestion("");
        setStatusMeta({
          cache_hit: true,
          truncated_by: truncatedBy,
          cache_has_more: hasMore,
        });
      } else if (!alreadyInserted) {
        setSuggestion(chunk);
        setStatusMeta({
          cache_hit: true,
          truncated_by: truncatedBy,
          cache_has_more: hasMore,
        });
      }

      if (
        !isProposalAutocompleteCache(cache) &&
        shouldExtendAutocompleteCache(cache.offset, cache.raw.length)
      ) {
        const modelForRequest = resolveCompletionModel(completionModel, modelUsed, cycleModels);
        if (!extendCacheInFlightRef.current) {
          extendCacheInFlightRef.current = true;
          requestCompletion({
            model: modelForRequest || undefined,
            extendCache: true,
            cacheOffset: cache.offset,
            silent: true,
          }).finally(() => {
            extendCacheInFlightRef.current = false;
          });
        }
      }
      return true;
    },
    [
      activeSectionIndex,
      cursorInSection,
      sections,
      settings.autocomplete_max_words,
      settings.autocomplete_stop_on_period,
      getCompletionPrefixKey,
      insertSuggestionAtCursor,
      completionModel,
      modelUsed,
      cycleModels,
      requestCompletion,
    ]
  );

  const applyAccept = useCallback(() => {
    if (!suggestion) return;
    const result = insertSuggestionAtCursor(suggestion, activeSectionIndex);
    if (result.ok) {
      setSuggestion("");
      setStatusMeta(null);
    }
  }, [suggestion, activeSectionIndex, insertSuggestionAtCursor]);

  const activeCompletionModel = resolveCompletionModel(
    completionModel,
    modelUsed,
    cycleModels
  );

  const handleKeyDown = useCallback(
    (e) => {
      if (e.key === "Tab") {
        e.preventDefault();
        const el = textareaRefs.current[activeSectionIndex];
        const cur = el ? el.selectionStart ?? cursorInSection : cursorInSection;
        if (!tryServeNextCacheChunk({ autoInsert: true })) {
          const activeSec = sections[activeSectionIndex];
          if (
            canUseProposalAutocompleteBuffer(activeSec) &&
            seedProposalCompletionCache(activeSectionIndex, cur) &&
            tryServeNextCacheChunk({ autoInsert: true })
          ) {
            setError(null);
            return;
          }
          clearCompletionCache();
          const modelForTab = resolveCompletionModel(completionModel, modelUsed, cycleModels);
          requestCompletion({
            model: modelForTab || undefined,
            autoInsert: true,
          });
        }
        return;
      }

      if (e.key === " " && shouldAcceptOnSpace(suggestion, e.shiftKey)) {
        e.preventDefault();
        applyAccept();
        return;
      }

      if (e.key === "Escape") {
        suggestionHistoryRef.current?.rejectPending();
        clearCompletionCache();
        setSuggestion("");
        setError(null);
      }
    },
    [
      suggestion,
      applyAccept,
      requestCompletion,
      completionModel,
      modelUsed,
      cycleModels,
      tryServeNextCacheChunk,
      seedProposalCompletionCache,
      sections,
      activeSectionIndex,
      cursorInSection,
      clearCompletionCache,
    ]
  );

  const handleKeyUp = useCallback(
    (e) => {
      const el = textareaRefs.current[activeSectionIndex];
      if (el) setCursorInSection(el.selectionStart ?? 0);
    },
    [activeSectionIndex]
  );

  const handleSaveLetter = useCallback(
    async (copyText) => {
      await onSaveAndCopy({
        letterText: copyText,
        sections,
        proposalLetterText: sectionsToProposalText(sections),
        autocompleteHistory: suggestionHistoryRef.current?.finalizeForSave(),
        completionModel: modelUsed || completionModel,
        planModel,
        planCost: planCostRef.current,
        cycleModels,
        totalCost: totalCostRef.current,
      });
    },
    [onSaveAndCopy, sections, modelUsed, completionModel, planModel, cycleModels]
  );

  const saveCopy = useSaveAndCopy({
    letterText: bodyText,
    onSave: onSaveAndCopy ? handleSaveLetter : undefined,
    saving: savingFinal,
    resetKey: `${draftScope}\x1e${bodyText}`,
    requireSave: true,
  });

  return (
    <div
      style={{
        display: "flex",
        gap: 20,
        height: "calc(100vh - 120px)",
        minHeight: 400,
      }}
    >
      <AutocompleteModelPanel
        cycleModels={cycleModels}
        activeCompletionModel={activeCompletionModel}
        onActiveCompletionModelChange={handleActiveCompletionModelChange}
        onCycleModelsChange={handleCycleModelsChange}
        onCycleModelActivated={handleCycleModelActivated}
        persistedModels={persistedModels}
        roleDefaults={settings.autocomplete_role_defaults || {}}
        onPersisted={handleSettingsChange}
        planModel={planModel}
        onPlanModelChange={handlePlanModelChange}
        persistedPlanModel={settings.autocomplete_plan_model || ""}
        planRoleDefaults={settings.autocomplete_plan_role_defaults || {}}
        onPlanPersisted={handleSettingsChange}
        onRefreshPlans={refreshAllSectionPlans}
        plansLoading={plansLoadingAll}
      />

      <div style={{ flex: 1, minWidth: 0, display: "flex", flexDirection: "column", gap: 16 }}>
        <div
          style={{
            flex: 1,
            minHeight: 0,
            display: "flex",
            flexDirection: "column",
            padding: 16,
            border: "1px solid var(--border-color)",
            borderRadius: 8,
            background: "var(--panel-bg)",
          }}
        >
          <div
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "flex-start",
              gap: 12,
              flexWrap: "wrap",
              marginBottom: 8,
            }}
          >
            <h2 style={{ margin: 0, fontSize: 18, color: "var(--text-color)" }}>
              Autocomplete letter
            </h2>
            <SaveAndCopyButton
              id="autocomplete-save-copy-btn"
              onClick={saveCopy.handleClick}
              disabled={saveCopy.disabled}
              savedState={saveCopy.buttonSavedState}
              label={saveCopy.label}
            />
          </div>
          <SaveCopyErrorBanner
            message={saveCopy.saveError}
            style={{
              marginBottom: 12,
              borderBottom: "none",
              border: "1px solid var(--border-color)",
              borderRadius: 6,
            }}
          />
          <p style={{ margin: "0 0 12px", fontSize: 13, color: "var(--secondary-text-color)" }}>
            Section titles and goals guide the AI only — the saved letter uses paragraph text
            below each goal. Tab first streams the hidden proposal (up to {settings.autocomplete_max_words} words
            {settings.autocomplete_stop_on_period ? ", until period" : ""}); when that runs out—or after you edit a
            paragraph—Tab uses the completion model. Chunks are cached for fast repeat Tab.
            Space: accept ghost text. Pick the active model in the panel on the left.
          </p>

          <div style={{ marginBottom: 12, display: "flex", flexWrap: "wrap", gap: 8, alignItems: "center" }}>
            <span style={{ fontSize: 12, color: "var(--secondary-text-color)" }}>
              Model: <strong>{activeCompletionModel || "—"}</strong>
              {loading ? " · Loading…" : ""}
              {statusMeta?.cache_hit ? " · reused recent completion" : ""}
              {statusMeta?.cached_tokens > 0 ? ` · ${statusMeta.cached_tokens} cached tok` : ""}
              {statusMeta?.cost > 0 ? ` · $${Number(statusMeta.cost).toFixed(4)}` : ""}
              {statusMeta?.truncated_by ? ` · truncated: ${statusMeta.truncated_by}` : ""}
            </span>
          </div>

          {(error || planError) && (
            <div
              style={{
                marginBottom: 12,
                padding: 10,
                fontSize: 13,
                color: "#b91c1c",
                background: "#fef2f2",
                border: "1px solid #fecaca",
                borderRadius: 6,
              }}
            >
              {error || planError}
            </div>
          )}

          <AutocompleteSectionsEditor
            sections={sections}
            activeSectionIndex={activeSectionIndex}
            cursorInSection={cursorInSection}
            suggestion={suggestion}
            planningSectionIndices={planningSectionIndices}
            onSaveSectionGoal={refreshSectionPlan}
            onInvalidateCompletionCache={clearCompletionCache}
            onSectionsChange={setSections}
            onActiveChange={handleActiveChange}
            onKeyDown={handleKeyDown}
            onKeyUp={handleKeyUp}
            registerTextareaRef={registerTextareaRef}
            translation={translation}
          />

          {suggestion && (
            <div style={{ marginTop: 8, fontSize: 12, color: "var(--secondary-text-color)" }}>
              Press <kbd>Space</kbd> to accept or <kbd>Tab</kbd> for another chunk.
            </div>
          )}
        </div>
      </div>

      <JobDescriptionColumn
        jobText={jobText}
        companyReport={companyReport}
        contextSummary={contextSummary}
        contextSummaryLoading={plansLoadingAll}
        contextSummaryWarnings={contextSummaryWarnings}
        requirements={requirements}
        competences={competences}
        scaleConfig={competenceScaleConfig}
        overrides={competenceOverrides}
        width="350px"
        languages={languages}
        finalAssemblyText={bodyText}
      />
    </div>
  );
}
