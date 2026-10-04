import type { Attachment, ChatMessage } from "@/api/types";

export type UiMessage = ChatMessage & {
  status?: "streaming" | "stopped" | "error";
  error?: string;
  prompt?: string;
  promptFiles?: Attachment[];
};
