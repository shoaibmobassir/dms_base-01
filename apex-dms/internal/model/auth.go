package model

import (
	"time"

	"github.com/google/uuid"
)

// Role represents a user's role within a firm.
type Role string

const (
	RoleOwner  Role = "owner"
	RoleAdmin  Role = "admin"
	RoleMember Role = "member"
	RoleViewer Role = "viewer"
)

// IsAtLeast checks whether this role is equal to or higher than the required role.
func (r Role) IsAtLeast(required Role) bool {
	return roleRank(r) >= roleRank(required)
}

func roleRank(r Role) int {
	switch r {
	case RoleOwner:
		return 4
	case RoleAdmin:
		return 3
	case RoleMember:
		return 2
	case RoleViewer:
		return 1
	default:
		return 0
	}
}

// Firm represents an organisation (tenant).
type Firm struct {
	FirmID    uuid.UUID  `json:"firm_id"`
	Name      string     `json:"name"`
	Slug      string     `json:"slug"`
	LogoURL   *string    `json:"logo_url,omitempty"`
	Address   any        `json:"address,omitempty"`
	Settings  any        `json:"settings,omitempty"`
	CreatedAt time.Time  `json:"created_at"`
	UpdatedAt time.Time  `json:"updated_at"`
}

// User represents an authenticated user.
type User struct {
	UserID        uuid.UUID  `json:"user_id"`
	Email         string     `json:"email"`
	PasswordHash  string     `json:"-"` // never serialise
	DisplayName   string     `json:"display_name"`
	AvatarURL     *string    `json:"avatar_url,omitempty"`
	EmailVerified bool       `json:"email_verified"`
	MFASecret     *string    `json:"-"` // never serialise
	CreatedAt     time.Time  `json:"created_at"`
	UpdatedAt     time.Time  `json:"updated_at"`
}

// FirmMember represents the membership link between a user and a firm.
type FirmMember struct {
	FirmID   uuid.UUID `json:"firm_id"`
	UserID   uuid.UUID `json:"user_id"`
	Role     Role      `json:"role"`
	JoinedAt time.Time `json:"joined_at"`

	// Joined fields (optional, populated by queries that join users)
	DisplayName string  `json:"display_name,omitempty"`
	Email       string  `json:"email,omitempty"`
	AvatarURL   *string `json:"avatar_url,omitempty"`
}

// Invitation represents a pending firm invitation.
type Invitation struct {
	InviteID   uuid.UUID  `json:"invite_id"`
	FirmID     uuid.UUID  `json:"firm_id"`
	Email      string     `json:"email"`
	Role       Role       `json:"role"`
	InvitedBy  uuid.UUID  `json:"invited_by"`
	Token      string     `json:"-"` // not exposed in API responses
	ExpiresAt  time.Time  `json:"expires_at"`
	AcceptedAt *time.Time `json:"accepted_at,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
}

// APIKey represents a personal API key.
type APIKey struct {
	KeyID      uuid.UUID  `json:"key_id"`
	UserID     uuid.UUID  `json:"user_id"`
	FirmID     uuid.UUID  `json:"firm_id"`
	Name       string     `json:"name"`
	KeyHash    string     `json:"-"`
	KeyPrefix  string     `json:"key_prefix"`
	LastUsedAt *time.Time `json:"last_used_at,omitempty"`
	RateLimit  int        `json:"rate_limit"`
	RevokedAt  *time.Time `json:"revoked_at,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
}

// RefreshToken represents a stored refresh token.
type RefreshToken struct {
	TokenID    uuid.UUID  `json:"token_id"`
	UserID     uuid.UUID  `json:"user_id"`
	TokenHash  string     `json:"-"`
	DeviceInfo any        `json:"device_info,omitempty"`
	ExpiresAt  time.Time  `json:"expires_at"`
	RevokedAt  *time.Time `json:"revoked_at,omitempty"`
	CreatedAt  time.Time  `json:"created_at"`
}
