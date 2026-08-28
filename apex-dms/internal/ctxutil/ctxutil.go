// Package ctxutil provides context key helpers shared across packages
// to avoid import cycles between auth and middleware.
package ctxutil

import (
	"context"

	"github.com/apex-chambers/dms/internal/model"
	"github.com/google/uuid"
)

type contextKey string

const (
	KeyUserID contextKey = "user_id"
	KeyFirmID contextKey = "firm_id"
	KeyRole   contextKey = "role"
)

// WithUser injects auth values into a context.
func WithUser(ctx context.Context, userID, firmID uuid.UUID, role model.Role) context.Context {
	ctx = context.WithValue(ctx, KeyUserID, userID)
	ctx = context.WithValue(ctx, KeyFirmID, firmID)
	ctx = context.WithValue(ctx, KeyRole, role)
	return ctx
}

// UserIDFromCtx extracts the user ID from the request context.
func UserIDFromCtx(ctx context.Context) uuid.UUID {
	if v, ok := ctx.Value(KeyUserID).(uuid.UUID); ok {
		return v
	}
	return uuid.Nil
}

// FirmIDFromCtx extracts the firm ID from the request context.
func FirmIDFromCtx(ctx context.Context) uuid.UUID {
	if v, ok := ctx.Value(KeyFirmID).(uuid.UUID); ok {
		return v
	}
	return uuid.Nil
}

// RoleFromCtx extracts the role from the request context.
func RoleFromCtx(ctx context.Context) model.Role {
	if v, ok := ctx.Value(KeyRole).(model.Role); ok {
		return v
	}
	return ""
}
