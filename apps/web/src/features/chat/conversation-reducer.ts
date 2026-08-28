import type { ChatStreamEvent, Conversation } from "@mosaic/contracts";

export interface ConversationReducerState {
  conversation: Conversation;
  requestId: string | null;
  messageId: string | null;
  /** Last accepted sequence for this subscription. -1 means no event yet. */
  lastSequence: number;
  terminal: boolean;
}

/**
 * The public convenience reducer intentionally keeps only a Conversation in
 * its return type. The persisted sequence cursor lives on that public object;
 * this cache only retains request/message/terminal metadata for the same object.
 * The stateful reducer below remains the canonical implementation.
 */
const reducerMetadata = new WeakMap<object, Omit<ConversationReducerState, "conversation">>();

function copyConversation(conversation: Conversation): Conversation {
  return {
    ...conversation,
    messages: conversation.messages.map((message) => ({ ...message })),
  };
}

function findStreamingAssistant(
  conversation: Conversation,
  requestId: string | null,
): Conversation["messages"][number] | undefined {
  if (requestId === null) return undefined;
  return conversation.messages.find(
    (message) =>
      message.role === "assistant" &&
      message.status === "streaming" &&
      message.request_id === requestId,
  );
}

function initialMetadata(
  conversation: Conversation,
): Omit<ConversationReducerState, "conversation"> {
  const requestId = conversation.active_request_id;
  const assistant = findStreamingAssistant(conversation, requestId);
  const lastSequence = conversation.active_request_cursor ?? -1;
  return {
    requestId,
    messageId: assistant?.message_id ?? null,
    lastSequence,
    // An active request without a placeholder is an intended fresh stream, not
    // a terminal conversation. A conversation with no active request is
    // terminal until a caller creates a new request.
    terminal: requestId === null,
  };
}

export function createConversationReducerState(
  conversation: Conversation,
): ConversationReducerState {
  const copied = copyConversation(conversation);
  const metadata = initialMetadata(copied);
  reducerMetadata.set(copied, metadata);
  return { conversation: copied, ...metadata };
}

function metadataFor(
  conversation: Conversation,
): Omit<ConversationReducerState, "conversation"> {
  return reducerMetadata.get(conversation) ?? initialMetadata(conversation);
}

function unchanged(state: ConversationReducerState): ConversationReducerState {
  // Do not advance cursors for ignored events. This makes stale subscriptions
  // harmless and lets a later correctly ordered event still be accepted.
  return state;
}

function attachMetadata(
  conversation: Conversation,
  metadata: Omit<ConversationReducerState, "conversation">,
): void {
  reducerMetadata.set(conversation, metadata);
}

/**
 * Fold one stream event. Events must have exactly the active request/message
 * IDs, begin with started/0, and advance one sequence at a time. Duplicate,
 * stale, wrong-request, and post-terminal events are ignored.
 */
export function reduceConversation(
  state: ConversationReducerState,
  event: ChatStreamEvent,
): ConversationReducerState {
  const eventType: ChatStreamEvent["type"] = event.type;
  const metadata = state;

  if (metadata.terminal) return unchanged(state);

  // A fresh active request may not have persisted its assistant placeholder
  // yet. It can bind only to that exact active request and a started/0 event.
  if (metadata.messageId === null) {
    if (
      eventType !== "started" ||
      event.sequence !== 0 ||
      event.conversation_id !== state.conversation.conversation_id ||
      metadata.requestId === null ||
      event.request_id !== metadata.requestId
    ) {
      return unchanged(state);
    }
    const assistant = state.conversation.messages.find(
      (message) =>
        message.message_id === event.message_id && message.role === "assistant",
    );
    if (!assistant && state.conversation.messages.some(
      (message) => message.message_id === event.message_id,
    )) return unchanged(state);

    const nextMetadata = {
      requestId: event.request_id,
      messageId: event.message_id,
      lastSequence: 0,
      terminal: false,
    } as const;
    const nextConversation = copyConversation(state.conversation);
    const index = nextConversation.messages.findIndex(
      (message) => message.message_id === event.message_id,
    );
    nextConversation.active_request_id = event.request_id;
    nextConversation.active_request_cursor = 0;
    if (index >= 0) {
      nextConversation.messages[index] = {
        ...nextConversation.messages[index]!,
        status: "streaming",
        request_id: event.request_id,
      };
    } else {
      nextConversation.messages.push({
        message_id: event.message_id,
        role: "assistant",
        content: "",
        status: "streaming",
        created_at: nextConversation.updated_at,
        request_id: event.request_id,
      });
    }
    attachMetadata(nextConversation, nextMetadata);
    return { conversation: nextConversation, ...nextMetadata };
  }

  if (
    event.request_id !== metadata.requestId ||
    event.conversation_id !== state.conversation.conversation_id ||
    event.message_id !== metadata.messageId ||
    event.sequence !== metadata.lastSequence + 1
  ) {
    return unchanged(state);
  }
  if (metadata.lastSequence < 0) {
    if (eventType !== "started" || event.sequence !== 0) return unchanged(state);
    const nextMetadata = {
      requestId: metadata.requestId,
      messageId: metadata.messageId,
      lastSequence: 0,
      terminal: false,
    } as const;
    const nextConversation = copyConversation(state.conversation);
    nextConversation.active_request_cursor = 0;
    attachMetadata(nextConversation, nextMetadata);
    return { conversation: nextConversation, ...nextMetadata };
  }
  if (event.sequence === 0 || eventType === "started") {
    // started/0 is only legal as the first event; all later events must be a
    // non-started event at the next sequence.
    return unchanged(state);
  }

  const messageIndex = state.conversation.messages.findIndex(
    (message) => message.message_id === metadata.messageId,
  );
  if (messageIndex < 0) return unchanged(state);

  const nextConversation = copyConversation(state.conversation);
  const message = nextConversation.messages[messageIndex]!;
  const nextMetadata: Omit<ConversationReducerState, "conversation"> = {
    requestId: metadata.requestId,
    messageId: metadata.messageId,
    lastSequence: event.sequence,
    terminal: false,
  };
  nextConversation.active_request_cursor = event.sequence;

  switch (eventType) {
    case "delta":
      const deltaEvent = event as Extract<ChatStreamEvent, { type: "delta" }>;
      nextConversation.messages[messageIndex] = {
        ...message,
        content: `${message.content}${deltaEvent.delta}`,
        status: "streaming",
        request_id: metadata.requestId,
      };
      break;
    case "completed":
      const completedEvent = event as Extract<ChatStreamEvent, { type: "completed" }>;
      nextConversation.messages[messageIndex] = {
        ...message,
        content: completedEvent.content,
        status: "complete",
        request_id: metadata.requestId,
      };
      nextConversation.active_request_id = null;
      nextConversation.active_request_cursor = null;
      nextMetadata.terminal = true;
      break;
    case "stopped":
      nextConversation.messages[messageIndex] = {
        ...message,
        status: "stopped",
        request_id: metadata.requestId,
      };
      nextConversation.active_request_id = null;
      nextConversation.active_request_cursor = null;
      nextMetadata.terminal = true;
      break;
    case "failed":
      nextConversation.messages[messageIndex] = {
        ...message,
        status: "failed",
        request_id: metadata.requestId,
      };
      nextConversation.active_request_id = null;
      nextConversation.active_request_cursor = null;
      nextMetadata.terminal = true;
      break;
  }

  attachMetadata(nextConversation, nextMetadata);
  return { conversation: nextConversation, ...nextMetadata };
}

/** Convenience helper for consumers that only need a public Conversation. */
export function reduceConversationEvent(
  conversation: Conversation,
  event: ChatStreamEvent,
): Conversation {
  const state = reducerMetadata.has(conversation)
    ? { conversation, ...metadataFor(conversation) }
    : createConversationReducerState(conversation);
  return reduceConversation(state, event).conversation;
}

export const conversationReducer = reduceConversationEvent;
