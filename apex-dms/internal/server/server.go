package server

import (
	"io"
	"log/slog"
	"net/http"
	"net/http/httputil"
	"net/url"
	"strings"

	"github.com/apex-chambers/dms/internal/auth"
	"github.com/apex-chambers/dms/internal/config"
	"github.com/apex-chambers/dms/internal/matter"
	"github.com/apex-chambers/dms/internal/middleware"
	"github.com/apex-chambers/dms/internal/model"
	"github.com/go-chi/chi/v5"
	chimw "github.com/go-chi/chi/v5/middleware"
	"github.com/go-chi/cors"
)

// New creates and configures the Chi router with all routes.
func New(
	tokenValidator middleware.TokenValidator,
	authHandler *auth.Handler,
	matterHandler *matter.Handler,
	cfg *config.Config,
) http.Handler {
	r := chi.NewRouter()

	// Global middleware
	r.Use(chimw.RequestID)
	r.Use(chimw.RealIP)
	r.Use(middleware.RequestLogger)
	r.Use(chimw.Recoverer)
	r.Use(cors.Handler(cors.Options{
		AllowedOrigins:   []string{"http://localhost:3000", "http://localhost:5173", "http://localhost:5174", "http://localhost:8080"},
		AllowedMethods:   []string{"GET", "POST", "PATCH", "PUT", "DELETE", "OPTIONS"},
		AllowedHeaders:   []string{"Authorization", "Content-Type", "X-Firm-ID"},
		ExposedHeaders:   []string{"Link"},
		AllowCredentials: true,
		MaxAge:           300,
	}))

	// Health
	r.Get("/", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"service":"apex-dms","version":"0.1.0","health":"ok"}`))
	})
	r.Get("/health", func(w http.ResponseWriter, r *http.Request) {
		w.Header().Set("Content-Type", "application/json")
		w.Write([]byte(`{"status":"ok"}`))
	})

	// Public auth routes
	r.Route("/auth", func(r chi.Router) {
		r.Post("/register", authHandler.Register)
		r.Post("/login", authHandler.Login)
		r.Post("/refresh", authHandler.Refresh)
	})

	// Authenticated routes
	r.Group(func(r chi.Router) {
		r.Use(middleware.Auth(tokenValidator))

		// User
		r.Get("/me", authHandler.Me)
		r.Post("/auth/logout", authHandler.Logout)

		// Firm members
		r.With(middleware.RequireRole(model.RoleMember)).Get("/firms/members", authHandler.ListMembers)

		// Matters (includes clients, practice areas, documents, conversations)
		r.Mount("/matters", matterHandler.Routes())
		r.Mount("/documents", matterHandler.DocumentRoutes())
		r.Mount("/conversations", matterHandler.ConversationRoutes())
	})

	// Doc-search proxy — forwards to Python doc-search service
	if cfg.DocSearchURL != "" {
		mountDocSearchProxy(r, cfg.DocSearchURL)
	}

	// Serve frontend UI at /ui/
	r.Get("/ui", http.RedirectHandler("/ui/", http.StatusMovedPermanently).ServeHTTP)
	r.Get("/ui/*", serveFrontendUI())

	return r
}

// mountDocSearchProxy sets up reverse proxy routes to the doc-search Python service.
func mountDocSearchProxy(r chi.Router, targetURL string) {
	target, err := url.Parse(targetURL)
	if err != nil {
		slog.Error("invalid doc-search URL", "url", targetURL, "error", err)
		return
	}

	proxy := httputil.NewSingleHostReverseProxy(target)
	proxy.ErrorHandler = func(w http.ResponseWriter, r *http.Request, err error) {
		slog.Error("doc-search proxy error", "error", err, "path", r.URL.Path)
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(http.StatusBadGateway)
		w.Write([]byte(`{"error":"doc-search service unavailable"}`))
	}

	// POST /api/doc-search/ask → POST target/ask
	r.Post("/api/doc-search/ask", func(w http.ResponseWriter, r *http.Request) {
		r.URL.Path = "/ask"
		r.Host = target.Host
		proxy.ServeHTTP(w, r)
	})

	// GET /api/doc-search/doc/serve/* → GET target/doc/serve/*
	r.Get("/api/doc-search/doc/serve/{filename}", func(w http.ResponseWriter, r *http.Request) {
		filename := chi.URLParam(r, "filename")
		r.URL.Path = "/doc/serve/" + filename
		r.Host = target.Host
		proxy.ServeHTTP(w, r)
	})

	// GET /api/doc-search/health → GET target/health
	r.Get("/api/doc-search/health", func(w http.ResponseWriter, r *http.Request) {
		resp, err := http.Get(targetURL + "/health")
		if err != nil {
			w.Header().Set("Content-Type", "application/json")
			w.WriteHeader(http.StatusBadGateway)
			w.Write([]byte(`{"error":"doc-search unreachable"}`))
			return
		}
		defer resp.Body.Close()
		w.Header().Set("Content-Type", "application/json")
		w.WriteHeader(resp.StatusCode)
		io.Copy(w, resp.Body)
	})

	slog.Info("doc-search proxy configured", "target", targetURL)
}

// serveFrontendUI serves the Vite-built frontend from frontend/dist/ or falls back to index.html.
func serveFrontendUI() http.HandlerFunc {
	return func(w http.ResponseWriter, r *http.Request) {
		// Strip /ui/ prefix to get the file path
		path := strings.TrimPrefix(r.URL.Path, "/ui/")
		if path == "" || path == "/" {
			path = "index.html"
		}

		// For development, redirect to Vite dev server
		// In production, you'd serve from frontend/dist/
		// For now, serve a simple redirect page that loads from Vite
		w.Header().Set("Content-Type", "text/html; charset=utf-8")
		w.WriteHeader(http.StatusOK)
		w.Write([]byte(`<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>Apex Chambers DMS</title>
  <meta http-equiv="refresh" content="0;url=http://localhost:5173">
</head>
<body>
  <p>Redirecting to <a href="http://localhost:5173">Apex DMS UI</a>...</p>
</body>
</html>`))
	}
}
