import { useEffect } from "react";

const APP = "Precentis";

/** Sets the browser tab title for the current page ("Matters · Precentis"). */
export function usePageTitle(title?: string | null) {
  useEffect(() => {
    document.title = title ? `${title} · ${APP}` : APP;
    return () => {
      document.title = APP;
    };
  }, [title]);
}
