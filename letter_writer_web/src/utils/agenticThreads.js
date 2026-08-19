import { AGENTIC_TOPICS } from "../constants/feedbackTopics.js";

export { AGENTIC_TOPICS };

export function normalizeAgenticThreads(threadsPayload = {}, topicMetaPayload = {}) {
  const threadsOut = AGENTIC_TOPICS.reduce((acc, topic) => ({ ...acc, [topic]: [] }), {});
  const topicMetaOut = { ...(topicMetaPayload && typeof topicMetaPayload === "object" ? topicMetaPayload : {}) };

  const assignTopic = (topicKey, rawValue) => {
    if (!topicKey || typeof topicKey !== "string") return;
    const topic = topicKey.trim();
    if (!topic) return;
    if (!(topic in threadsOut)) threadsOut[topic] = [];
    if (Array.isArray(rawValue)) {
      threadsOut[topic] = rawValue;
      return;
    }
    if (!rawValue || typeof rawValue !== "object") {
      threadsOut[topic] = [];
      return;
    }
    const candidateThread = Array.isArray(rawValue.thread)
      ? rawValue.thread
      : Array.isArray(rawValue.comments)
        ? rawValue.comments
        : Array.isArray(rawValue.messages)
          ? rawValue.messages
          : [];
    threadsOut[topic] = candidateThread;
    const round = rawValue.round;
    const done = rawValue.done;
    const messages = rawValue.messages_count ?? rawValue.count ?? rawValue.messages;
    if (round != null || done != null || messages != null || "waiting_for" in rawValue) {
      const nextMeta = {
        ...(topicMetaOut[topic] || {}),
        ...(round != null && { round }),
        ...(messages != null && {
          messages: Number.isFinite(Number(messages)) ? Number(messages) : candidateThread.length,
        }),
        ...(done != null && { done: done === true }),
      };
      if ("waiting_for" in rawValue) {
        const wf = rawValue.waiting_for;
        if (wf != null && typeof wf === "object") nextMeta.waiting_for = wf;
        else if (wf != null && String(wf).trim() !== "") nextMeta.waiting_for = String(wf).trim();
        else delete nextMeta.waiting_for;
      }
      topicMetaOut[topic] = nextMeta;
    }
  };

  if (Array.isArray(threadsPayload)) {
    threadsPayload.forEach((entry) => {
      if (!entry || typeof entry !== "object") return;
      assignTopic(entry.topic || entry.key || entry.name, entry.thread ?? entry.comments ?? entry.messages ?? entry);
    });
  } else if (threadsPayload && typeof threadsPayload === "object") {
    Object.entries(threadsPayload).forEach(([topic, value]) => assignTopic(topic, value));
  }

  return { threads: threadsOut, topicMeta: topicMetaOut };
}

export function stripAgenticThreadFields(state) {
  if (!state || typeof state !== "object") return state;
  const next = { ...state };
  delete next.threads;
  delete next.topic_meta;
  return next;
}
