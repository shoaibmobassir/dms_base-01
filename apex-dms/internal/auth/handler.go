package auth

import (
	"encoding/json"
	"log/slog"
	"net/http"

	"github.com/apex-chambers/dms/internal/ctxutil"
)

// Handler holds HTTP handlers for auth endpoints.
type Handler struct {
	service *Service
}

// NewHandler creates a new auth handler.
func NewHandler(service *Service) *Handler {
	return &Handler{service: service}
}

// Register handles POST /auth/register
func (h *Handler) Register(w http.ResponseWriter, r *http.Request) {
	var req RegisterRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	result, err := h.service.Register(r.Context(), req)
	if err != nil {
		slog.Warn("registration failed", "error", err, "email", req.Email)
		writeError(w, http.StatusBadRequest, err.Error())
		return
	}

	writeJSON(w, http.StatusCreated, result)
}

// Login handles POST /auth/login
func (h *Handler) Login(w http.ResponseWriter, r *http.Request) {
	var req LoginRequest
	if err := json.NewDecoder(r.Body).Decode(&req); err != nil {
		writeError(w, http.StatusBadRequest, "invalid request body")
		return
	}

	result, err := h.service.Login(r.Context(), req)
	if err != nil {
		slog.Warn("login failed", "error", err, "email", req.Email)
		writeError(w, http.StatusUnauthorized, "invalid credentials")
		return
	}

	writeJSON(w, http.StatusOK, result)
}

// Refresh handles POST /auth/refresh
func (h *Handler) Refresh(w http.ResponseWriter, r *http.Request) {
	var body struct {
		RefreshToken string `json:"refresh_token"`
	}
	if err := json.NewDecoder(r.Body).Decode(&body); err != nil || body.RefreshToken == "" {
		writeError(w, http.StatusBadRequest, "refresh_token is required")
		return
	}

	result, err := h.service.Refresh(r.Context(), body.RefreshToken)
	if err != nil {
		slog.Warn("refresh failed", "error", err)
		writeError(w, http.StatusUnauthorized, "invalid refresh token")
		return
	}

	writeJSON(w, http.StatusOK, result)
}

// Logout handles POST /auth/logout (requires auth)
func (h *Handler) Logout(w http.ResponseWriter, r *http.Request) {
	userID := ctxutil.UserIDFromCtx(r.Context())
	if err := h.service.Logout(r.Context(), userID); err != nil {
		slog.Error("logout failed", "error", err, "user_id", userID)
		writeError(w, http.StatusInternalServerError, "logout failed")
		return
	}
	writeJSON(w, http.StatusOK, map[string]string{"status": "logged out"})
}

// Me handles GET /me (requires auth)
func (h *Handler) Me(w http.ResponseWriter, r *http.Request) {
	userID := ctxutil.UserIDFromCtx(r.Context())
	user, err := h.service.repo.FindUserByID(r.Context(), userID)
	if err != nil || user == nil {
		writeError(w, http.StatusNotFound, "user not found")
		return
	}

	firmID := ctxutil.FirmIDFromCtx(r.Context())
	role := ctxutil.RoleFromCtx(r.Context())

	writeJSON(w, http.StatusOK, map[string]any{
		"user":    user,
		"firm_id": firmID,
		"role":    role,
	})
}

// ListMembers handles GET /firms/{firmID}/members (requires auth + member)
func (h *Handler) ListMembers(w http.ResponseWriter, r *http.Request) {
	firmID := ctxutil.FirmIDFromCtx(r.Context())
	members, err := h.service.repo.ListMembers(r.Context(), firmID)
	if err != nil {
		slog.Error("list members failed", "error", err)
		writeError(w, http.StatusInternalServerError, "failed to list members")
		return
	}
	writeJSON(w, http.StatusOK, map[string]any{"members": members})
}

// --- helpers ---

func writeJSON(w http.ResponseWriter, status int, data any) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(data)
}

func writeError(w http.ResponseWriter, status int, msg string) {
	w.Header().Set("Content-Type", "application/json")
	w.WriteHeader(status)
	json.NewEncoder(w).Encode(map[string]string{"error": msg})
}
