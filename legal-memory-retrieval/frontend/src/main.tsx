import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { BrowserRouter } from "react-router-dom";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "@/App";
import { ApiError } from "@/api/client";
import { AppProvider } from "@/context/AppContext";
import { ThemeProvider } from "@/lib/theme";
import "@fontsource-variable/manrope";
import "@fontsource/dm-serif-display/400.css";
import "@fontsource/ibm-plex-mono/400.css";
import "@fontsource/ibm-plex-mono/500.css";
import "@fontsource/ibm-plex-mono/600.css";
import "@fontsource-variable/material-symbols-outlined/wght.css";
import "@/index.css";
import "@/App.css";

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      // Client errors (401/403/404) won't change on retry.
      retry: (count, err) => !(err instanceof ApiError && err.status < 500) && count < 2,
    },
  },
});

// Icons are font ligatures: keep them hidden until the icon font is ready (no flash of icon names).
const showIcons = () => document.documentElement.classList.add("icons-ready");
void document.fonts.load('24px "Material Symbols Outlined Variable"').then(showIcons, showIcons);
setTimeout(showIcons, 3000);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/ui">
          <AppProvider>
            <App />
          </AppProvider>
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  </StrictMode>,
);
