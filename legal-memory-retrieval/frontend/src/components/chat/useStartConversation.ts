import { useNavigate } from "react-router-dom";

/**
 * Open the Assistant ready to work on one matter. The conversation itself is
 * created with the first message, so opening and leaving adds nothing to History.
 */
export function useStartConversation() {
  const navigate = useNavigate();
  const start = (matterId?: string) => navigate(matterId ? `/chat?matter=${encodeURIComponent(matterId)}` : "/chat");
  return { start, starting: false };
}
