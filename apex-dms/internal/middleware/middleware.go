package middleware

import (
	"log/slog"
	"net/http"
	"strings"
	"time"

	"github.com/apex-chambers/dms/internal/ctxutil"
	"github.com/apex-chambers/dms/internal/model"
	"github.com/google/uuid"
)

// TokenValidator validates a JWT string and returns user_id, firm_id, role.
// This interface breaks the import cycle — auth.JWTManager implements it.
type TokenValidator interface {
	ValidateToken(tokenString string) (userID, firmID uuid.UUID, role string, err error)
}

// Auth validates the JWT Bearer token and injects user_id, firm_id, role into context.
func Auth(validator TokenValidator) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			header := r.Header.Get("Authorization")
			if header == "" {
				http.Error(w, `{"error":"missing authorization header"}`, http.StatusUnauthorized)
				return
			}

			parts := strings.SplitN(header, " ", 2)
			if len(parts) != 2 || !strings.EqualFold(parts[0], "Bearer") {
				http.Error(w, `{"error":"invalid authorization format"}`, http.StatusUnauthorized)
				return
			}

			userID, firmID, role, err := validator.ValidateToken(parts[1])
			if err != nil {
				slog.Warn("jwt validation failed", "error", err)
				http.Error(w, `{"error":"invalid or expired token"}`, http.StatusUnauthorized)
				return
			}

			ctx := ctxutil.WithUser(r.Context(), userID, firmID, model.Role(role))
			next.ServeHTTP(w, r.WithContext(ctx))
		})
	}
}

// RequireRole creates middleware that ensures the user has at least the given role.
func RequireRole(minRole model.Role) func(http.Handler) http.Handler {
	return func(next http.Handler) http.Handler {
		return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
			role := ctxutil.RoleFromCtx(r.Context())
			if !role.IsAtLeast(minRole) {
				http.Error(w, `{"error":"insufficient permissions"}`, http.StatusForbidden)
				return
			}
			next.ServeHTTP(w, r)
		})
	}
}

// RequestLogger logs each request with latency, status, and method.
func RequestLogger(next http.Handler) http.Handler {
	return http.HandlerFunc(func(w http.ResponseWriter, r *http.Request) {
		start := time.Now()
		ww := &statusWriter{ResponseWriter: w, status: http.StatusOK}
		next.ServeHTTP(ww, r)
		slog.Info("request",
			"method", r.Method,
			"path", r.URL.Path,
			"status", ww.status,
			"duration_ms", time.Since(start).Milliseconds(),
			"remote", r.RemoteAddr,
		)
	})
}

type statusWriter struct {
	http.ResponseWriter
	status int
}

func (w *statusWriter) WriteHeader(code int) {
	w.status = code
	w.ResponseWriter.WriteHeader(code)
}
